"""
Mitmproxy addon to record incoming Discord client traffic,
from both Discord's REST API and "Gateway" (Websocket) API.

Saves the following to traffic_archive/:
 - request_index
     Keeps track of metadata for each recorded HTTPS response.
     Each line is {timestamp} {method (GET or POST)} {url} {response hash} {filename}
     The filename points to a file in traffic_archive/requests which contains the response contents.
     These responses are pretty readable; images should even be saved with the right extensions.
     However, this directory will get big over time.
 - requests/
     Stores response contents. Contents tracked in request_index.
 - gateway_index
     Keeps track of metadata for each recorded Gateway connection.
     Each line is {timestamp} {url} {filename prefix}.
     The filename prefix points to a pair of files in traffic_archive/gateways, which end in _data and _timeline.
 - gateways/
     Stores compressed Gateway "message" contents and timing information, in pairs of files ending in _data and _timeline respectively.
     Each Gateway lasts a long time (like, until the client disconnects), and is tranport compressed via zlib.
     The _data file contains the entire Gateway "response"/"stream" (every "message" concatenated together)
     while the _timeline file keeps track of when each compressed "chunk"/"message" of the response was received.
     Each line of the _timeline file is {timestamp} {chunk length}.

Invoke like: mitmdump -s wumpus_in_the_middle.py --listen-port=8181 --allow-hosts '^(((.+\.)?discord\.com)|((.+\.)?discordapp\.com)|((.+\.)?discord\.net)|((.+\.)?discordapp\.net)|((.+\.)?discord\.gg))$'

todo:
    rename stuff for clarity?
        rename requests_index / requests/ to response_index / responses?
        rest_index and gateway_index?
        iron out terminology for Gateway "payloads" vs "messages". "chunks"?

"""

from mitmproxy import http, ctx
from urllib.parse import urlparse
import time
import os
import json
import zlib
from base64 import b64encode

# Sniff traffic to these domains and their subdomains.
# Sorta redundant when mitmproxy is invoked with --allow-hosts [big long discord domain regex],
# but not fully redundant since allow-hosts doesn't filter http requests, only https.
# Maybe instead of keeping track of domains here, we could just ignore all http,
# but redundancy is nice to ensure we don't archive non-Discord traffic.
DISCORD_DOMAINS = set(( 
    "discord.com",
    "discord.net",
    "discordapp.net",
    "discordapp.com",
    "discord.gg",
    # The rest of these probably aren't used. Including them anyway:
    "dis.gd",
    "discord.co",
    "discord.app",
    "discord.dev",
    "discord.new",
    "discord.gift",
    "discord.gifts",
    "discord.media",
    "discord.store",
    "discordstatus.com",
    "bigbeans.solutions",
    "watchanimeattheoffice.com"
))

def url_has_discord_root_domain(url):
    hostname = urlparse(url).hostname
    return (
        hostname is not None and
        any(hostname.endswith(domain) for domain in DISCORD_DOMAINS)
    )

def url_is_gateway(url):
    return url_has_discord_root_domain(url) and "gateway" in url

"""
Lossily turn a string into a reasonable/safe filename, possibly truncating it.
Uses a max filename length of 255.
"""
def safe_filename(filename):
    return "".join(c if c.isalnum() or c == "." else "_" for c in filename).rstrip()[:255]

def log_info(message):
    ctx.log.info("☎️  Wumpus In The Middle: " + message)

"""
Archives Gateway payloads for a single Gateway connection.
"""
class Gatekeeper:
    def __init__(self, data_path, timeline_path):
        self.data_file = open(data_path, "xb") # Every payload we get from the Gateway, concatenated.
        self.timeline_file = open(timeline_path, "x") # Tracks when we got the Gateway payloads. Each line: {timestamp} {number of bytes received at that time}

    """
    Save Gateway payload.
    """
    def save(self, message):
        payload_length = self.data_file.write(message.content)
        self.timeline_file.write("{} {}\n".format(message.timestamp, payload_length))
    
    def done(self):
        self.data_file.close()
        self.timeline_file.close()
        
