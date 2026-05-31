"""
Wrapper script to invoke different exporter backends from one script.

How to register a new backend:
- create a new directory in exporters
- add the code below to a file called __init__.py in your new directory
- import exporters.mydirectory in this file


from .. import registry
import argparse

uwu_parser = argparse.ArgumentParser()
uwu_parser.add_argument("-g","--giggle",action='store_true')
@registry.register_exporter("uwu",uwu_parser)
def uwu_exporter(args):
    print("Successfully registered an exporter. UwU. giggle =", args.giggle)
"""

import logging
import sys

# noinspection PyUnusedImports
import exporters.html, exporters.dcejson, exporters.htmeml

import exporters.registry as exporter_registry

if __name__ == "__main__":
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(levelname)s: %(message)s")
    exporter_registry.parse_args_and_run()
