import time
from typing import Iterable
import os.path
import os
from traffic_parser import *
from itertools import batched

MESSAGES_PER_PAGE = 10


def export_messages_page(messages: Iterable[Message], channel_directory: str, page_index: int):
    message_file = os.path.join(channel_directory,f"page_{page_index}.txt")
    with open(message_file, "w") as f:
        for message in messages:
            f.write(f"--- {message.message_data["author"]["username"]} ---\n{message.message_data["content"]}\n\n")


def export_channel(channel_id, history: ChannelMessageHistory, export_directory: str):
    channel_directory = os.path.join(export_directory, f"channel_{channel_id}")
    os.makedirs(channel_directory)

    messages = list(history.messages.values())
    messages.sort()

    # export to paginated files
    for page_index, message_batch in enumerate(batched(messages, MESSAGES_PER_PAGE)):
        export_messages_page(message_batch, channel_directory, page_index + 1)  # start page indexes at 1


if __name__ == "__main__":
    export_path = os.path.join("web_exports",f"export_{int(time.time())}")

    archive = TrafficArchive("../discordless/traffic_archive/")
    parse_request_index_file(archive.file_path("request_index"), archive)

    for channel_id in archive.channel_message_files.keys():
        history = parse_channel_history(archive.channel_message_files[channel_id])
        export_channel(channel_id, history, export_path)
