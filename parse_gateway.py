"""
Parses Discord's zlib-encoded Gateway/websocket messages.
Currently only recognizes two URLs because those are the only ones I've seen in practice.
Let me know if you see others.

todo: https://gateway-us-east1-d.discord.gg/?encoding=json&v=9&compress=zlib-stream ??

"""

import zlib
import json
import erlpack
import urllib.parse

"""
Recursively convert the bytes and Atom objects in a Gateway payload to strings.
"""
def deserialize_erlpackage(payload):
    if isinstance(payload, bytes):
        return payload.decode()
    elif isinstance(payload, erlpack.Atom):
        return str(payload)
    elif isinstance(payload, list):
        return [deserialize_erlpackage(i) for i in payload]
    elif isinstance(payload, dict):
        deserialized = {}
        for k, v in payload.items():
            deserialized[deserialize_erlpackage(k)] = deserialize_erlpackage(v)
        return deserialized
    else:
        return payload

"""
Yields deserialized Gateway payloads for a single archived Gateway connection.
"""
def parse_gateway(gateway_path_prefix, url):
    querystring = urllib.parse.urlparse(url).query
    decompressor = zlib.decompressobj()
    buffer = bytearray()
    with open(gateway_path_prefix + "_data", "rb") as data_file, open(gateway_path_prefix + "_timeline") as timeline_file:
        for line in timeline_file:
            try:
                timestamp, length = line.split(" ")
            except ValueError:
                print(f"Improper line in timeline:\n{line}")
                continue
            timestamp, length = float(timestamp), int(length)

            chunk = data_file.read(length)
            buffer.extend(chunk)

            if not chunk:
                print("Incomplete gateway.")
                return
            if not buffer.endswith(b'\x00\x00\xff\xff'):
                continue
            
            try:
                payload = decompressor.decompress(buffer)
            except:
                print(
                    "Error decompressing message for Gateway {}.".format(gateway_path_prefix)
                    + " This can happen if WitM restarts in the middle of a Gateway connection."
                    + " Skipping the rest of this Gateway."
                )
                return
            
            buffer = bytearray()

            if querystring == "encoding=json&v=9&compress=zlib-stream":
                payload = json.loads(payload.decode())
            elif querystring == "encoding=etf&v=9&compress=zlib-stream":
                payload = deserialize_erlpackage(erlpack.unpack(payload))
            else:
                assert 0, "Unrecognized querystring "+querystring+", did Discord upgrade its API version?"

            yield payload
            
if __name__ == "__main__":
    with open("traffic_archive/gateway_index") as file:
        for line in file:
            url, gateway_name_prefix = line.strip().split(" ")[1:]
            print("reading", "traffic_archive/gateways/" + gateway_name_prefix, url)
            
            for i in parse_gateway("traffic_archive/gateways/" + gateway_name_prefix, url):
                print("Payload of type {} and length {}.".format(i["t"], len(str(i))))
            





