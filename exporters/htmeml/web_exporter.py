import mimetypes
import resource
import shutil
import os.path
import os
import argparse
import sys
import time

import filetype
import logging
from discord_markdown import discord_markdown_to_html
from metrics import MetricsReport
from traffic_parser import *
from itertools import batched
import jinja2

logger = logging.getLogger(__name__)

MESSAGES_PER_PAGE = 500
NAVIGATION_RANGE = 10
FILENAME_EXTENSION_MAX_LENGTH = 10
IMAGE_MIME_TYPES = {"image/webp", "image/png", "image/jpeg","image/gif","image/avif"}
AUDIO_MIME_TYPES = {"audio/mpeg", "audio/wav", "audio/mp4","audio/aac", "audio/aacp", "audio/webm", "audio/flac"}

jinja_environment = jinja2.Environment(loader=jinja2.FileSystemLoader("templates/"))
page_template = jinja_environment.get_template("page.html")
index_template = jinja_environment.get_template("index.html")


class AttachmentViewModel:
    def __init__(self, file_name: str | None, is_image: bool, is_audio: bool):
        self.file_name: str | None = file_name
        self.is_image: bool = is_image
        self.is_audio: bool = is_audio

def export_channel(channel: ChannelMetadata, history: ChannelMessageHistory, export_directory: str, traffic_archive: TrafficArchive):
    guild = None
    if channel.guild_id:
        guild = traffic_archive.get_guild_metadata(channel.guild_id)

    channel_directory = os.path.join(export_directory, f"channel_{channel.channel_id}")
    os.makedirs(channel_directory, exist_ok=True)
    os.makedirs(os.path.join(channel_directory, "attachments"), exist_ok=True)

    messages = list(history.messages.values())
    messages.sort()

    # set flag if any messages are exported
    channel.message_count = len(messages)

    # export to paginated files
    LAST_PAGE = len(messages) // MESSAGES_PER_PAGE
    for page_index, message_batch in enumerate(batched(messages, MESSAGES_PER_PAGE)):
        # pages navigation - available pages
        nav_start = page_index - NAVIGATION_RANGE // 2
        nav_end = page_index + NAVIGATION_RANGE // 2
        if nav_start < 0:
            nav_end += abs(nav_start)
            nav_start = 0
        if nav_end > LAST_PAGE:
            nav_start = max(nav_start - (nav_end - LAST_PAGE), 0)
            nav_end = LAST_PAGE

        # gather attachments
        attachment_view_models: dict[int, AttachmentViewModel] = {}
        for message in message_batch:
            message.content = discord_markdown_to_html(message.content)

            for attachment in message.attachments:
                if attachment.attachment_id in traffic_archive.attachment_files:
                    attachment_file_info = traffic_archive.attachment_files[attachment.attachment_id]
                    src = attachment_file_info.get_best_version()

                    # gather file info
                    is_image = False
                    is_audio = False
                    mime: str = attachment.reported_mime or "application/octet-stream"
                    kind = filetype.guess(src)
                    if kind is not None:
                        mime = kind.mime
                    if mime in IMAGE_MIME_TYPES:
                        is_image = True
                    if mime in AUDIO_MIME_TYPES:
                        is_audio = True
                    extension = mimetypes.guess_extension(mime)
                    if extension is None:
                        file_name_last_part = attachment.file_name.split(".")[-1]
                        if len(file_name_last_part) < FILENAME_EXTENSION_MAX_LENGTH:
                            extension = f".{file_name_last_part}"
                    if extension is None:
                        export_filename = f"attachment_{attachment.attachment_id}"
                    else:
                        export_filename = f"attachment_{attachment.attachment_id}{extension}"

                    dst = os.path.join(channel_directory, "attachments", export_filename)
                    shutil.copyfile(src, dst)

                    attachment_view_models[attachment.attachment_id] = AttachmentViewModel(export_filename,is_image,is_audio)
                else:
                    attachment_view_models[attachment.attachment_id] = AttachmentViewModel(None, False, False)

        if guild:
            channel_name = f"{guild.get_name()} - {channel.get_name()}"
        else:
            channel_name = f"{channel.get_name()}"

        message_file = os.path.join(channel_directory, f"page_{page_index + 1}.html")
        with open(message_file, "w") as f:
            page = page_template.render(
                page_index=page_index,
                channel_name=channel_name,
                nav_start=nav_start,
                nav_end=nav_end,
                messages=message_batch,
                attachment_data=attachment_view_models)
            f.write(page)

def write_server_index_file(guild: GuildMetadata, export_directory: str, traffic_archive: TrafficArchive):
    guild_index_file = os.path.join(export_dir,f"server_{guild.guild_id}.html")
    with open(guild_index_file, "w") as f:
        page = index_template.render(server=guild)
        f.write(page)

if __name__ == "__main__":
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser()

    parser.add_argument("-t","--traffic_archive",default="traffic_archive",help="The directory containing the traffic recordings that should be converted. Defaults to \"traffic_archive\"",metavar="<traffic_archive>")
    parser.add_argument("-o","--out_dir",default="web_exports",help="The directory to export the HTML files. Defaults to \"web_exports\"",metavar="<out_dir>")
    parser.add_argument("--limit-guilds", help="Limit the export to the following guild IDs", metavar="<guild id>", action="append", nargs="+")
    parser.add_argument("--metrics-file", help="Export a prometheus metrics file", metavar="<metrics file>")

    args = parser.parse_args()

    allowed_guilds = None
    if args.limit_guilds:
        allowed_guilds = set()
        for lst in args.limit_guilds:
            for guild_id in lst:
                allowed_guilds.add(int(guild_id))

    export_dir = args.out_dir
    traffic_dir = args.traffic_archive

    archive = TrafficArchive(traffic_dir)
    metrics = MetricsReport()

    start_time = time.time()

    logger.info("analyzing gateways...")
    parse_gateway_messages(archive.file_path("gateway_index"), archive, metrics)

    logger.info("parsing requests...")
    parse_request_index_file(archive.file_path("request_index"), archive, metrics)

    logger.info("exporting channels...")
    for channel in archive.get_channels():

        guild_id = channel.get_guild_id()
        if (allowed_guilds is not None) and ((guild_id is None) or (guild_id not in allowed_guilds)):
            continue

        history = parse_channel_history(channel.get_message_files())
        export_channel(channel, history, export_dir, archive)

        if channel.get_guild_id() is None or not archive.has_guild_information(channel.get_guild_id()):
            metrics.unknown_guild_count += 1

    logger.info(f"Found {metrics.unknown_guild_count} ({metrics.unknown_guild_count/archive.get_channel_count():.1f}%) channels without guild (e.g. PMs, or channels where guild information didn't get captured.)")

    logger.info("exporting server channel indices...")
    for guild in archive.get_guilds():
        if (allowed_guilds is not None) and (guild.guild_id not in allowed_guilds):
            continue
        if not guild.has_accurate_information():
            logger.warning(f"No accurate information for guild {guild.guild_id}")
        write_server_index_file(guild, export_dir, archive)

    end_time = time.time()
    metrics.runtime = end_time-start_time
    metrics.channel_count = archive.get_channel_count()
    metrics.guild_count = archive.get_guild_count()
    metrics.attachment_count = archive.get_attachment_count()

    metrics.maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss + resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    logger.info(f"done in {metrics.runtime:.1f}s, maxrss={metrics.maxrss}")

    if args.metrics_file:
        metrics.write(args.metrics_file)
