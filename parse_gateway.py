"""
Parses Discord's zlib-encoded Gateway/websocket messages.
Currently only recognizes two URLs because those are the only ones I've seen in practice.
Let me know if you see others.

todo: https://gateway-us-east1-d.discord.gg/?encoding=json&v=9&compress=zlib-stream ??

"""

import zlib
import pyzstd
import json
import erlpack
import urllib.parse

"""
Decodes the query part of a url and converts it to a dict
"""
def decode_querystring(querystring: str) -> dict[str, str]:
    data = urllib.parse.parse_qs(querystring, keep_blank_values=True)
    result = {}
    for key, value in data.items():
        if len(value) != 1:
            print(f"query parameter '{key}' has been specified multiple times")
            continue
        result[key] = value[0]
    return result

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
    # parse query string for parameters
    querystring = urllib.parse.urlparse(url).query
    query = decode_querystring(querystring)

    # buffer to store the data
    buffer = bytearray()

    # get compression scheme from query
    if "compress" not in query:
        print(f"discord websocket querystring doesn't contain a compression scheme: {querystring}")
        return
    compression_scheme = query["compress"]
    is_zlib = compression_scheme == "zlib-stream"
    is_zstd = compression_scheme == "zstd-stream"
    decompressor = None
    if is_zlib:
        decompressor = zlib.decompressobj()
    elif is_zstd:
        decompressor = pyzstd.ZstdDecompressor()
    if decompressor is None:
        print(f"discord websocket traffic is encoded in an unsupported compression scheme: '{compression_scheme}'")
        return

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

            # some form of zlib integrity checking
            if is_zlib and not buffer.endswith(b'\x00\x00\xff\xff'):
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

            if "encoding" not in query:
                print(f"discord websocket querystring doesn't contain a encoding scheme: {querystring}")
                return

            if query["encoding"] == "json":
                payload = json.loads(payload.decode())
            elif query["encoding"] == "etf":
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






