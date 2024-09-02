"""
This is neglected in favor of dcejson_exporter.py, but it should still mostly work.

todo:
    consistent naming mode toggle
    js2py discord markdown
    render embeds
    code is duplicated between here and dcejson_exporter. refactor that.
"""

import os
import re
import json
import time
import datetime
import argparse
from dateutil import parser
from shutil import copyfile
from parse_gateway import parse_gateway
import jinja2

arg_parser = argparse.ArgumentParser(prog='python3 html_exporter.py')
arg_parser.add_argument("-d","--dry",action='store_true', help="perform a dry run without actually writing any files")
arg_parser.add_argument("-t","--traffic-archive", default="traffic_archive/", help="The traffic archive directory used for this conversion. Per default 'traffic_archive/'", metavar="<dir>")
arg_parser.add_argument("-o","--output", default="html_exports/", help="The directory to export the output into. Per default 'html_exports/'", metavar="<dir>")
options = arg_parser.parse_args()

DRY_RUN = options.dry
archive_path = options.traffic_archive
requests_path = os.path.join(archive_path, "requests/")
gateways_path = os.path.join(archive_path, "gateways/")
chatlogs_path = os.path.join(options.output, "export_" + str(int(time.time())))

MESSAGE_TYPE_NAMES = {
    0: "DEFAULT",
    1: "RECIPIENT_ADD",
    2: "RECIPIENT_REMOVE",
    3: "CALL",
    4: "CHANNEL_NAME_CHANGE",
    5: "CHANNEL_ICON_CHANGE",
    6: "CHANNEL_PINNED_MESSAGE",
    7: "GUILD_MEMBER_JOIN",
    8: "USER_PREMIUM_GUILD_SUBSCRIPTION",
    9: "USER_PREMIUM_GUILD_SUBSCRIPTION_TIER_1",
    10: "USER_PREMIUM_GUILD_SUBSCRIPTION_TIER_2",
    11: "USER_PREMIUM_GUILD_SUBSCRIPTION_TIER_3",
    12: "CHANNEL_FOLLOW_ADD",
    14: "GUILD_DISCOVERY_DISQUALIFIED",
    15: "GUILD_DISCOVERY_REQUALIFIED",
    16: "GUILD_DISCOVERY_GRACE_PERIOD_INITIAL_WARNING",
    17: "GUILD_DISCOVERY_GRACE_PERIOD_FINAL_WARNING",
    18: "THREAD_CREATED",
    19: "REPLY",
    20: "CHAT_INPUT_COMMAND",
    21: "THREAD_STARTER_MESSAGE",
    22: "GUILD_INVITE_REMINDER",
    23: "CONTEXT_MENU_COMMAND"
}

def attachment_url_to_id(url):
    if url.startswith("https://images-ext"): # unused for now
        match = re.match(
            r"https://images-ext-\d.discordapp.net/external/([^\/]+)/(.*)",
            url
        )
        return match.group(1)
    # else, media or cdn url
    match = re.match(
        r"https://(media|cdn).discordapp.(com|net)/attachments/(\d+)/(\d+)/([^\?]*)(.*)",
        url
    )
    
    return match.group(4) + "-" + match.group(5)

def get_dmo_time(dmo):
    return parser.parse(dmo["timestamp"])

channel_messages = {} # channel_id : {message_id: MessageProvenance}

all_attachments = {} # url : filepath
all_authors = {} # author_id : author info, from message["author"]
all_avatars = {} # author_id : avatar bytes

# Just using this since it's the only channel metadata we care about.
# Replace this with Channel stuff once we care more about channels.
channel_titles = {} # message_id : title (guild name concatenated with channel name)

# Classes for guild and channel.
# Not used yet, but here to build upon later.
class Guild:
    listing = {}
    def __init__(self, guild_id, name):
        assert guild_id not in listing
        self.guild_id = guild_id
        self.name = name
        listing[guild_id] = self
    #def get_substantial_channels(self): # let's only get the ones we have data for
    #    return [channel if channel.guild_id=self.guild_id and for channel_id, channel in Channels.listing.items()]
