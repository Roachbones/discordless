# Discordless

Automatically save local archives of Discord conversations and render them as HTML or [DiscordChatExporter-frontend](https://github.com/slatinsky/DiscordChatExporter-frontend) compatible JSON.

# How it works

Discord uses [an HTTPS REST API](https://discord.com/developers/docs/reference) and [Websocket API](https://discord.com/developers/docs/topics/gateway) to transfer data. Discordless's [mitmproxy](https://docs.mitmproxy.org/stable/) addon, Wumpus In The Middle, intercepts that traffic and saves it locally as it is fetched. Discordless's exporter scripts can then render that saved data as HTML or [DiscordChatExporter-frontend](https://github.com/slatinsky/DiscordChatExporter-frontend)-compatible JSON for easy viewing.

Once you connect your Discord client to mitmproxy, Wumpus In The Middle automatically saves any data that your client fetches. Therefore, all messages, attachments, icons, etc. that you view will be saved. If you want to archive an entire channel at once, you will have to scroll through the whole thing, and maybe click on image attachments to load full-res versions.

# Motivation
Discord has a history of arbitrary, unexpected, unappealable bans, which make you lose access to all your messages. If you want to keep records of your heartfelt conversations, you should probably save your own copies in case you lose access to your account or Discord shuts down someday. There are also a lot of communities that treat Discord as a documentation hub that ought to be archived.

There already exist tools to archive Discord channels, the most popular one being [DiscordChatExporter](https://github.com/Tyrrrz/DiscordChatExporter), but they violate Discord's frustratingly strict Terms of Service. Exporting DMs with these tools requires "self-botting", which is a bannable offense - though it anecdotally seems to be rarely enforced against exporter tools. Nobody knows how Discord's auto-moderation and botting detection algorithms work, so I'd rather not risk it.

Discordless does not create any API requests or modify client behavior at all, so I don't think it violates Discord's Terms of Service, and it should be harder for Discord to detect. It also runs in the background, so you don't have to remember to backup regularly. It also works for mobile devices (as long as they are connected to Discordless's proxy server), which is nice for me since I primarily use Discord on my phone.

The archives are also "archive-grade" if you care about that; Discordless stores the raw API responses.

# Install and setup - Debian-based Linux

You'll need to install Python, mitmproxy, and [Discord's erlpack library](https://github.com/discord/erlpack).

Here are example commands you can use on Ubuntu. Assumes you use Python 3.9, but any 3.x version should work.

- Install Python: `sudo apt install python3.9 python3.9-dev python3.9-idle`
- Update pip: `python3.9 -m pip install --upgrade pip`
- Install mitmproxy: download the binaries from [mitmproxy.org](https://mitmproxy.org/)
- [Install mitmproxy's certificate](https://docs.mitmproxy.org/stable/concepts-certificates/#quick-setup) on every device with a Discord client that you want to archive with. (Sometimes you also have to install it on the browser level.)
- Install filetype and erlpack: `python3.9 -m pip install filetype erlpack`

## erlpack installation issue workaround

**Not sure if this is still the case; try this if you get an error when trying to install erlpack.**

Discord uses a tool called erlpack to deserialize objects sent over the Gateway websocket, but it's currently(?) broken. There's a pull request open for oliver-ni's branch, which fixes the problem, but Discord hasn't merged it. So, just install Oliver's version: 
```
pip install git+https://github.com/oliver-ni/erlpack.git#egg=erlpack`
```

# Install and setup - Mac
Mostly the same as the Debian-based Linux setup.

- Install Python 3.9+
- Install erlpack: `pip install git+https://github.com/oliver-ni/erlpack.git#egg=erlpack`
- [Install mitmproxy](https://docs.mitmproxy.org/stable/overview-installation/#macos): `brew install mitmproxy`
- Run mitmproxy at least once to generate its certificate: `mitmproxy`
- [Install mitmproxy's certificate](https://docs.mitmproxy.org/stable/concepts-certificates/#quick-setup): `sudo security add-trusted-cert -d -p ssl -p basic -k /Library/Keychains/System.keychain ~/.mitmproxy/mitmproxy-ca-cert.pem`

# Install and setup - Windows

Make sure Python 3.9+ is installed. There is a problem with installing `erlpack` dependency on Windows, so Python 3.11+ is not supported. To check if Python is installed, open command prompt (Windows key + R, type `cmd` and press Enter) and run command:
```
py --version
```

If Python is not installed, [download and install version 3.9.X or 3.10.X from official site](https://www.python.org/downloads/). During installation, don't forget to check "Add Python 3.X to PATH".

Clone this project (Open folder where you want to clone this project in file explorer, press Alt + D, type `cmd` and press Enter)
```
git clone https://github.com/Roachbones/discordless
cd discordless
```

Update pip and install `erlpack` and `python-dateutil` dependencies:
```
py -m pip install --upgrade pip
py -m pip install git+https://github.com/oliver-ni/erlpack.git#egg=erlpack
py -m pip install python-dateutil filetype
```

Install mitmproxy from [official site](https://mitmproxy.org/). Mitmproxy installer for windows should automatically add `mitmproxy`, `mitmdump` and `mitmweb` to path. Close all opened command prompts to update PATH variable.

Open elevated command prompt (Windows key + R, type `cmd` and press Ctrl + Shift + Enter)

Generate certificates by running mitmproxy the first time:
```
mitmproxy.exe
```

Install mitmproxy certificate:
```
cd %UserProfile%\.mitmproxy\
certutil -addstore root mitmproxy-ca-cert.cer
```


# Usage

## Step one: data collection - Debian based Linux

Start the proxy server: `mitmdump -s wumpus_in_the_middle.py --listen-port=8080 --allow-hosts '^(((.+\.)?discord\.com)|((.+\.)?discordapp\.com)|((.+\.)?discord\.net)|((.+\.)?discordapp\.net)|((.+\.)?discord\.gg))(?::\d+)?$'`

Start Discord, connected to the proxy server. If you're on a PC, you can do `discord --proxy-server=localhost:8080` to start an instance of Discord connected to the proxy without having to configure your whole computer to use the proxy. You can replace `localhost:8080` with some other address if the proxy server is running on a different device. If you're on mobile, or otherwise don't want to use that commandline argument, then configure the whole device to use the proxy server in the network settings. Due to the `--allow-hosts` argument we pass to mitmproxy, it should not interfere much with non-Discord traffic.

You can tell that data collection is working if `traffic_archive/requests/` starts filling up.

## Step one: data collection - Windows

Start the proxy server in the first command prompt (Windows key + R, type `cmd` and press Enter):
```
mitmdump -s wumpus_in_the_middle.py --listen-port=8080 --allow-hosts "^(((.+\.)?discord\.com)|((.+\.)?discordapp\.com)|((.+\.)?discord\.net)|((.+\.)?discordapp\.net)|((.+\.)?discord\.gg))(?::\d+)?$"
```

Discord executable is not in PATH; we need to find it manually. Open second command prompt (Windows key + R, type `cmd` and press Enter)
```
cd %LocalAppData%\Discord\app-<version>\
cd app-
[tab]
[enter]
discord --proxy-server=localhost:8080
```

## Step two: export archived traffic to DCE-style JSON (or HTML)

If Wumpus In The Middle is still running, restart it (ctrl+c in the terminal) to ensure it flushes its file buffers. Then run `dcejson_exporter.py` or `html_exporter.py` to turn the data in `traffic_archive/` into an export.

### DCE-style JSON

`dcejson_exporter.py` reads the data in `traffic_archive` and outputs a [DiscordChatExporter](https://github.com/Tyrrrz/DiscordChatExporter)-style JSON export to `dcejson_exports/export_{current Unix time}/`. You can feed that export into [DiscordChatExporter-frontend](https://github.com/slatinsky/DiscordChatExporter-frontend) to neatly display it in a Discord-style interface.

### HTML

HTML exporting is half-baked at this point; embeds do not work, and there's no pagination. It can show some extra data, though, like message edit history.

You can run `html_exporter.py` similar to `dcejson_exporter.py`.

## Step three: view the export

### DiscordChatExporter-style JSON

Use [DiscordChatExporter-frontend](https://github.com/slatinsky/DiscordChatExporter-frontend) to view JSON exports. JSON exports should also be compatible with other DiscordChatExporter-based tools, such as [chat-analytics](https://github.com/mlomb/chat-analytics).

### HTML

Open one of the folders in the export (each folder corresponding to a channel, but good luck distinguishing them) and open `chatlog.html` in your favorite web browser. Unlike the JSON export, each channel folder contains its own assets, so any channel folder can be individually moved outside the export folder without breaking image links.

## More technical details

Here's a breakdown of the Wumpus In The Middle invocation command (`mitmdump -s wumpus_in_the_middle.py --listen-port=8080 --allow-hosts '^(((.+\.)?discord\.com)|((.+\.)?discordapp\.com)|((.+\.)?discord\.net)|((.+\.)?discordapp\.net)|((.+\.)?discord\.gg))(?::\d+)?$'`):
- `--listen-port=8080` tells mitmdump to run the proxy server on port 8080. Feel free to change this.
- `--allow-hosts '^(((.+\.)?discord\.com)|((.+\.)?discordapp\.com)|((.+\.)?discord\.net)|((.+\.)?discordapp\.net))(?::\d+)?$'` tells mitmproxy to not intercept any https traffic besides traffic to Discord. This is a little redundant since Wumpus In The Middle is also programmed to focus on Discord traffic, but this improves performance and helps to avoid interfering with any sites that have strict certificate policies.
- In theory, you can also add ` --proxyauth 'username:password'` to the end to require authentication to connect to the proxy. However, I haven't been able to get this to work when connecting to the proxy from my iPhone; I get 407 errors even if I specify proxy authentication in my phone's network settings. **Let me know if you get it to work!**

Although you can connect multiple devices to the same Wumpus In The Middle instance, do not do so with multiple Discord accounts; Discordless currently assumes that all traffic is from one account and does not distinguish between multiple accounts. (I guess you could make a conglomerate archive of all of the servers of multiple accounts if you wanted, though.)

## Directory structure

- Wumpus In The Middle saves Discord traffic to a neighboring directory called `traffic_archive/`. `chatlog_exporter.py` reads the data in this directory. This directory will grow over time. Contents:
	- `request_index`:
	Keeps track of metadata for each recorded HTTPS response. Each line is structured like `{timestamp} {method (GET or POST)} {url} {response hash} {filename}`. The filename points to a file in `traffic_archive/requests/` which contains the response contents. 
	- `requests/`: Stores response contents. Contents tracked in `request_index/`.
	- `gateway_index`: Tracks metadata for each recorded Gateway (websocket) connection. Each line is structured like `{timestamp} {url} {filename prefix}`. The filename prefix points to a pair of files in `traffic_archive/gateways/`, which end in `_data` and `_timeline`.
	- `gateways/`: Stores compressed Gateway "message" contents and timing information, in pairs of files ending in `_data` and `_timeline` respectively. Each Gateway lasts a long time (like, until you quit the client), and is tranport compressed via zlib. The `_data` file contains the entire Gateway "response"/"stream" (every "message" concatenated together) while the `_timeline` file keeps track of when each compressed "chunk"/"message" was received. Each line of the `_timeline` file is structured like `{timestamp} {chunk length}`.
- `dcejson_exporter.py` exports to `dcejson_exports/`. Each export is a directory named something like `export_1686901312` where the number is the Unix time that the export was made.
- `html_exporter.py` similarly exports to `html_exports/`.
- `html_template/` stores some static files that `html_exporter.py` uses to generate HTML exports.
	- `html_template/style.css` is a stylesheet that gets copied to every HTML export.
	- `html_template/index.html` is a Jinja template that gets filled with chatlog data to render HTML exports.


# Limitations

## iOS websocket traffic ignores proxy settings

iOS seems to ignore HTTP proxy settings for websockets (pls tell me if you know why this is and how to fix it), so Discordless fails to sniff websocket traffic from iOS devices. However, much of the archived data comes from regular REST endpoints instead, so you can still get decent data coverage without websockets!

In a nutshell: regular REST endpoints are used for you to say stuff to Discord like "Load the messages in this channel!" and "Load this image!". Websockets are for the server to tell you stuff like "Hey, this person sent you a message!". The latter should be mostly redundant if you often switch between different channels (thus reloading the messages via REST).



# Comparison to DiscordChatExporter
Discordless requires technical knowledge to set up and its realtime archive-grade backups are overkill for most people. Here's a feature comparison between it and DiscordChatExporter, the most popular Discord archiving tool:

|  | DiscordChatExporter | Discordless |
|---|---|---|
| Easy to use? | Yes, more or less! **Thus, it remains superior for most people.** | Not yet! Requires some technical setup. Hoping to make it easier eventually. |
| Obeys Discord's ToS? | Not if you export DMs (which requires self-botting), though its violations are probably rarely enforced. | Yes |
| Archives in realtime, automatically? | No, but you could run it in a nightly cron job. | Yes! |
| Works on mobile? | No | Yes, if you connect your mobile device to a proxy server running Discordless's proxy server (Wumpus In The Middle) |
| Slows down Discord? | No; it's not running all the time. | Yes. Discord traffic must be processed through Wumpus In The Middle, which adds latency. |
| Disk space usage | Uses less space. Saves the exports and nothing else. | Uses more space; see above. My usage runs about 70mb per day. |
| Export to HTML? | Yes | Sorta; some features missing |
| Export to JSON? | Yes | Yes, following DiscordChatExporter's (undocumented) JSON format for compatibility with **DiscordChatExporter-frontend**. Some features WIP. |
| "Archival grade"? | No, but this probably doesn't matter for most people. | Yes; records all data received by the Discord API, allowing exporter updates to be backported to old data. Can track stuff like message edits and deletions. See also: [Discard](https://github.com/Sanqui/discard), [Discard2](https://github.com/Sanqui/discard2), and [DiscordLogEverything](https://github.com/LostXOR/DiscordLogEverything). |




# Other notes

## How to get the Discord desktop app to trust your mitmproxy certificate
For me, the usual mitmproxy workflow of [installing a mitmproxy root certificate on an operating system level](https://docs.mitmproxy.org/stable/concepts-certificates/) worked for everything on my computer *except* the Discord desktop app. Discord in browser worked fine, but not the desktop app. I had to add the certificate in Chrome, for some reason, to make the Discord app trust it. This might be an Ubuntu thing.

## Development tips for Wumpus In The Middle

If you want to work on Wumpus In The Middle (the mitmproxy script), then it can be handy to prepare a .flow file for testing purposes. Mitmproxy's .flow files are used to "replay" web traffic. This way, instead of having to open Discord every time you want to test Wumpus In The Middle, you can just record a sample of Discord traffic to a file ("`discord_dump.flow`") and feed that into Wumpus In The Middle every time you test it.

### Part one: record traffic
`mitmproxy -w discord_dump.flow --set stream_large_bodies=100k --allow-hosts '^(((.+\.)?discord\.com)|((.+\.)?discordapp\.com)|((.+\.)?discord\.net)|((.+\.)?discordapp\.net)|((.+\.)?discord\.gg))(?::\d+)?$'`
`-w discord_dump.flow` tells mitmproxy to output all the traffic logs to a file named `discord_dump.flow`. This clobbers any existing file at that path.

Once you start recording, do some stuff on Discord. Scroll through channels, send messages, that sort of thing. You may want to restart your Discord client, and disable cache if you're using in-browser Discord, to make sure you re-fetch assets.

### Part two: parse traffic
`mitmdump -s wumpus_in_the_middle.py --rfile discord_dump.flow`
This replays the flow to Wumpus In The Middle. It should archive the traffic in `traffic_archive`. Then you can run one of the exporter scripts as normal.

## To do

Some features of the JSON export are incomplete. Namely:
- reactions
- stickers
- emojos ("Custom Emoji")

However, Wumpus In The Middle still archives this data, so any enhancements to the exporter scripts to include these features will be backwards-compatible with existing traffic archives.


![The "programmer art" logo for Discordless, depicting Discord's Clyde mascot as a corded phone with its cord cut.](doc_images/logo.png)
