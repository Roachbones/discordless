import time


class MetricsReport:
    def __init__(self):
        self.fp = None
        self.maxrss: int = 0
        self.runtime: float = 0
        self.guild_count: int = 0
        self.channel_count: int = 0
        self.unknown_guild_count: int = 0
        self.attachment_count: int = 0
        self.latest_request_timestamp: float = 0
        self.latest_gateway_timestamp: float = 0

    def write(self, file: str):
        with open(file, "w") as f:
            self.fp = f

            self.write_metric(f"discordless_htmeml_export_time","counter", int(time.time()), "time of the last successful export")
            self.write_metric(f"discordless_htmeml_export_maxrss", "gauge", self.maxrss, "maxrss in bytes")
            self.write_metric(f"discordless_htmeml_export_runtime", "gauge", self.runtime, "runtime in seconds of last export")
            self.write_metric(f"discordless_htmeml_export_unknown_guilds", "gauge", self.unknown_guild_count, "number of unknown guilds")
            self.write_metric(f"discordless_htmeml_export_guilds", "gauge", self.guild_count, "number of guilds")
            self.write_metric(f"discordless_htmeml_export_channels", "gauge", self.channel_count, "number of channels")
            self.write_metric(f"discordless_htmeml_last_request_time", "counter", self.latest_request_timestamp, "time of the last recorded request")
            self.write_metric(f"discordless_htmeml_last_gateway_time", "counter", self.latest_gateway_timestamp, "time of the last recorded gateway")
            self.write_metric(f"discordless_htmeml_attachments", "gauge", self.attachment_count, "number of attachments")

    def write_metric(self, name: str, metric_type: str, value: int | float, description: str):
        if isinstance(value, int):
            value = str(value)
        elif isinstance(value, float):
            value = f"{value:.2f}"

        self.fp.write(f"# HELP {name} {description}\n")
        self.fp.write(f"# TYPE {name} {metric_type}\n")
        self.fp.write(f"{name} {value}\n\n")