class Channel:
    listing = {}
    def __init__(self, channel_id, name, guild_id=None):
        assert channel_id not in listing
        self.id = channel_id
        self.name = name
        self.guild_id = guild_id
        listing[channel_id] = self
    def update_info(name=None, guild_id=None):
        self.name = name or self.name
        self.guild_id = guild_id or guild_id
    def get_display_name(self): # for tab titles, that sort of thing
        if guild_id in Guild.listing:
            guild_name = Guild.listing[guild_id].name
            return guild_name + ": " + self.name
        return self.name


"""
Each MessageProvenance has a list of MessageObservations for each time the message was observed.
This lets us keep track of message editing and deletion.
"""
class MessageProvenance: # Recorded history of a particular message. Sequence of MessageObservations.
    def __init__(self, observation):
        self.observations = [observation]
        self.message_id = observation.message_id
        self.creation_timestamp = datetime.datetime.fromtimestamp(
            # see discord.com/developers/docs/reference#convert-snowflake-to-datetime
            ((int(self.message_id) >> 22) + 1420070400000) / 1000,
            tz=datetime.timezone.utc
        )
    def add_observation(self, observation):
        assert observation.message_id == self.message_id
        # If we now have two deletion observations, just keep the earlier one
        if observation.dmo is None and self.observations[-1].dmo is None:
            self.observations[-1] = min(observation, observations[-1])
        self.observations.append(observation)
        self.observations.sort()
    """ Returns (author id, author username) if we've observed it, otherwise (None, None). """
    def author_id_and_username(self):
        for observation in self.observations:
            if observation.dmo:
                return int(observation.dmo["author"]["id"]), observation.dmo["author"]["username"]
        return (None, None)
    def __iter__(self):
        return self.observations.__iter__()
    def __lt__(self, other_provenance): # for sorting messages
        return self.creation_timestamp < other_provenance.creation_timestamp

"""
A single "version" of a message and how we saw it (or its absence).
Contains a DMO, or None if we didn't see the message.
seen_timestamp: when we observed the message
message_id_or_dict: the message id or a dict representing Discord's Message object.
saw_update: whether we observed the message as it was updated.
If observation.message_dict is None and saw_update is True, it means we witnessed the message get deleted
at seen_timestamp, in a MESSAGE_DELETE event.
If message_dict is None and saw_update is False, it means that we saw that the message was gone,
but we didn't actually watch it get deleted, so it happened *sometime* before seen_timestamp.
"""
class MessageObservation:
    def __init__(self, seen_timestamp, dmo_or_message_id, mechanism):
        self.seen_timestamp = seen_timestamp
        if isinstance(dmo_or_message_id, int):
            self.dmo = None
            self.message_id = dmo_or_message_id
        else: # it's a DMO
            self.dmo = dmo_or_message_id
            self.message_id = int(self.dmo["id"])
        self.mechanism = mechanism
    """
    Whether this observation represents the same message edition as another.
    """
    def is_equivalent_to(self, other_observation):
        if self.message_id != other_observation.message_id:
            return False
        if self.dmo is None and other_observation.dmo is None:
            return True
        if (self.dmo and other_observation.dmo) is None:
            return False
        if "edited_timestamp" in self.dmo and "edited_timestamp" in other_observation.dmo:
            return self.dmo["edited_timestamp"] == other_observation.dmo["edited_timestamp"]
        for field in ("content", "embeds", "flags"): # Everything that can be edited..?
            if field in self.dmo and field in other_observation.dmo and str(self.dmo[field]) != str(other_observation.dmo[field]):
                return False
        return True # I guess?
    def __lt__(self, other_observation):
        return self.seen_timestamp < other_observation.seen_timestamp

"""
Record a MessageObservation (and an associated MessageProvenance if there isn't one for this message)
from a DMO ("Discord's 'Message' object")
or just the ID I guess? Need to document further
"""
def observe_dmo(seen_timestamp, dmo, saw_update, channel_id=None, message_id=None):
    if dmo is not None:
        if "code" in dmo:
            print("skipping dmo with code",dmo["code"])
            #pprint(dmo)
            # todo: support "Cannot send messages to this user", code 50007
            return
        channel_id = int(dmo["channel_id"])
        message_id = int(dmo["id"])
    
    observation = MessageObservation(seen_timestamp, dmo or message_id, saw_update)
    if channel_id not in channel_messages:
        channel_messages[channel_id] = {}
    if message_id not in channel_messages[channel_id]:
        channel_messages[channel_id][message_id] = MessageProvenance(observation)
    else:
        channel_messages[channel_id][message_id].add_observation(observation)


