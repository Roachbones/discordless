"""
Read the traffic archive outputted by Wumpus In The Middle and create
a DiscordChatExporter-style JSON export, compatible with DiscordChatExporter-frontend.

todo: rename "timestamp" variables to be more clear. We use several kinds of "timestamps" here.
todo: DCEF errors out if an asset has a None url; see AssetProcessor.process.
  HOTLINK_MISSING_ASSETS=True prevents this, but ideally,
  we should be able to either use a fake dummy path or patch DCEF to support null attachment URLs.
todo: replicate DCE's bespoke embed-merging logic to accommodate https://github.com/Tyrrrz/DiscordChatExporter/issues/695
todo: calculate name colors based on roles
todo: Support emojos ("Custom Emojis"). Should be straightforward.
todo: Support reactions
todo: Support stickers

In this code, "dao" means Discord API Object.
For example, "user dao" means a User object served by the Discord API,
defined (loosely) by https://discord.com/developers/docs/resources/user#user-object
"dmo" means Discord Message Object, aka a "message dao".
todo: make these names more consistent.
"""

import os
import re
import json
import time
import datetime
from dateutil import parser
from shutil import copyfile
import urllib.parse
from parse_gateway import parse_gateway
from pprint import pprint
from tqdm import tqdm

# configuration
DRY_RUN = False
CONSISTENT_NAMING_MODE = False
INCLUDE_DELETED_MESSAGES = False # todo
HOTLINK_MISSING_ASSETS = True
MAX_FILENAME_LENGTH = 60
CHANNELS_TO_EXPORT_IDS = None

ARCHIVE_PATH = "traffic_archive/"
REQUESTS_PATH = os.path.join(ARCHIVE_PATH, "requests/")
GATEWAYS_PATH = os.path.join(ARCHIVE_PATH, "gateways/")

def get_dmo_time(dmo):
    return parser.parse(dmo["timestamp"])

channel_messages = {} # channel_id : {message_id: MessageProvenance}

"""
Tracks attachments, and also embed images since they act similarly.
"""
attachmentoids = {}
def observe_attachmentoid(url, downloaded_path):
    parsed_qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    if "width" in parsed_qs:
        if "height" in parsed_qs:
            size = int(parsed_qs["width"][0]) * int(parsed_qs["height"][0])
        else: # Should only ever happen via manual url tampering
            size = width # Just guess. Sizes incomparable in this case.
    else:
        size = None
    observe_biggest(size, downloaded_path, shave_attachmentoid_url(url), attachmentoids)
"""
Take an attachment URL ("proxy URL", really), and remove the querystring and such.
This should give a sort of identifier I call a "bald URL".
Importantly, this should give the same output from any URL used to fetch the attachment
or the proxy_url specified in the Discord API Attachment object.
Used as an identifier to link messages with attachments to the right archived assets.
"""
def shave_attachmentoid_url(url):
    parsed_url = urllib.parse.urlparse(url)
    return parsed_url.netloc + parsed_url.path
def find_attachmentoid_downloaded_path_by_url(url):
    bald_url = shave_attachmentoid_url(url)
    if bald_url in attachmentoids:
        return attachmentoids[bald_url][1]

"""
Non-attachment image assets (avatar, server icon, etc.) downloaded over Discord's CDN.
See https://discord.com/developers/docs/reference#image-formatting-image-formats
"""
cdnimages = {}
def observe_cdnimage(url, downloaded_path):
    parsed_url = urllib.parse.urlparse(url)
    assert parsed_url.path.count(".") == 1
    cdnimage_id, _ext = parsed_url.path[1:].split(".") # todo: could add extension preference
    parsed_qs = urllib.parse.parse_qs(parsed_url.query)
    if "size" in parsed_qs:
        size = int(parsed_qs["size"][0])
    else:
        size = None # full size
    observe_biggest(size, downloaded_path, cdnimage_id, cdnimages)

"""
Returns downloaded path of a user's avatar, given its id and avatar hash.
"""
def find_avatar(user_id, avatar_hash): # maybe remove
    if avatar_hash is None:
        return
    cdnimage_id = "avatars/" + str(user_id) + "/" + avatar_hash
    if cdnimage_id in cdnimages:
        return cdnimages[cdnimage_id][1]
"""
Returns downloaded path of a guild's icon, given its id and icon hash.
"""
def find_guildicon(guild_id, icon_hash):
    if icon_hash is None:
        return
    cdnimage_id = "icons/" + str(guild_id) + "/" + icon_hash
    if cdnimage_id in cdnimages:
        return cdnimages[cdnimage_id][1]
