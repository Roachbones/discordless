import logging
import os.path
import re
import json
import os.path
from typing import Any
import datetime
import gateway

logger = logging.getLogger(__name__)

"""
Extracts the time from a discord snowflake id
See https://discord.com/developers/docs/reference#snowflakes
"""


def snowflake_to_unix_timestamp(snowflake: int) -> float:
    return ((snowflake >> 22) + 1420070400000) / 1000


class ChannelMessageFile:
    def __init__(self, request_time: float, channel_id: int, file: str):
        self.channel_id: int = channel_id
        self.file: str = file
        self.request_time: float = request_time


class AttachmentFile:
    def __init__(self, channel_id: int, attachment_id: int):
        self.channel_id: int = channel_id
        self.attachment_id: int = attachment_id
        self.files: list[str] = []

    def get_best_version(self) -> str:
        # heuristic to get the attachment in its best quality: sort by file size
        if len(self.files) > 1:
            self.files.sort(key=lambda file: os.path.getsize(file))
        return self.files[0]


class Message:
    def __init__(self, observation_time: float, message_data: dict[str, Any]):
        self.message_id: int = int(message_data["id"])
        self.creation_time: float = snowflake_to_unix_timestamp(self.message_id)
        self.observation_time: float = observation_time
        self.author_id: int = int(message_data["author"]["id"])
        self.content: str = message_data["content"]

        # author names must be gathered from multiple places
        self.author_name: str = message_data["author"]["global_name"]
        if self.author_name is None:
            self.author_name = message_data["author"]["username"]

        self.attachments: list[Attachment] = [Attachment(data) for data in message_data["attachments"]]

    def get_message_datetime(self) -> datetime.datetime:
        return datetime.datetime.fromtimestamp(self.creation_time, datetime.timezone.utc)

    def __lt__(self, other):
        return self.creation_time < other.creation_time


class Attachment:
    def __init__(self, attachment_obj: dict[str, Any]):
        self.attachment_id: int = int(attachment_obj["id"])
        self.file_name: str = attachment_obj["filename"]
        self.reported_mime: str | None = attachment_obj.get("content_type", None)


class ChannelMessageHistory:
    def __init__(self):
        self.messages: dict[int, Message] = {}


class ChannelMetadata:
    def __init__(self, channel_id: int):
        self.name: str | None = None
        self.guild_id: int | None = None
        self.channel_id: int = channel_id
        self.message_count: int = 0
        self.message_files: list[ChannelMessageFile] = []

    def get_name(self) -> str:
        if self.name:
            return self.name
        return f"Channel {self.channel_id}"

    def get_guild_id(self):
        return self.guild_id

    def add_message_file(self, file: ChannelMessageFile):
        self.message_files.append(file)

    def get_message_files(self):
        return self.message_files


class GuildMetadata:
    def __init__(self, guild_id: int):
        self.guild_id: int = guild_id
        self.name: str | None = None
        self.channels: set[ChannelMetadata] = set()

    def get_name(self):
        if self.name:
            return self.name
        else:
            return f"Server_{self.guild_id}"

    def get_channels(self):
        return self.channels

    def has_accurate_information(self) -> bool:
        return self.name is not None

class TrafficArchive:
    def __init__(self, traffic_archive_directory: str):
        self.traffic_archive_directory: str = traffic_archive_directory
        self.attachment_files: dict[int, AttachmentFile] = {}
        self._channel_metadata: dict[int, ChannelMetadata] = {}
        self._guild_metadata: dict[int, GuildMetadata] = {}

    def get_channel_metadata(self, channel_id: int) -> ChannelMetadata:
        assert channel_id is not None

        if channel_id not in self._channel_metadata:
            self._channel_metadata[channel_id] = ChannelMetadata(channel_id)  # TODO
        return self._channel_metadata[channel_id]

    def get_channels(self):
        return self._channel_metadata.values()

    def get_channel_count(self) -> int:
        return len(self._channel_metadata)

    def get_guild_metadata(self, guild_id: int) -> GuildMetadata:
        assert guild_id is not None

        if guild_id not in self._guild_metadata:
            self._guild_metadata[guild_id] = GuildMetadata(guild_id)
        return self._guild_metadata[guild_id]

    def get_guilds(self):
        return self._guild_metadata.values()

    def has_guild_information(self, guild_id: int) -> bool:
        if guild_id not in self._guild_metadata:
            return False
        return self.get_guild_metadata(guild_id).has_accurate_information()

    def file_path(self, *relative_parts: str):
        return os.path.join(self.traffic_archive_directory, *relative_parts)


