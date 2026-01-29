from .. import registry
import argparse

arg_parser = argparse.ArgumentParser()
arg_parser.add_argument("-d","--dry",action='store_true', help="perform a dry run without actually writing any files")
arg_parser.add_argument("-t","--traffic-archive", default="traffic_archive/", help="The traffic archive directory used for this conversion. Per default 'traffic_archive/'", metavar="<dir>")
arg_parser.add_argument("-o","--output", default="html_exports/", help="The directory to export the output into. Per default 'html_exports/'", metavar="<dir>")
arg_parser.add_argument('--channel-id-dirs', default=False, help="Name channel directories in the form channel_{channel id}", action='store_true')

@registry.register_exporter("html",arg_parser, description="Convert discordless traffic archives to HTML files.")
def html_exporter(args):
    print("hi from the html exporter")