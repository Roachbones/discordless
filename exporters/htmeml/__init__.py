import argparse
import logging
import sys

from .web_exporter import htmeml_exporter_main
from .. import registry

# arguments specific to the HTMemL exporter
parser = argparse.ArgumentParser()
parser.add_argument("-t", "--traffic_archive", default="traffic_archive", help="The directory containing the traffic recordings that should be converted. Defaults to \"traffic_archive\"", metavar="<traffic_archive>")
parser.add_argument("-o", "--out_dir", default="web_exports", help="The directory to export the HTML files. Defaults to \"web_exports\"", metavar="<out_dir>")
parser.add_argument("--limit-guilds", help="Limit the export to the following guild IDs", metavar="<guild id>", action="append", nargs="+")
parser.add_argument("--metrics-file", help="Export a prometheus metrics file", metavar="<metrics file>")

# register the HTMemL exporter
@registry.register_exporter("htmeml",parser, description="Memory-optimized HTML converter with a focus on exports for public archives.")
def htmeml_exporter_backend(args):
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(levelname)s: %(message)s")

    htmeml_exporter_main(args)