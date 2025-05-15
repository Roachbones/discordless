The format of the traffic_archive data is taken from the [discordless](https://github.com/Roachbones/discordless)
project, on which this project builds on.
The data formats of both this project and discordless are 100% compatible.

The traffic archive data is organized the following:

## High-Level Structure

- All data is stored in a directory and its subdirectories. This directory shall be called the traffic archive
  directory.
- Inside the traffic archive directory, there is a `request_index` text file that contains an entry for each
  intercepted HTTP request.
- The content of intercepted HTTP calls are stored in files in the `requests` subdirectory.
- There is also a `gateway_index` file for all intercepted websocket "gateway" traffic.
- The content of gateway messages are stored in files in the `gateways` subdirectory.

## HTTP Request Archive
TODO

## Gateway Message Archive
TODO

Historically, discord has used different compressions schemes. Some gateway messages are encoded with zlib, while 
newer messages are compressed with zstd.