def parse_guild_profile_file(guild_profile_request_file: str):
    with open(guild_profile_request_file, "r") as f:
        content = json.load(f)
        return content["name"]


def parse_request_index_file(file: str, traffic_archive: TrafficArchive):
    with open(file, "r") as request_index:
        for index_entry in request_index:
            seen_timestamp, method, url, response_hash, filename = index_entry.split()

            # message files
            match = re.match(r"https://discord.com/api/v9/channels/(\d*)/messages(\?|$)", url)
            if match:
                channel_id = int(match.group(1))

                channel_metadata = traffic_archive.get_channel_metadata(channel_id)
                channel_metadata.add_message_file(ChannelMessageFile(float(seen_timestamp), channel_id, traffic_archive.file_path("requests", filename)))
                continue

            # guild info
            match = re.match(r"https://discord.com/api/v9/guilds/(\d*)/profile(\?|$)", url)
            if match:
                guild_id = int(match.group(1))
                guild_name = parse_guild_profile_file(traffic_archive.file_path("requests", filename))

                guild = traffic_archive.get_guild_metadata(guild_id)
                guild.name = guild_name  # TODO: determine if this is actually a newer name

            # attachments
            match = re.match(r"https://(?:media|cdn).discordapp.(?:com|net)/attachments/(\d+)/(\d+)/.*", url)
            if match:
                channel_id = int(match.group(1))
                attachment_id = int(match.group(2))
                # we just assume attachment ids are unique across channels
                if attachment_id in traffic_archive.attachment_files:
                    # but to be sure, let's check for collisions
                    if traffic_archive.attachment_files[attachment_id].channel_id != channel_id:
                        logger.warning(f"duplicate attachment id detected for id={attachment_id} channel={channel_id}")
                        continue
                # save attachment. there might be multiple versions
                if attachment_id not in traffic_archive.attachment_files:
                    traffic_archive.attachment_files[attachment_id] = AttachmentFile(channel_id, attachment_id)
                traffic_archive.attachment_files[attachment_id].files.append(traffic_archive.file_path("requests", filename))


def parse_channel_message_file(channel_file: ChannelMessageFile, history: ChannelMessageHistory):
    with open(channel_file.file, "r") as message_file:
        data = json.load(message_file)

        # discordless unfortunately doesn't record http status codes. We have to detect errors by the content
        if isinstance(data, dict) and "code" in data and "message" in data:
            logger.error(f"skipping channel message file {channel_file.file} due to discord-side errors")
            return

        # discord fails to encapsulate messages in an array if there is just one message
        if isinstance(data, dict):
            data = [data]

        for message_observation in data:
            message = Message(channel_file.request_time, message_observation)

            if message.message_id in history.messages:
                # determine which message is newer
                other_message = history.messages[message.message_id]
                if message.observation_time > other_message.observation_time:  # these are unix timestamps
                    history.messages[message.message_id] = message
            else:
                history.messages[message.message_id] = message


def parse_channel_history(channel_files: list[ChannelMessageFile]) -> ChannelMessageHistory:
    history = ChannelMessageHistory()

    for channel_file in channel_files:
        parse_channel_message_file(channel_file, history)

    return history


def parse_gateway_recording(gateway_timeline: str, gateway_data: str, url: str, traffic_archive: TrafficArchive):
    for message in gateway.parse_gateway_recording(gateway_timeline, gateway_data, url):
        message_type = message["t"]
        data = message["d"]

        # server info like channels
        if message_type == "READY":
            for guild in data["guilds"]:
                guild_id = int(guild["id"])
                guild_meta = traffic_archive.get_guild_metadata(guild_id)

                if "channels" in guild:
                    for channel in guild["channels"]:
                        channel_id = int(channel["id"])

                        channel_meta = traffic_archive.get_channel_metadata(channel_id)
                        channel_meta.name = channel["name"]
                        channel_meta.guild_id = guild_id

                        guild_meta.channels.add(channel_meta)

                if "threads" in guild:
                    for thread in guild["threads"]:
                        channel_meta = traffic_archive.get_channel_metadata(thread["id"])
                        channel_meta.name = f"thread: {thread["name"]}"
                        channel_meta.guild_id = guild_id
                        guild_meta.channels.add(channel_meta)


def parse_gateway_messages(gateway_index: str, traffic_archive: TrafficArchive):
    with open(gateway_index, "r") as f:
        for index_entry in f:
            timestamp, url, name = index_entry.split()

            timeline_file = traffic_archive.file_path("gateways", f"{name}_timeline")
            data_file = traffic_archive.file_path("gateways", f"{name}_data")

            parse_gateway_recording(timeline_file, data_file, url, traffic_archive)
