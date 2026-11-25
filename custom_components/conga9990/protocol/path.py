"""Bounded parser of the public Tuya 13-byte path header and points."""
import struct

from .lz4_block import decompress_block


def decode_path(data: bytes):
    if len(data) < 13 or data[0] not in (0, 1, 2, 3):
        raise ValueError("Unsupported path header")
    version, path_id, initial, kind, count, angle, compressed = struct.unpack_from(">BHBBIHH", data)
    if not 0 <= count <= 16384 or initial not in (0, 1) or (count == 0 and compressed):
        raise ValueError("Invalid path bounds")
    if compressed:
        if len(data) != 13 + compressed:
            raise ValueError("Compressed path length mismatch")
        body = decompress_block(data[13:], max_output=count * 4)
    else:
        body = data[13:]
    if len(body) != count * 4:
        raise ValueError("Path point count mismatch")
    def signed(value):
        return value - 65535 if value > 32767 else value
    points = [(signed(x & 0xfffe) / 10, -signed(y & 0xfffe) / 10)
              for x, y in struct.iter_unpack(">HH", body)]
    return {"path_id": path_id, "initial": bool(initial), "angle": angle, "points": points}
