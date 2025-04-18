import time
from typing import Iterable
import os.path
import os
from traffic_parser import *
from itertools import batched
import jinja2

MESSAGES_PER_PAGE = 500
NAVIGATION_RANGE = 10

jinja_environment = jinja2.Environment(loader=jinja2.FileSystemLoader("templates/"))
page_template = jinja_environment.get_template("page.html")

def export_channel(channel_id, history: ChannelMessageHistory, export_directory: str):
    channel_directory = os.path.join(export_directory, f"channel_{channel_id}")
    os.makedirs(channel_directory, exist_ok=True)

    messages = list(history.messages.values())
    messages.sort()

    # export to paginated files
    LAST_PAGE = len(messages) // MESSAGES_PER_PAGE
    for page_index, message_batch in enumerate(batched(messages, MESSAGES_PER_PAGE)):
        # pages navigation - available pages
        nav_start = page_index-NAVIGATION_RANGE//2
        nav_end = page_index+NAVIGATION_RANGE//2
        if nav_start < 0:
            nav_end += abs(nav_start)
            nav_start = 0
        if nav_end > LAST_PAGE:
            nav_start = max(nav_start-(nav_end-LAST_PAGE), 0)
            nav_end = LAST_PAGE

        message_file = os.path.join(channel_directory, f"page_{page_index+1}.html")
        with open(message_file, "w") as f:
            page = page_template.render(
                page_index=page_index,
                channel_name=f"Channel {channel_id}",
                nav_start=nav_start,
                nav_end=nav_end,
                messages=message_batch)
            f.write(page)


if __name__ == "__main__":
    #export_path = os.path.join("web_exports", f"export_{int(time.time())}")
    export_path = os.path.join("web_exports", f"export_latest")

    archive = TrafficArchive("../discordless/traffic_archive/")
    parse_request_index_file(archive.file_path("request_index"), archive)

    for channel_id in archive.channel_message_files.keys():
        history = parse_channel_history(archive.channel_message_files[channel_id])
        export_channel(channel_id, history, export_path)