with open(os.path.join(archive_path, "request_index")) as file:
    for line in file:
        seen_timestamp, method, url, response_hash, filename = line.split()
        seen_timestamp = datetime.datetime.utcfromtimestamp(float(seen_timestamp))
        path = os.path.join(requests_path, filename)
        
        # messages
        match = re.match(r"https://discord.com/api/v9/channels/(\d*)/messages(\?|$)", url)
        if match:
            with open(path) as request_file:
                try:
                    dmos = json.load(request_file)
                except:
                    print("ignoring invalid json")
            if isinstance(dmos, dict): # if there's only one then they erroenously fail to encapsulate it in an array??
                dmos = [dmos]
            for dmo in dmos:
                observe_dmo(seen_timestamp, dmo, "REST")

        # attachments
        elif (
            url.startswith("https://cdn.discordapp.com/attachments/") or
            url.startswith("https://media.discordapp.net/attachments/")
            #url.startswith("https://images-ext-1.discordapp.net/external/") or # todo
            #url.startswith("https://images-ext-1.discordapp.net/external/") 
        ):
            attachment_id = attachment_url_to_id(url)
            # if we haven't yet collected this attachment, or this is a bigger version of a collected attachment, then collect it
            if attachment_id not in all_attachments or os.path.getsize(all_attachments[attachment_id]) < os.path.getsize(path):
                all_attachments[attachment_id] = path

with open(os.path.join(archive_path, "gateway_index")) as file:
    for line in file:
        seen_timestamp, url, gateway_path_base = line.rstrip().split(" ", maxsplit=2)
        seen_timestamp = datetime.datetime.utcfromtimestamp(float(seen_timestamp))
        for payload in parse_gateway(os.path.join(archive_path, "gateways", gateway_path_base), url):
            # Discord calls payload["d"] both "inner payload" and "event data", which are both bad names. Let's call it "event".
            event_name, event = payload["t"], payload["d"] 
            if event_name in ("MESSAGE_CREATE", "MESSAGE_UPDATE"): # MESSAGE_UPDATE only has ambiguously partial dmo. might cause issues                
                observe_dmo(seen_timestamp, event, event_name)
            elif event_name == "MESSAGE_DELETE":
                observe_dmo(seen_timestamp, None, event_name, int(event["channel_id"]), int(event["id"]))
            elif event_name=="READY":
                pass

print("Collected {} messages and {} attachments from {} channels.".format(
    sum(len(messages) for messages in channel_messages.values()),
    len(all_attachments),
    len(channel_messages)
))

unique_id_counter = 0
"""
Sanitizes a file or directory name

This function shall do the following to the input:
- alphanumeric characters
- underscores and dots
- no two or more dots in a series
- invalid characters shall be replaced with a underscore
- too long filenames shall be shortened
- if a filename is shortened, a unique suffix is added to ensure uniqueness
- if a filename is too short, add a unique suffix
"""
def reasonable_filename(filename: str) -> str:
    global unique_id_counter

    ALLOWED_CHARS = ["_", "."]
    MAX_LEN = 80
    MIN_LEN = 3

    last_c = ""
    valid = []
    for c in filename:
        if not c.isalnum() and c not in ALLOWED_CHARS:
            c = "_"

        if last_c == "." and c == ".":
            continue  # we can skip updating last_c since last_c already equals c

        valid.append(c)
        last_c = c

    filename = "".join(valid)

    # ensure the length is okay. Otherwise, shorten it if required and add a unique suffix
    if not (MIN_LEN < len(filename) < MAX_LEN):
        unique_suffix = hex(unique_id_counter)[2:]
        unique_id_counter += 1
        filename = filename[:MAX_LEN-len(unique_suffix)]+unique_suffix

    return filename


