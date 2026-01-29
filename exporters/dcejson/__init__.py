from .. import registry
import argparse

arg_parser = argparse.ArgumentParser()
arg_parser.add_argument("-d","--dry",action='store_true', help="perform a dry run without actually writing any files")
arg_parser.add_argument("-t","--traffic-archive", default="traffic_archive/", help="The traffic archive directory used for this conversion. Per default 'traffic_archive/'", metavar="<dir>")
arg_parser.add_argument("-o","--output", default="dcejson_exports/", help="The directory to export the output into. Per default 'dcejson_exports/'", metavar="<dir>")
arg_parser.add_argument("--consistent-naming-mode",action='store_true', help="enable consistent naming mode")
arg_parser.add_argument("--max-filename-length",type=int,default=60, help="the maximum filename length for exported files", metavar="<int>")

@registry.register_exporter("dcejson",arg_parser, description="Convert discordless traffic archives to DiscordChatExporter JSON files.")
def dcejson_exporter(args):
    print("hi from the dcejson exporter")