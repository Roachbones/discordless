# DCEJSON format

Here I try to document the JSON format that [DiscordChatExporter](https://github.com/Tyrrrz/DiscordChatExporter) and Discordless output, and [DiscordChatExporter-frontend](https://github.com/slatinsky/DiscordChatExporter-frontend) and [Chat Analytics](https://github.com/mlomb/chat-analytics) expect as input.

An export consists of:

- A set of json files, each one representing a channel, storing its messages and metadata. I'll call these files "channel jsons".
- A set of asset files such as attachments, referenced by the json files. I'll call these "assets".

in no particular directory structure (though with naming requirements defined below). A channel json references assets in relation to its parent directory. The files in an export may have filenames long enough to require [a registry edit to increase the maximum path length on Windows](https://github.com/slatinsky/DiscordChatExporter-frontend/tree/6059ec4c21192e67cda0b671fcd6b4a213eb4b2c/release/registry_tweaks).

## Assets

An asset's filename must match the regex `.+\-[A-F0-9]{5}(?:\..+)?`. For example, `maxresdefault-612A2.png` or `vivian-avatar-00747`.

Assets representing attachments or embedded images must retain their extension. Assets representing guild icons or user avatars may omit the extension.

DiscordChatExporter-frontend represents attachments by these filenames in its UI, so their names should approximate the original filenames used by the attachments. **is this true? why?**

## Channel jsons

### Channel json filenames

A channel json's filename must end in `.json`, but must *not* end in a match for the regex `([A-F0-9]{5})\.json$`. (DiscordChatExporter-frontend uses it to distinguish between assets that happen to be json files and channel jsons.) **todo: PR for DCEF to prepend a hyphen to this regex?**

### Channel json contents

A channel json must be a valid json file that contains the string "guild" within the first 16 bytes ([DCEF expects it](https://github.com/slatinsky/DiscordChatExporter-frontend/blob/6059ec4c21192e67cda0b671fcd6b4a213eb4b2c/backend/preprocess/FileFinder.py#L29)).

Objects in the channel json are based on Discord's API objects, but with some changes. To summarize, these changes are:
 - Spell keys in camelCase
 - Replace enumerated values with strings representing those values (Message Type and Channel Type)
 - Consistently represent [Snowflakes](https://discord.com/developers/docs/reference#snowflakes) as strings, not ints
 - Replace Discord URLs for assets, such as attachment URLs, with local paths to downloaded versions of those assets if possible. Otherwise, they remain as URLs.
 - Always omit `proxy_url`; when its equivalent local path is needed, use the `url` key.
 - Represent colors as hex codes instead of ints

A channel json should contain these keys and values:

- guild: object, containing:
  - id: string, integer id of the channel's guild.
  - name: string, name of the channel's guild.
  - iconUrl: string?, path to the guild's icon.
- channel: object, containing:
  - id: string, integer id of the channel.
  - name: string, name of the channel.
  - categoryId: string, integer id of the channel's "parent". [Discord calls this the `parent_id`](https://discord.com/developers/docs/resources/channel#channel-object), and explains: *for guild channels: id of the parent category for a channel (each parent category can contain up to 50 channels), for threads: id of the text channel this thread was created*. Channel "parents" are represented as Channels in the Discord API.
  - category: string, name of the channel's "parent".
  - topic: string?, channel topic.
  - type: string, DiscordChatExporter's name for the channel's Type. Must be a string in [DCE's ChannelKind enum](https://github.com/Tyrrrz/DiscordChatExporter/blob/31c7ae93120276899048df8063658b3483d86f51/DiscordChatExporter.Core/Discord/Data/ChannelKind.cs) (copied below for reference), which is based on (but different from) [Discord's string names for channel types](https://discord.com/developers/docs/resources/channel#channel-object-channel-types).
    ```
    GuildTextChat = 0,
    DirectTextChat = 1,
    GuildVoiceChat = 2,
    DirectGroupTextChat = 3,
    GuildCategory = 4,
    GuildNews = 5,
    GuildNewsThread = 10,
    GuildPublicThread = 11,
    GuildPrivateThread = 12,
    GuildStageVoice = 13,
    GuildDirectory = 14,
    GuildForum = 15
    ```
- dateRange: object, containing: **todo: what's this for?**
  - after: null (?)
  - before: null (?)
- messages: array, containing objects, containing:
  - id: string, message id
  - type: DiscordChatExporter's name for the message's Type. Must be a string in [DCE's MessageKind enum](https://github.com/Tyrrrz/DiscordChatExporter/blob/31c7ae93120276899048df8063658b3483d86f51/DiscordChatExporter.Core/Discord/Data/MessageKind.cs) (copied below for reference), which is based on (but different from) [Discord's string names for message types](https://discord.com/developers/docs/resources/channel#message-object-message-types).
    ```
    Default = 0,
    RecipientAdd = 1,
    RecipientRemove = 2,
    Call = 3,
    ChannelNameChange = 4,
    ChannelIconChange = 5,
    ChannelPinnedMessage = 6,
    GuildMemberJoin = 7,
    ThreadCreated = 18,
    Reply = 19
    ```
    If the message's type is absent from DiscordChatExporter's MessageKind enum, then... maybe make it null? Or omit the message entirely? **todo: which is it?**
  - timestamp: string, ISO8601 timestamp (same as Discord uses), time the message was sent
  - timestampEdited: string?, ISO8601 timestamp, time the message was last edited, or null if it's unedited.
  - callEndedTimestamp?: string, ISO8601 timestamp, time the call ended if this message represents a call, null *or absent* otherwise. **todo: Discordless does not use this at all yet**
  - isPinned: bool, whether the message is pinned.
  - content: string, message content.
  - author: object, containing:
    - name: string, author's username.
    - discriminator: string?(?), author's discriminator, without the #.
    - nickname: string?(?), author's nickname. **Todo: does DCEF use this?**
    - color: string?, hex color (including the #) representing the author's name color in this server.
    - isBot: bool, whether the user is a bot.
    - avatarUrl: string?, path to the user's avatar.
  - attachments: array, containing objects, containing:
    - id: string, attachment id
    - fileName: string. [Discord calls this `filename`.](https://discord.com/developers/docs/resources/channel#attachment-object) **todo: this is just for DCEF's download UI, right?**
    - fileSizeBytes: int, number of bytes in attachment. [Discord calls this `size`.](https://discord.com/developers/docs/resources/channel#attachment-object)
    - url: string, path to attachment's asset file
  - embeds: array, containing objects based on [Discord's Embed object](https://discord.com/developers/docs/resources/channel#embed-object) but with a few differences.
    
    If a value in the Embed object is a URL pointing to an asset on Discord, then it should be replaced with a local path to the asset, similar to other such URLs. The keys whose values should be modified in this way vary between Embed Types. 
    
    `thumbnail`, `video`, and `image` type Embeds are like Attachments in that their `proxy_url`s should be omitted and their `url`s replaced with local paths. `author` and `footer` type Embeds should have their `url`s unchanged (as they refer to actual hyperlinks, not paths to assets) but their `proxy_icon_url`s should be replaced with `iconUrl`s pointing to local paths. **todo: not sure about the iconUrl; see [issue 6](https://github.com/Roachbones/discordless/issues/6)**
    
    As an extra bit of embed postprocessing, "multi-image embeds" are represented by Discord as multiple consecutive embeds, but represented by DCE as one embed. This one embed has all images from the other embeds listed under its `images` key.
    
  - stickers: array, containing objects, containing:
    - **idk, todo**
  - reactions: array, containing objects ([similar to Discord's Reaction objects](https://discord.com/developers/docs/resources/channel#reaction-object)), containing:
    - emoji: object, containing:
      - id: string. For non-custom emoji, this should be the empty string. For custom emoji, the custom emoji's ID.
      - name: string. For non-custom emoji, this should be the emoji itself; for example, "\uD83D\uDC40". For custom emoji, the custom emoji's name.
      - isAnimated: bool, whether the emoji is animated. **todo: is this used?**
      - imageUrl: path to the emoji as an image. **todo: is this necessary for non-custom emoji?**
    - count: int, how many people 
  - mentions: array, containing objects, containing `id`, `name`, `discriminator?`, `nickname`, `isBot`, similar to the `author` object defined above.
- messageCount?: length of the messages array.

DM channels are open to interpretation. DCE exports them as having a guild of ID 0 and name "Direct Messages". Alternatively, you could make up a separate fake guild for each DM channel, which would allow you to define guild icons for group DMs.

Here's an example of the contents of a channel json containing a single message:

```
{
  "guild": {
    "id": "0",
    "name": "Direct Messages",
    "iconUrl": "Direct Messages - Private - Deleted User 2d4b7dbb [897616348878872660].json_Files\\0-EB806.png"
  },
  "channel": {
    "id": "897616348878872660",
    "type": "DirectTextChat",
    "categoryId": "0",
    "category": "Private",
    "name": "Deleted User 2d4b7dbb",
    "topic": null
  },
  "dateRange": {
    "after": null,
    "before": null
  },
  "messages": [
    {
      "id": "897616432739799082",
      "type": "Default",
      "timestamp": "2021-10-12T22:47:14.472+00:00",
      "timestampEdited": null,
      "callEndedTimestamp": null,
      "isPinned": false,
      "content": "Hello",
      "author": {
        "id": "434468647994523650",
        "name": "Slada",
        "discriminator": "7077",
        "nickname": "Slada",
        "color": null,
        "isBot": false,
        "avatarUrl": "Direct Messages - Private - Deleted User 2d4b7dbb [897616348878872660].json_Files\\606d47abe5d938a482e737a05c54fabe-8B00F.png"
      },
      "attachments": [],
      "embeds": [],
      "stickers": [],
      "reactions": [],
      "mentions": []
    }
  ],
  "messageCount": 1
}
```