if not DRY_RUN:
    with open("html_template/style.css") as file:
        chatlog_style = file.read() # for copying into every archive

    for channel_id, message_id_to_provenance in channel_messages.items():
        provenances = list(message_id_to_provenance.values())
        provenances.sort()
        
        # Go through the whole message log just to get the authors.
        # Todo: Should try to get this from channel info api requests, like dcejson_exporter.
        # This could be a fallback if that's not available.
        authors = {}
        for provenance in provenances:
            author_id, author_username = provenance.author_id_and_username()
            if author_id:
                authors[author_id] = author_username
        conversation_name = "-".join(sorted(authors.values())) # example: chase-vivian
        
        print("Sorted {} messages in the {} channel. (channel id {})".format(
            len(provenances),
            channel_id,#conversation_name,
            channel_id
        ))
        
        jenv = jinja2.Environment(loader=jinja2.FileSystemLoader('html_template'), autoescape=True)
        template = jenv.get_template("index.html")

        chatlog_path = os.path.join(chatlogs_path, reasonable_filename(str(channel_id) + "-" + conversation_name))
        os.makedirs(chatlog_path)
        chatlog_attachments_path = os.path.join(chatlog_path, "attachments")
        os.mkdir(chatlog_attachments_path)
        
        # prepare chatlog
        chatlog_messages = []
        chatlog_attachments = set()
        prev_author_id = None
        prev_creation_timestamp = None
        for provenance in provenances:
            chatlog_message = {
                "id": provenance.message_id,
                "timestamp": str(provenance.creation_timestamp),
                "readable_timestamp": provenance.creation_timestamp.strftime("%m/%d/%y %H:%M:%S"),
                # Default values, populated later if applicable
                "editions": [], # editions of the single message tracked by this provenance
                "author_id": None,
                "author_name": None,
                "date_divider": None
            }
            chatlog_messages.append(chatlog_message)
            
            # Add date-labelling horizontal rule if the message is on a different day than the previous one, or it's the first message
            if prev_author_id is None or provenance.creation_timestamp.date() != prev_creation_timestamp.date():
                chatlog_message["date_divider"] = provenance.creation_timestamp.strftime("%B %e, %Y")
            
            prev_observation = None
            edited_timestamps_observed = set()
            edition = None
            for observation in provenance:
                dmo = observation.dmo
                # todo: simplify edit tracking
                if dmo and ("edited_timestamp" in dmo) and ((None if dmo["edited_timestamp"] is None else parser.parse(dmo["edited_timestamp"])) in edited_timestamps_observed):
                    continue # We've already processed this version of the message
                if observation.mechanism == "MESSAGE_UPDATE": # todo: add support for embed and flags, and their editing
                    if "content" in observation.dmo and edition is not None: # if this is a content update and this is not the first edition we've seen
                        if edition["content"] == dmo["content"]: # weird redundant edit
                            continue
                        edition = edition.copy() # copy the last edition and make a new one based on it
                        edition["content"] = dmo["content"]
                        edition["edited_timestamp"] = observation.seen_timestamp
                        chatlog_message["editions"].append(edition)
                        continue
                    else: # This MESSAGE_UPDATE is the first we've heard of this message.
                        chatlog_message["partial_data"] = True # unused
                        # just keep using the dmo from this observation as the source of truth for the original message
                
                edition = { # An edition of this message, based on the observation, to feed to the Jinja template.
                    "deleted": dmo is None,
                    # default values, populated later if applicable
                    "images": [],
                    "attachment_links": [],
                    "date_divider": None,
                    "system_text": None,
                    "referenced_message": None,
                    "edited_timestamp": None
                }
                chatlog_message["editions"].append(edition)
                
                if dmo is None: # If this observation is of a deleted message
                    break # stop checking this message's observations

                if "author" in dmo:
                    chatlog_message["author_id"] = int(dmo["author"]["id"])
                    chatlog_message["author_name"] = dmo["author"]["username"] # todo: improve author name determination

                if "content" in dmo:
                    edition["content"] = dmo["content"]

                if "edited_timestamp" in dmo:
                    if dmo["edited_timestamp"] is not None:
                        edition["edited_timestamp"] = parser.parse(dmo["edited_timestamp"])
                    edited_timestamps_observed.add(edition["edited_timestamp"])
                else: # MESSAGE_UPDATE doesn't provide an edit timestamp, so just use its observation time.
                    edition["edited_timestamp"] = observation.seen_timestamp
                
                # Add reactions
                chatlog_message["reactions"] = []
                if "reactions" in dmo:
                    for reaction in dmo["reactions"]:
                        chatlog_message["reactions"].append({
                            "emoji": reaction["emoji"]["name"],
                            "count": reaction["count"],
                            "me": reaction["me"]
                        })

                # Add attachments: embedded images, local links, and external links
                if "attachments" in dmo:
                    for attachment in dmo["attachments"]:
                        attachment_id = attachment_url_to_id(attachment["proxy_url"])
                        if attachment_id in all_attachments:
                            if attachment_id not in chatlog_attachments:
                                chatlog_attachment_path = os.path.join(chatlog_attachments_path, reasonable_filename(attachment_id))
                                chatlog_attachment_rel_path = os.path.relpath(chatlog_attachment_path, chatlog_path) # used for img src in chatlog.html
                                copyfile(all_attachments[attachment_id], chatlog_attachment_path) # Make copy of the attachment for the chatlog
                                chatlog_attachments.add(attachment_id)
                            # todo: support videos
                            if any(attachment_id.lower().endswith(ext) for ext in (".png",".jpg",".jpeg",".gif",".bmp",".webp")):
                                edition["images"].append(chatlog_attachment_rel_path)
                            else:
                                edition["attachment_links"].append(chatlog_attachment_rel_path)
                        else: # We don't have the attachment archived, so just give a link to it.
                            #print(attachment["proxy_url"], attachment_id, " not in all_attachments")
                            edition["attachment_links"].append(attachment["proxy_url"])

                # Show *something* for embeds, at least. Needs workshopped.
                if "embeds" in dmo and dmo["embeds"]:
                    edition["embeds_code"] = str(dmo["embeds"])

                if "type" in dmo:
                    # Do stuff with weird "messages", like calls and replies.
                    if dmo["type"] == 3: # call
                        edition["system_text"] = "started a call"
                        if dmo["call"]["ended_timestamp"] != None:
                            edition["system_text"] += " that lasted " + str(parser.parse(dmo["call"]["ended_timestamp"]) - provenance.creation_timestamp).split(".")[0]
                        edition["system_text"] += "."
                    elif dmo["type"] == 7: # server join
                        edition["system_text"] = "joined the server."
                        #pprint(dmo)
                    elif dmo["type"] == 19: # reply
                        edition["system_text"] = "replied"
                        if "referenced_message" in dmo and dmo["referenced_message"] is not None: # todo: support message_reference + cross-channel links or whatever
                            edition["referenced_message"] = {
                                "content": dmo["referenced_message"]["content"],
                                "author_id": dmo["referenced_message"]["author"]["id"],
                                "author_name": dmo["referenced_message"]["author"]["username"]
                            }
                            if dmo["referenced_message"]["id"] in message_id_to_provenance:
                                edition["referenced_message"]["link"] = "#message-" + str(dmo["referenced_message"]["id"]) # needs to be updated when implementing pagination
                    elif dmo["type"] == 6: # pinning a message
                        edition["system_text"] = "pinned a message." # todo: add referenced message
                    elif dmo["type"] != 0: # if it's any other weird message type
                        edition["system_text"] = MESSAGE_TYPE_NAMES.get(dmo["type"]) or str(dmo["type"])

                prev_observation = observation
             
            chatlog_message["needs_header"] = ( # Enable username/date header for this message iff
                prev_creation_timestamp is None # this is the first message in the chatlog,
                or chatlog_message["author_id"] != prev_author_id # or the author is different from the last message's,
                or provenance.creation_timestamp - prev_creation_timestamp > datetime.timedelta(minutes=7) # or 7 mins have passed since the previous message,
                or chatlog_message["date_divider"] # or the message requires a dated separator.
            )
            
            prev_creation_timestamp = provenance.creation_timestamp
            prev_author_id = chatlog_message["author_id"]

        print("Prepared chatlog.")
        
        with open(os.path.join(chatlog_path, "chatlog.html"), "w") as file:
            file.write(template.render(
                chatlog=chatlog_messages,
                conversation_name=conversation_name
            ))

        print("Rendered chatlog.")

        with open(os.path.join(chatlog_path, "style.css"), "w") as file:
            file.write(chatlog_style)
        
        print("Chatlog saved to {}.\n".format(chatlog_path))

print("All done. UwU")