class DiscordArchiver:
    def __init__(self):
        self.archive_path = "traffic_archive/"
        
        self.requests_path = os.path.join(self.archive_path, "requests/")
        self.gateways_path = os.path.join(self.archive_path, "gateways/")

        os.makedirs(self.requests_path, exist_ok=True)
        os.makedirs(self.gateways_path, exist_ok=True)

        # open the index files in line buffering mode: after a line is written, changes are flushed to the disk
        self.request_index_file = open(os.path.join(self.archive_path, "request_index"), "a+", buffering=1) # each line: {timestamp} {method} {url} {response hash} {filename}
        self.gateway_index_file = open(os.path.join(self.archive_path, "gateway_index"), "a+", buffering=1) # each line: {timestamp} {url} {gateway filename w/o _data or _timeline}
        self.request_index_file.seek(0)
        self.gateway_index_file.seek(0)
        
        self.recorded_response_hashes = set() # {(url, hash),...}
        for line in self.request_index_file:
            _timestamp, _method, url, response_hash, _filename = line.rstrip().split(maxsplit=4)
            self.recorded_response_hashes.add((url, response_hash))

        self.recorded_gateways_count = sum(1 for line in self.gateway_index_file)
        self.gatekeepers = {}

    def websocket_message(self, flow: http.HTTPFlow):
        # aggressively capture any potential discord traffic
        if not url_is_gateway(flow.request.pretty_url):
            log_info("websocket message is from non-gateway traffic: " + flow.request.pretty_url)
            return
        message = flow.websocket.messages[-1]
        if message.from_client:
            return
        if flow not in self.gatekeepers:
            gateway_filename_prefix = str(self.recorded_gateways_count)
            self.recorded_gateways_count += 1
            self.gatekeepers[flow] = Gatekeeper(
                os.path.join(self.gateways_path, gateway_filename_prefix + "_data"),
                os.path.join(self.gateways_path, gateway_filename_prefix + "_timeline"),
            )
            self.gateway_index_file.write(
                " ".join((str(flow.response.timestamp_start), flow.request.pretty_url, gateway_filename_prefix)) + "\n"
            )
            
        log_info("Archiving Gateway message.")
        self.gatekeepers[flow].save(message)
    
    def response(self, flow: http.HTTPFlow) -> None:
        url = flow.request.pretty_url
        if url_has_discord_root_domain(url) and flow.response.content:
            response_hash = str(hash(flow.response.content))
            
            if (url, response_hash) in self.recorded_response_hashes:
                log_info("Skipping hash-identical {}.".format(url))
                return
            
            filename = safe_filename(str(len(self.recorded_response_hashes)) + "_" + url[8:].rsplit("?", maxsplit=1)[0])
            log_info("Archiving {} to {}.".format(url, filename))
            
            with open(os.path.join(self.requests_path, filename), "wb") as file:
                file.write(flow.response.content)

            self.request_index_file.write(
                " ".join(
                    (
                        str(flow.response.timestamp_start),
                        flow.request.method,
                        url,
                        response_hash,
                        filename
                    )
                ) + "\n"
            )
            self.recorded_response_hashes.add((url, response_hash))

    """
    Select which requests should be "streamed".
    "Streaming" the request makes it sorta bypass the MitM,
    improving performance for large requests but preventing us from reading the contents.
    We only do this with file uploads, since they tend to break otherwise and often get re-downloaded anyway.
    """
    def requestheaders(self, flow):
        if not url_has_discord_root_domain(flow.request.pretty_url):
            return
        if flow.request.method == "POST" and flow.request.pretty_url.endswith("/attachments"):
            log_info("Streaming attachment upload.")
            flow.request.stream = True
    
    def done(self):
            log_info("Closing files.")
            self.request_index_file.close()
            self.gateway_index_file.close()
            for gatekeeper in self.gatekeepers.values():
                gatekeeper.done()

addons = [
    DiscordArchiver()
]