"""
Returns downloaded path of a channel's icon, given its id and icon hash.
This endpoint undocumented in the Discord API,
"""
def find_channelicon(channel_id, icon_hash):
    if icon_hash is None:
        return
    cdnimage_id = "channel-icons/" + str(channel_id) + "/" + icon_hash
    if cdnimage_id in cdnimages:
        return cdnimages[cdnimage_id][1]

# Keeps track of the last known observations ("impressions", I guess) of guilds and channels,
#  since we want to use the most recent information for them (guild icons, channel names, etc.)
#  and currently have no motivation to show the user how they evolve over time.
guild_impressions = {} # guild_id : (seen_timestamp, guild_dao)
channel_impressions = {} # channel_id : (seen_timestamp, channel_dao)
channel_id_to_guild_id = {}

def observe_guild(seen_timestamp, guild_dao):
    # Only observe data that we care about.
    observation = {
        "id": guild_dao["id"],
        "properties": {
            "name": guild_dao["properties"]["name"],
            "icon": guild_dao["properties"]["icon"] # todo: docs say sometimes this is "icon_hash" rather than "icon"?
        },
        "roles": [ # Only care about role id and role color. Not used yet, though.
            {k:v for k,v in role_dao.items() if k in ("id","color")} for role_dao in guild_dao["roles"]
        ]
    }
    observe_newest(seen_timestamp, observation, int(guild_dao["id"]), guild_impressions)

def observe_channel(seen_timestamp, channel_dao, guild_id):
    observation = {k:v for k,v in channel_dao.items() if k in ("type","name","id","topic","parent_id","recipient_ids")}
    observe_newest(seen_timestamp, observation, int(channel_dao["id"]), channel_impressions)
    channel_id_to_guild_id[int(channel_dao["id"])] = guild_id

"""
Observe something that changes over time, but we only care about the latest version.
So, discard any older versions if new versions are available.
Used for guilds and channels and such, since we want to show the most up-to-date names/icons for them.
"""
def observe_newest(seen_timestamp, new_observation, observee_id, timestamped_observations):
    observe_superlative(seen_timestamp, new_observation, observee_id, timestamped_observations, lambda old, new: old < new)

"""
Observe something that has multiple sizes, but we only care about the biggest version we can find.
So, discard any smaller versions if bigger versions are available.
Used for attachments and such.
None is considered the biggest size, since supplying no size parameter to a Discord endpoint that accepts multiple sizes
 gives you the full size.
"""
def observe_biggest(size, new_observation, observee_id, sized_observations):
    observe_superlative(
        size,
        new_observation,
        observee_id,
        sized_observations,
        lambda old, new: (old is not None) and (new is None or old < new) # None is assumedly full-size
    )

"""
Observe something that has multiple versions, but we only care about the best version.
So, discard any observations of inferior versions.
Used by wrapper functions observe_newest and observe_biggest.
"""
def observe_superlative(score, new_observation, observee_id, impressions, heuristic):
    if (observee_id not in impressions) or heuristic(impressions[observee_id][0], score):
        impressions[observee_id] = (score, new_observation)

# Used for keeping track of guild member data (mostly nicknames) across time.
member_histories = {} # (user_id, guild_id) : { seen_timestamp : partial Discord Member object }
# Used for keeping track of user data (mostly usernames and avatars) across time.
user_histories = {} # user_id : { seen_timestamp : partial Discord User object }

# The bot flag is inconsistently included in User objects, so it would be annoying to track alongside other user properties.
# Fortunately, it never changes, so let's just track it here.
# May need to change how this works if we ever live in a future where you can wander into a robot factory and get turned into a roomba.
user_id_to_isbot = {} # user_id : isBot

"""
Consume a Discord Member object and file it away in member_histories.
Also observe the Discord User object within.
"""
def observe_member(seen_timestamp, member_dao, guild_id):
    # The Discord Member object contains a bunch of superfluous stuff.
    # Extract only the data we want.
    observation = {k: member_dao[k] for k in ("nick", "avatar", "roles")}
    observe_eternalistically(seen_timestamp, observation, (int(member_dao["user"]["id"]), guild_id), member_histories)
    observe_user(seen_timestamp, member_dao["user"])

