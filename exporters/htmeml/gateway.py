"""
Parses Discord's zlib-encoded Gateway/websocket messages.

TODO: see in how far this can be merged back with the other exporters gateway handling
"""
import logging
import zlib
import pyzstd
import json
import erlpack
import urllib.parse

logger = logging.getLogger(__name__)

"""
Decodes the query part of a url and converts it to a dict
"""
def decode_querystring(querystring: str) -> dict[str, str]:
    data = urllib.parse.parse_qs(querystring, keep_blank_values=True)
    result = {}
    for key, value in data.items():
        if len(value) != 1:
            logger.error(f"decode_querystring: query parameter '{key}' has been specified multiple times")
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
def parse_gateway_recording(gateway_timeline: str, gateway_data: str, url: str):
    # parse query string for parameters
    querystring = urllib.parse.urlparse(url).query
    query = decode_querystring(querystring)

    # buffer to store the data
    buffer = bytearray()

    # get compression scheme from query
    if "compress" not in query:
        logger.error(f"discord websocket querystring doesn't contain a compression scheme: {querystring}")
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
        logger.error(f"discord websocket traffic is encoded in an unsupported compression scheme: '{compression_scheme}'")
        return

    with open(gateway_data, "rb") as data_file, open(gateway_timeline, "r") as timeline_file:
        for line in timeline_file:
            try:
                timestamp, length = line.split(" ")
            except ValueError:
                logger.error(f"Improper line in timeline file '{gateway_timeline}':\n{line}")
                continue
            timestamp, length = float(timestamp), int(length)

            chunk = data_file.read(length)
            buffer.extend(chunk)

            if not chunk:
                logger.error(f"Incomplete gateway in '{gateway_data}'")
                return

            # some form of zlib integrity checking
            if is_zlib and not buffer.endswith(b'\x00\x00\xff\xff'):
                continue

            try:
                payload = decompressor.decompress(buffer)
            except:
                logger.error(
                    "Error decompressing message for Gateway {}.".format(gateway_timeline)
                    + " This can happen if WitM restarts in the middle of a Gateway connection."
                    + " Skipping the rest of this Gateway."
                )
                return
            
            buffer = bytearray()

            if "encoding" not in query:
                logger.error(f"discord websocket querystring doesn't contain a encoding scheme: {querystring}")
                return

            if query["encoding"] == "json":
                payload = json.loads(payload.decode())
            elif query["encoding"] == "etf":
                payload = deserialize_erlpackage(erlpack.unpack(payload))
            else:
                assert 0, "Unrecognized querystring "+querystring+", did Discord upgrade its API version?"

            yield payload






