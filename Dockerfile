FROM mitmproxy/mitmproxy:12.1.2

WORKDIR /app
RUN apt-get update &&\
    apt-get install -y g++ &&\
    pip install python-dateutil pyzstd filetype erlpack
COPY . .

EXPOSE 8080
CMD mitmdump -s wumpus_in_the_middle.py --listen-port=8080 --set console_eventlog_verbosity=debug --allow-hosts '^(((.+\.)?discord\.com)|((.+\.)?discordapp\.com)|((.+\.)?discord\.net)|((.+\.)?discordapp\.net)|((.+\.)?discord\.gg))(?::\d+)?$'