"""
Consume a Discord User object and file it away in user_histories.
"""
def observe_user(seen_timestamp, user_dao):
    observation = {k: user_dao[k] for k in ("username", "discriminator", "avatar")}
    assert len(observation) == 3
    user_id = int(user_dao["id"])
    observe_eternalistically(seen_timestamp, observation, user_id, user_histories)
    # Discord User objects don't always include the "bot" property.
    # If this one does, then record it separately.
    if ("bot" in user_dao) and (user_id not in user_id_to_isbot):
        user_id_to_isbot[user_id] = user_dao["bot"]

"""
Observe something that exists over different points in time.
Used by wrapper functions observe_member and observe_user.
"""
def observe_eternalistically(new_timestamp, new_observation, observee_id, histories):
    # If there are no observations on file for this observee, then make a new history with this observation
    if observee_id not in histories:
        histories[observee_id] = {}

    history = histories[observee_id]

    # If we already have an observation for this observee at this exact timestamp, then disregard.
    if new_timestamp in history:
        return
    
    # Check if the previous observation is the same as this one.
    # If it is, no need to record this one; it's redundant.
    # If it's not (or there is no previous observation on file),
    #  then let's add this observation as a new entry in the history.
    lower_timestamps = [t for t in history if t < new_timestamp]
    higher_timestamps = [t for t in history if t > new_timestamp]
    if (not lower_timestamps) or history[max(lower_timestamps)] != new_observation:
        history[new_timestamp] = new_observation

        # Check if the next observation is the same as this one.
        # If it is, then it's redundant; let's get rid of it.
        if higher_timestamps and history[min(higher_timestamps)] == new_observation:
            del history[min(higher_timestamps)]
    
    assert history

"""
Returns our best guess for an eternalistically-tracked object's state was at a given time.
"""
def guess_state_at_time(target_time, history):
    # Try to find the most recent observation that occurred prior to the target time.
    # This should provide our best guess for what the state was at the time of sending.
    prior_observation_timestamps = [t for t in history if t < target_time]
    if prior_observation_timestamps:
        return history[max(prior_observation_timestamps)]
    else: # We only ever observed this object after this time, so use the oldest observation.
        return history[min(history)]
"""
Returns the latest state in an eternalistically-tracked object's history.
"""
def get_latest_observation(history):
    return history[max(history.keys())]
"""
Like guess_state_at_time, but respects CONSISTENT_NAMING_MODE.
If CONSISTENT_NAMING_MODE is true, then this simply returns the latest known state for the history.
(For example, a user's latest username, to avoid deadnaming them.)
Otherwise, it returns our best guess for what the state was at the target time.
Should probably be used for anything relating to a person's identity - username, nickname, avatar, etc.
"""
def guess_name_state_at_time(target_time, history):
    if CONSISTENT_NAMING_MODE:
        return get_latest_observation(target_time, history)
    else:
        return guess_state_at_time(target_time, history)

