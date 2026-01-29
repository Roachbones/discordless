import argparse

"""
Utilities to register discordless exporter backends.

This file is separate from exporter.py to avoid circular dependencies.
"""

parser = argparse.ArgumentParser()
subparsers = parser.add_subparsers(required=True, title="Available Exporters", metavar="<exporter backend>")


def register_exporter(name: str, exporter_args, description: str = ""):
    def discordless_exporter_decorator(func):
        backend_name = f"{name}-exporter"
        subcommand_parser = subparsers.add_parser(
            # subcommand name
            backend_name,

            # help screen options
            help=f"Use the {backend_name} exporter backend",
            description=description,

            # options to get the decorator trick working
            parents=[exporter_args],
            add_help=False,
        )
        subcommand_parser.set_defaults(func=func)

    return discordless_exporter_decorator


def parse_args_and_run():
    args = parser.parse_args()
    args.func(args)
