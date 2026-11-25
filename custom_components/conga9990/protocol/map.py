"""Decoder for the observed Conga 9990 map profile.

Version 2 metadata and room records follow Tuya's public robot protocol.
No source map or household-specific fingerprint is included in this package.
"""

from dataclasses import dataclass
import struct
import zlib
import hashlib

from .lz4_block import LZ4DecodeError, decompress_block


class MapFormatError(ValueError):
    """The input does not match the observed map profile."""


@dataclass(frozen=True)
class MapGrid:
    width: int
    height: int
    cells: bytes
    header: bytes
    trailer: bytes
    rooms: tuple = ()

    @property
    def map_id(self):
        return int.from_bytes(self.header[1:3], "big")

    @property
    def resolution(self):
        return int.from_bytes(self.header[12:14], "big") / 100

    @property
    def origin(self):
        return (int.from_bytes(self.header[8:10], "big") / 10,
                int.from_bytes(self.header[10:12], "big") / 10)

    @property
    def stable(self):
        return self.header[3] == 1

    @property
    def signature(self):
        return hashlib.sha256(self.header[1:3] + self.header[4:14]).hexdigest()[:16]

    def pixel_to_robot(self, x, y, *, traversable=True):
        import math
        if (isinstance(x, bool) or isinstance(y, bool)
                or not isinstance(x, (int, float)) or not isinstance(y, (int, float))
                or not math.isfinite(x) or not math.isfinite(y)
                or not 0 <= x < self.width or not 0 <= y < self.height
                or not self.resolution):
            raise MapFormatError("Point is outside the calibrated map")
        if traversable and self.cells[int(y) * self.width + int(x)] & 7 not in (2, 7):
            raise MapFormatError("Point is not mapped as traversable")
        # Protocol positions are grid units / 10. Resolution is metres per
        # cell for physical display, not another factor in these coordinates.
        return (x - self.origin[0], y - self.origin[1])


def decode_map(data: bytes, max_cells: int = 4 * 1024 * 1024) -> MapGrid:
    if len(data) <= 24:
        raise MapFormatError("Missing header or LZ4 data")
    if data[0] != 2:
        raise MapFormatError("Only the observed version byte 2 is supported")
    width, declared_height = struct.unpack_from(">HH", data, 4)
    if not 1 <= width <= 4096:
        raise MapFormatError("Invalid width in observed header position")
    if not 1 <= max_cells <= 16 * 1024 * 1024:
        raise ValueError("max_cells must be between 1 and 16 MiB")
    try:
        decoded = decompress_block(data[24:], max_output=max_cells + 100 * 1024)
    except (LZ4DecodeError, ValueError, OverflowError) as exc:
        raise MapFormatError("Invalid or oversized LZ4 block") from exc
    cell_count = width * declared_height
    if not declared_height or cell_count > max_cells or len(decoded) < cell_count + 2:
        raise MapFormatError("Invalid map height or truncated room metadata")
    if int.from_bytes(data[18:22], "big") != len(decoded) or int.from_bytes(data[22:24], "big") != len(data) - 24:
        raise MapFormatError("Map length metadata mismatch")
    cells, trailer = decoded[:cell_count], decoded[cell_count:]
    if trailer[0] != 1:
        raise MapFormatError("Unknown room metadata version")
    rooms = []
    offset = 2
    for _ in range(trailer[1]):
        if offset + 47 > len(trailer):
            raise MapFormatError("Truncated room record")
        record = trailer[offset:offset + 47]
        room_id = int.from_bytes(record[:2], "big")
        name_length, vertices = record[26], record[46]
        if room_id > 27 or name_length > 19 or vertices > 64:
            raise MapFormatError("Invalid room record")
        end = offset + 47 + vertices * 4
        if end > len(trailer):
            raise MapFormatError("Truncated room vertices")
        try:
            name = record[27:27 + name_length].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MapFormatError("Invalid room name") from exc
        rooms.append({"id": room_id, "name": name or f"Room {room_id}"})
        offset = end
    if offset != len(trailer) or len({room['id'] for room in rooms}) != len(rooms):
        raise MapFormatError("Inconsistent room metadata")
    if len(cells) > max_cells or len(cells) % width:
        raise MapFormatError("Decoded cell count does not match width")
    height = len(cells) // width
    if not 1 <= height <= 4096:
        raise MapFormatError("Invalid inferred grid height")
    if any(value & 7 not in (0, 1, 2, 7) for value in cells):
        raise MapFormatError("Unsupported cell type")
    return MapGrid(width, height, cells, data[:24], trailer, tuple(rooms))


def make_png(width: int, height: int, cells: bytes, scale: int = 4) -> bytes:
    """Render grid data using a presentation palette, without screenshot input."""
    if not 1 <= scale <= 16 or width * height != len(cells):
        raise ValueError("Invalid render dimensions or scale")
    colors = (b"\x80\xcb\xc4", b"\xff\xcc\x80", b"\xb3\x9d\xdb", b"\x90\xca\xf9",
              b"\xef\x9a\x9a", b"\xc5\xe1\xa5", b"\xff\xf5\x9d", b"\xce\x93\xd8")
    def color(value):
        kind, room = value & 7, value >> 3
        if kind == 0: return b"\x06\x1b\x20"
        if kind == 1: return b"\xff\xff\xff"
        if kind in (2, 7): return colors[room % len(colors)] if room <= 27 else b"\xc9\xcd\xcf"
        raise ValueError("Unsupported map cell")
    palette = {value: color(value) for value in set(cells)}
    raw = bytearray()
    for y in range(height):
        row = b"\x00" + b"".join(palette[value] * scale for value in cells[y * width:(y + 1) * width])
        raw.extend(row * scale)

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)

    return b"\x89PNG\r\n\x1a\n" + b"".join([
        chunk(b"IHDR", struct.pack(">IIBBBBB", width * scale, height * scale, 8, 2, 0, 0, 0)),
        chunk(b"IDAT", zlib.compress(raw)), chunk(b"IEND", b""),
    ])