"""
Each MessageProvenance has a list of MessageObservations for each time the message was observed.
This lets us keep track of message editing and deletion.
Currently sorta overkill, since DCEF has no fancy message edition history rendering.
"""
class MessageProvenance: # Recorded history of a particular message. Sequence of MessageObservations.
    def __init__(self, observation):
        self.observations = [observation]
        self.message_id = observation.message_id
        self.creation_timestamp = datetime.datetime.fromtimestamp(
            # See discord.com/developers/docs/reference#convert-snowflake-to-datetime
            ((self.message_id >> 22) + 1420070400000) / 1000,
            tz=datetime.timezone.utc
        )
    def add_observation(self, observation):
        assert observation.message_id == self.message_id
        # If we now have two deletion observations, just keep the earlier one
        if observation.dmo is None and self.observations[-1].dmo is None:
            self.observations[-1] = min(observation, self.observations[-1])
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
A single "edition" of a particular message and how we observed it (or its absence).
Contains a DMO, or None if we didn't observe the message directly (like if we observed that it was deleted).
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
        if isinstance(dmo_or_message_id, str):
            print(dmo_or_message_id)
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
todo: make this more consistent with other observations?
"""
def observe_dmo(seen_timestamp, dmo, saw_update, channel_id=None, message_id=None):
    if dmo is not None:
        if "author" in dmo:
            observe_user(seen_timestamp, dmo["author"])
        if "code" in dmo:
            print("skipping dmo with code",dmo["code"])
            #pprint(dmo)
            # todo: support "Cannot send messages to this user", code 50007
            return
        if "captcha_key" in dmo:
            print("skipping dmo with captcha_key")
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

#### Analyze traffic! ####

start_time = time.time()

# We print channel names later (which often include emoji), so try printing 🧿 to test if it crashes the output device.
print("\n 🧿 Initializing export 🧿 \n") # If this crashes, your terminal lacks sufficient Unicode support.

print("Analyzing REST traffic.") # todo: report progress percentage
with open(os.path.join(ARCHIVE_PATH, "request_index")) as file:
    for line in file:
        seen_timestamp, method, url, response_hash, filename = line.split()
        seen_timestamp = datetime.datetime.fromtimestamp(float(seen_timestamp), tz=datetime.timezone.utc)
        path = os.path.join(REQUESTS_PATH, filename)
        
        # Messages
        match = re.match(r"https://discord.com/api/v9/channels/(\d*)/messages(\?|$)", url)
        if match:
            with open(path) as request_file:
                try:
                    dmos = json.load(request_file)
                except:
                    # Invalid JSON.
                    # This can happen due to a Discord outage where we got some error page served instead of the JSON response.
                    # We might want to change Wumpus In The Middle to account for that - maybe track response codes?
                    # But for now, it seems easy to just filter out invalid JSON.
                    print("skipping invalid json") # todo: clean this up?
                    continue
            if isinstance(dmos, dict): # if there's only one then Discord fails to encapsulate it in an array??
                dmos = [dmos]
            for dmo in dmos:
                observe_dmo(seen_timestamp, dmo, "REST")

        # Attachments
        elif (
            url.startswith("https://cdn.discordapp.com/attachments/") or
            url.startswith("https://media.discordapp.net/attachments/") or
            url.startswith("https://images-ext-1.discordapp.net/external/") or
            url.startswith("https://images-ext-2.discordapp.net/external/") or
            url.startswith("https://images-ext-3.discordapp.net/external/") or
            url.startswith("https://images-ext-4.discordapp.net/external/") 
        ):
            observe_attachmentoid(url, path)

        # Avatars, guild icons, and emojos (custom emoji)
        elif any(url.startswith("https://cdn.discordapp.com/" + i) for i in ("avatars","icons","emojis","channel-icons")):
            observe_cdnimage(url, path)
        

print("Analyzing websocket traffic.")
# Count the total number of lines in the file
with open(os.path.join(ARCHIVE_PATH, "gateway_index")) as file:
    num_lines = sum(1 for _ in file)

# Re-open the file and iterate through the lines with a progress bar
with open(os.path.join(ARCHIVE_PATH, "gateway_index")) as file:
    for line in tqdm(file, total=num_lines, smoothing=0):
        seen_timestamp, url, gateway_path_base = line.rstrip().split(" ", maxsplit=2)
        try:
            seen_timestamp = datetime.datetime.fromtimestamp(float(seen_timestamp), tz=datetime.timezone.utc)
        except ValueError:
            print(f"Incorrect seen timestamp: {seen_timestamp}")
            continue
        for payload in parse_gateway(os.path.join(ARCHIVE_PATH, "gateways", gateway_path_base), url):
            # Discord calls payload["d"] both "inner payload" and "event data", which are both bad names.
            # Here, I'll just call it the "event".
            event_name, event = payload["t"], payload["d"]
            if event_name in ("MESSAGE_CREATE", "MESSAGE_UPDATE"): # MESSAGE_UPDATE only has ambiguously partial dmo. might cause issues
                observe_dmo(seen_timestamp, event, event_name)
            elif event_name == "MESSAGE_DELETE":
                observe_dmo(seen_timestamp, None, event_name, int(event["channel_id"]), int(event["id"]))
            elif event_name=="READY":
                for user_dao in event["users"] + [event["user"]]:
                    observe_user(seen_timestamp, user_dao)
                for channel_dao in event["private_channels"]:
                    observe_channel(seen_timestamp, channel_dao, None)
                    #assert "women, online" not in str(channel_dao)
                for guild_dao in event["guilds"]:
                    assert guild_dao["data_mode"] == "full", "data mode {}. i don't know what that means sowwy >.<".format(dgo["data_mode"])
                    observe_guild(seen_timestamp, guild_dao)
                    for channel_dao in guild_dao["channels"]:
                        observe_channel(seen_timestamp, channel_dao, int(guild_dao["id"]))
            elif event_name=="GUILD_MEMBER_LIST_UPDATE":
                # see https://arandomnewaccount.gitlab.io/discord-unofficial-docs/lazy_guilds.html
                for op in event["ops"]:
                    assert op["op"] in ("DELETE","INSERT","SYNC","UPDATE","INVALIDATE")
                    if op["op"] in ("INSERT", "UPDATE"):
                        op_items = [op["item"]]
                    elif op["op"] == "SYNC":
                        op_items = op["items"]
                    else:
                        continue
                    for op_item in op_items:
                        if "group" in op_item:
                            continue # skip member "groups" formed by hoisted roles
                        assert "member" in op_item
                        observe_member(seen_timestamp, op_item["member"], int(event["guild_id"]))

print("Collected {} messages, {} attachmentoids, and {} CDN images.".format(
    sum(len(messages) for messages in channel_messages.values()),
    len(attachmentoids),
    len(cdnimages)
))

#### Create the export! ####

# from https://github.com/Tyrrrz/DiscordChatExporter/blob/31c7ae93120276899048df8063658b3483d86f51/DiscordChatExporter.Core/Discord/Data/ChannelKind.cs
DCE_CHANNEL_TYPE_NAMES = {
    0:  "GuildTextChat",
    1:  "DirectTextChat",
    2:  "GuildVoiceChat",
    3:  "DirectGroupTextChat",
    4:  "GuildCategory",
    5:  "GuildNews",
    10: "GuildNewsThread",
    11: "GuildPublicThread",
    12: "GuildPrivateThread",
    13: "GuildStageVoice",
    14: "GuildDirectory",
    15: "GuildForum"
}
# from https://github.com/Tyrrrz/DiscordChatExporter/blob/31c7ae93120276899048df8063658b3483d86f51/DiscordChatExporter.Core/Discord/Data/MessageKind.cs
DCE_MESSAGE_TYPE_NAMES = {
    0:  "Default",
    1:  "RecipientAdd",
    2:  "RecipientRemove",
    3:  "Call",
    4:  "ChannelNameChange",
    5:  "ChannelIconChange",
    6:  "ChannelPinnedMessage",
    7:  "GuildMemberJoin",
    18: "ThreadCreated",
    19: "Reply"
}

EXPORTS_DIR =                 "dcejson_exports"
EXPORT_DIR =                  os.path.join(EXPORTS_DIR, "export_" + str(int(time.time())))
EXPORTED_DMS_DIR =            os.path.join(EXPORT_DIR, "DMs")
EXPORTED_ASSETS_DIR =         os.path.join(EXPORT_DIR, "assets")
EXPORTED_AVATARS_DIR =        os.path.join(EXPORTED_ASSETS_DIR, "avatars")
EXPORTED_GUILDICONS_DIR =     os.path.join(EXPORTED_ASSETS_DIR, "guildicons")
EXPORTED_ATTACHMENTOIDS_DIR = os.path.join(EXPORTED_ASSETS_DIR, "attachmentoids")

if not DRY_RUN:
	os.makedirs(EXPORTS_DIR, exist_ok=True)
	for directory in (EXPORT_DIR, EXPORTED_DMS_DIR, EXPORTED_ASSETS_DIR, EXPORTED_AVATARS_DIR, EXPORTED_GUILDICONS_DIR, EXPORTED_ATTACHMENTOIDS_DIR):
		os.mkdir(directory)

mirrored_assets = {} # old path : new path

def mirror_asset(downloaded_path, name_suggestion="", preserve_ext=False, target_dir=EXPORTED_ASSETS_DIR, relate_to=None): 
    if downloaded_path not in mirrored_assets:
        # DCEF searches for asset files by filtering a glob search through the regex .+\-[A-F0-9]{5}(?:\..+)?
        # So, we need to make our asset filenames match that pattern.
        suffix = "-" + format(len(mirrored_assets), "05X")
        
        # We could avoid filling the ID space by assigning asset IDs more cleverly
        # (like foo-00000.jpg, bar-00000.jpg, foo-00001.jpg)
        # But for now, let's just error out if there are more than 16^5 assets.
        assert len(mirrored_assets) < 16**5, "Sorta ran out of asset namespace, sorry! Todo: fix this."
        
        if preserve_ext:
            # Try to preserve extension from name suggestion; DCEF seems to rely on it in some cases.
            name_suggestion, ext = os.path.splitext(name_suggestion)
            if len(ext) < 6: # Otherwise probably not a real extension, and if it is, DCEF probably does not need it anyway.
                suffix += ext

        mirrored_assets[downloaded_path] = os.path.join(target_dir, reasonable_filename(
            name_suggestion,
            suffix=suffix
        ))
    return os.path.relpath(mirrored_assets[downloaded_path], start=relate_to)

"""
Take a name "suggestion" and turn it into a "reasonable" filename that should be valid on most operating systems.
`suffix`, if given, is a REQUIRED suffix of the filename.
"""
def reasonable_filename(name_suggestion, suffix=""): # needs cleaned up
    assert all(c.isalnum() or c in "_[-]." for c in suffix), name_suggestion + " ⋄ " + suffix
    assert len(suffix) <= MAX_FILENAME_LENGTH, "length of required suffix {} exceeded max filename length {}".format(suffix, MAX_FILENAME_LENGTH)
    return "".join(c if (c.isalnum() or c in "[-]") else "_" for c in name_suggestion)[:MAX_FILENAME_LENGTH - len(suffix)] + suffix

"""
Take a proxy_url (or just a "url", in some cases) from an embed
and return a mirrored path to be referenced in the export.
"""
def embed_proxy_url_to_dce_url(proxy_url):
    downloaded_path = find_attachmentoid_downloaded_path_by_url(proxy_url)
    if downloaded_path:
        return mirror_asset(
            downloaded_path,
            name_suggestion=urllib.parse.urlparse(proxy_url).path.split("/")[-1],
            preserve_ext=True,
            target_dir=EXPORTED_ATTACHMENTOIDS_DIR,
            relate_to=EXPORT_DIR
        )
    else:
        return maybe_hotlink(proxy_url)

stats = {
    "hotlinks": 0
}

"""
Returns url if hotlinking is enabled. Returns None otherwise.
todo: this function is currently pointless since HOTLINK_MISSING_ASSETS is required by DCEF
"""
def maybe_hotlink(url):
    if HOTLINK_MISSING_ASSETS:
        stats["hotlinks"] += 1
        return url

if DRY_RUN:
    print("DRY_RUN is True, so not actually exporting anything this time.")

print("Exporting DiscordChatExporter-style JSON to {}.".format(EXPORT_DIR))

for channel_id, message_id_to_provenance in channel_messages.items():
    if CHANNELS_TO_EXPORT_IDS is not None and channel_id not in CHANNELS_TO_EXPORT_IDS:
        continue
    
    if channel_id not in channel_impressions:
        print("skipping unidentified channel {}. ><'".format(channel_id))
        continue
    
    _, channel_dao = channel_impressions[channel_id]
    guild_id = channel_id_to_guild_id[channel_id]
        
    if (guild_id is not None) and (guild_id not in guild_impressions):
        print("Skipping channel with unidentified guild {}. U_U".format(channel.guild_id))
        continue

    channel_name = channel_dao.get("name")
    
    if guild_id is None: # DMs / Group DMs
        guild_id = 0 # DCE treats guildless channels as having a guild with ID 0.
        guild_name = "Direct Messages"
        if channel_name is None: # Make up a channel name consisting of the recipients' names
            recipient_names = []
            for recipient_id in channel_dao["recipient_ids"]:
                recipient_id = int(recipient_id)
                if recipient_id in user_histories:
                    recipient_names.append(get_latest_observation(user_histories[recipient_id])["username"])
                else:
                    recipient_names.append(recipient_id)
            channel_name = ", ".join(recipient_names)
            
        guildicon_name_suggestion = channel_name
        guildicon_downloaded_path = None
        if "icon" in channel_dao:
            # Really a "channel icon" for group DMs, but DCE calls it a guild icon, so let's call it that.
            guildicon_downloaded_path = find_channelicon(channel_id, channel_dao.get("icon"))
        elif channel_dao["type"] == 1 and channel_dao["recipient_ids"] and recipient_id in user_histories: # Direct DM
            # We could use the recipient's avatar as guild/channel icon,
            # but then DCEF just picks a single one to use for all DMs.
            # So, let's comment this out and leave the avatar null.
            # guildicon_downloaded_path = find_avatar(recipient_id, get_latest_observation(user_histories[recipient_id]).get("avatar"))
            # Todo: optionally split DMs into their own fake "guild"s
            pass
    else:
        _, guild_dao = guild_impressions[guild_id]
        guild_name = guild_dao["properties"]["name"]
        guildicon_name_suggestion = guild_name
        guildicon_downloaded_path = find_guildicon(guild_id, guild_dao["properties"]["icon"])
    
    print("Exporting " + channel_name)

    dce_guildicon_url = None
    if guildicon_downloaded_path is not None:
        dce_guildicon_url = mirror_asset(
            guildicon_downloaded_path,
            name_suggestion=guildicon_name_suggestion + os.path.splitext(guildicon_downloaded_path)[1],
            preserve_ext=True,
            target_dir=EXPORTED_GUILDICONS_DIR,
            relate_to=EXPORT_DIR
        )
    
    if channel_dao.get("parent_id") is not None: # apparently this can be absent OR null for orphan channels
        channel_parent_id = int(channel_dao["parent_id"])
        if channel_parent_id in channel_impressions:
            channel_parent_name = channel_impressions[channel_parent_id][1]["name"]
        else:
            channel_parent_name = "UNKNOWN CHANNEL PARENT >~<'"
            print("Failed to identify parent channel for {} [{}].".format(channel_dao["name"], channel_id))
    else:
        channel_parent_name = None
    
    dce_channel = {
        "guild": {
            "id": guild_id,
            "name": guild_name,
            "iconUrl": dce_guildicon_url
        },
        "channel": {
            "id": channel_id,
            "type": DCE_CHANNEL_TYPE_NAMES[channel_dao["type"]],
            "categoryId": channel_dao.get("parent_id"), # not sure if this should be null or absent for orphan channels
            "category": channel_parent_name,
            "name": channel_name,
            "topic": channel_dao.get("topic")
        },
        "dateRange": {"after":None,"before":None}, #???
        "messages": []
    }
    
    provenances = list(message_id_to_provenance.values())
    provenances.sort()
    for provenance in provenances:
        # We don't care about message provenance; just get the latest observed Discord Message Object for this message.
        dmo = provenance.observations[-1].dmo
        if dmo is None: # message deleted. todo: optionally include these?
            continue
        
        if "timestamp" not in dmo: # Not sure why this happens. Messages of type "article"?
            print("Skipping timestampless message.")
            continue
        message_sent_time = get_dmo_time(dmo)

        user_id = int(dmo["author"]["id"])
        member_id = (user_id, guild_id)
        
        if member_id in member_histories: # If we have Member data for this author
            member_dao = guess_name_state_at_time(message_sent_time, member_histories[member_id])
            author_color = None # todo
        else: # Oops, we've never observed this member.
            member_dao = {} # Use an empty dict for member data so that member_dao.get returns None later.
        
        user_dao = guess_name_state_at_time(message_sent_time, user_histories[user_id])
        author_name = user_dao["username"]
        author_discriminator = user_dao["discriminator"]
        
        avatar = find_avatar(user_id, user_dao["avatar"])
        if avatar:
            dce_avatar_url = mirror_asset(
                avatar,
                name_suggestion=author_name,
                preserve_ext=False,
                target_dir=EXPORTED_AVATARS_DIR,
                relate_to=EXPORT_DIR
            )
        else:
            # todo: could use an explicit 404 avatar to show that the user DID have an avatar, we just don't have it
            dce_avatar_url = None

        dce_attachments = []
        for attachment_dao in dmo["attachments"]:
            attachment_downloaded_path = find_attachmentoid_downloaded_path_by_url(attachment_dao["proxy_url"])
            if attachment_downloaded_path:
                dce_attachment_url = mirror_asset(
                    attachment_downloaded_path,
                    name_suggestion=attachment_dao["filename"],
                    preserve_ext=True,
                    target_dir=EXPORTED_ATTACHMENTOIDS_DIR,
                    relate_to=EXPORT_DIR
                )
            else:
                # We don't have it, so just hotlink to Discord if configured to do so
                dce_attachment_url = maybe_hotlink(attachment_dao["proxy_url"])
            
            dce_attachments.append({ # DCE uses the keys "id", "url", "fileName", and "fileSizeBytes"
                "id": attachment_dao["id"],
                "fileName": attachment_dao["filename"],
                "fileSizeBytes": attachment_dao["size"],
                "url": dce_attachment_url or maybe_hotlink(attachment_dao["proxy_url"])
            })
            assert dce_attachments[-1]["fileSizeBytes"] is not None
            assert "../" not in dce_attachments[-1]["url"]
        
        dce_message = {
            "id": str(dmo["id"]),
            # todo: Not sure what I should be doing with messages with types that DCE does not have constants for.
            # Do I just leave them out? Or make this null?
            "type": DCE_MESSAGE_TYPE_NAMES.get(dmo["type"]),
            "timestamp": dmo["timestamp"],
            "timestampEdited": dmo["edited_timestamp"],
            "isPinned": dmo["pinned"],
            "content":dmo["content"],
            "author": {
                "id": str(user_id),
                "name": author_name,
                "discriminator": author_discriminator,
                "nickname": member_dao.get("nick"),
                "color": None, # todo 
                "isBot": user_id_to_isbot.get(user_id),
                "avatarUrl": dce_avatar_url
            },
            "attachments": dce_attachments, #id, url, fileName, fileSizeBytes
            "embeds": [],
            "stickers": [], # todo
            "reactions": [], # todo
            "mentions": [] # todo?
        }
        dce_channel["messages"].append(dce_message)
        
        for deo in dmo["embeds"]:
            dce_embed = {
                # I think DCEF needs these keys to be specified even if absent on the Discord Embed Object
                "title": deo.get("title") or "",
                "description": deo.get("description") or "",
                "timestamp": deo.get("timestamp") or ""
            }

            # DCE translates Discord's integer colors to hex codes; replicate that.
            if "color" in deo: 
                dce_embed["color"] = "#" + format(deo["color"], "06X")

            # Embeds can have a Thumbnail, a Video, and/or an Image.
            # These have basically the same data structure, so let's handle them all here.
            # Each has a proxy_url that we need to mirror
            # ... except sometimes it has a "url" instead, in which case let's mirror that.
            for embed_asset_type in ("thumbnail", "video", "image"):
                if embed_asset_type in deo:
                    dce_embed_asset = {}
                    dce_embed[embed_asset_type] = dce_embed_asset
                    
                    if "proxy_url" in deo[embed_asset_type]:
                        dce_embed_asset["url"] = embed_proxy_url_to_dce_url(deo[embed_asset_type]["proxy_url"])
                    elif "url" in deo[embed_asset_type]:
                        dce_embed_asset["url"] = embed_proxy_url_to_dce_url(deo[embed_asset_type]["url"])
                    
                    for k in ("width", "height"):
                        if k in deo[embed_asset_type]:
                            dce_embed_asset[k] = deo[embed_asset_type][k]

            # Embeds can have an Author and/or a Footer.
            # These have similar data structures, so let's handle them all here.
            # Author has a "url" property, but this is actually a hyperlink to the author's page, not an asset we should mirror.
            # Instead, we need to mirror the proxy_icon_url.
            for embed_asset_type in ("author", "footer"):
                if embed_asset_type in deo:
                    dce_embed[embed_asset_type] = {}
                    assert "proxy_icon_url" in deo[embed_asset_type] or "icon_url" not in deo[embed_asset_type]
                    if "proxy_icon_url" in deo[embed_asset_type]:
                        # todo: this does not seem to work for DCEF
                        dce_embed[embed_asset_type]["iconUrl"] = embed_proxy_url_to_dce_url(deo[embed_asset_type]["proxy_icon_url"])
                    # Copy other properties to the exported embed.
                    for k in ("name", "url", "text"):
                        if k in deo[embed_asset_type] and k not in dce_embed[embed_asset_type]:
                            dce_embed[embed_asset_type][k] = deo[embed_asset_type][k]
            
            # Copy any remaining keys from the Discord Embed object to the DCE Embed object.
            # This includes Fields, Provider, maybe more.
            for k in deo:
                if k not in dce_embed:
                    dce_embed[k] = deo[k]
            
            dce_message["embeds"].append(dce_embed)                

    dce_channel["messageCount"] = len(dce_channel["messages"])

    channel_export_path = os.path.join(
        EXPORT_DIR,
        reasonable_filename(
            channel_name,
            # Annoyingly, the brackets here are actually kind of necessary;
            # DCEF ignores any channel export whose name contains a match for the regex "([A-F0-9]{5})\.json$".
            suffix="[" + str(channel_id) + "].json"
        )
    )
    
    if not DRY_RUN:
        with open(channel_export_path, "w") as file:
            json.dump(dce_channel, file)

# Check for asset name collisions.
target_asset_paths = set()
for target_asset_path in mirrored_assets.values():
    if target_asset_path in target_asset_paths:
        print("oh uh, asset name collision >~<' " + target_asset_path)
    target_asset_paths.add(target_asset_path)

if not DRY_RUN:
    print("\nExporting " + str(len(mirrored_assets)) + " assets... >.<'") #todo: report progress
    for source, dest in mirrored_assets.items():
        copyfile(source, dest)
    
    print("Export saved to " + EXPORT_DIR)
    print(str(len(mirrored_assets)) + " assets saved to " + EXPORTED_ASSETS_DIR)
    # todo: asset details. how many avatars, etc?
    if stats["hotlinks"]: print("Hotlinked " + str(stats["hotlinks"]) + " missing assets.")

print("Finished in " + str(int((time.time() - start_time) // 60)) + " minutes.")
print("\n ✨ All done. UwU ✨ \n")
