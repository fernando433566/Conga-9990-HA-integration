"""Own bounded encoding of the Conga panel's combined cleaning commands.

Wire format cross-checked against this robot's authenticated DP15 reports.
Coordinates use the public protocol's modulo-65535 representation, not int16.
The 0x58/0x60/0x62 field layout comes from static original-panel analysis;
no original implementation is bundled or executed by this integration.
"""
import base64
import math
import struct
from decimal import Decimal, ROUND_HALF_UP


def command(code: int, payload: bytes = b"") -> str:
    if not 0 <= code <= 255 or len(payload) > 119:
        raise ValueError("Command exceeds the robot's 128-byte limit")
    body = bytes([code]) + payload
    wire = b"\xaa\x01" + struct.pack(">I", len(body)) + body + bytes([sum(body) & 255])
    return base64.b64encode(wire).decode()


def decode_command(value: str) -> tuple[int, bytes]:
    try:
        wire = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid raw command") from exc
    if (len(wire) < 8 or len(wire) > 128 or wire[:2] != b"\xaa\x01"
            or int.from_bytes(wire[2:6], "big") != len(wire) - 7
            or sum(wire[6:-1]) & 255 != wire[-1]):
        raise ValueError("Invalid command header, length or checksum")
    return wire[6], wire[7:-1]


def coordinate(value: float) -> bytes:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Coordinate must be finite")
    if abs(value) > 3276.8:
        raise ValueError("Coordinate outside supported bounds")
    # Match the public encoder's Number.toFixed(1), including negative ties
    # and the exact binary value represented by the input float.
    raw = int(Decimal.from_float(float(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP) * 10)
    if not -32767 <= raw <= 32767:
        raise ValueError("Coordinate outside supported bounds")
    return struct.pack(">H", raw % 65535)


def settings(repeats=1, fan_speed="normal", clean_pattern="auto", water_level="close",
             carpet_boost=False, y_mop=False):
    if type(repeats) is not int or not 1 <= repeats <= 3:
        raise ValueError("Repetitions must be between one and three")
    patterns = {"auto": 1, "thorough": 2, "border": 3, "scrub": 4,
                "spiral": 5, "square_spiral": 6, "quiet": 18}
    fans = {"close": 0, "gentle": 1, "normal": 2, "strong": 3}
    water = {"close": 0, "low": 1, "middle": 2, "high": 3}
    if (fan_speed not in fans or clean_pattern not in patterns or water_level not in water
            or type(carpet_boost) is not bool or type(y_mop) is not bool):
        raise ValueError("Unsupported combined cleaning settings")
    return bytes([patterns[clean_pattern], repeats, fans[fan_speed], water[water_level],
                  int(carpet_boost), int(y_mop)])


def room_command(room_ids: list[int], repeats: int = 1, **options) -> str:
    if (not room_ids or len(room_ids) > 24 or len(set(room_ids)) != len(room_ids)
            or any(type(room) is not int or not 0 <= room <= 27 for room in room_ids)):
        raise ValueError("Select one to 24 distinct mapped rooms")
    return command(0x58, bytes([1, len(room_ids), *room_ids]) + settings(repeats, **options))


def spot_command(x: float, y: float, repeats: int = 1, **options) -> str:
    return command(0x60, bytes([1]) + coordinate(x) + coordinate(-y) + settings(repeats, **options))


def zone_command(zones: list[list[list[float]]], repeats: int = 1, **options) -> str:
    if not 1 <= len(zones) <= 3:
        raise ValueError("Select one to three rectangles within the 128-byte limit")
    body = bytearray()
    for points in zones:
        if len(points) != 4 or any(len(point) != 2 for point in points):
            raise ValueError("A zone requires four coordinate pairs")
        xs, ys = {point[0] for point in points}, {point[1] for point in points}
        if len(xs) != 2 or len(ys) != 2 or len({tuple(point) for point in points}) != 4:
            raise ValueError("Zone must be a non-empty rectangle")
        x0, x1 = sorted(xs); y0, y1 = sorted(ys)
        body.append(4)
        for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            body.extend(coordinate(x)); body.extend(coordinate(-y))
        body.extend(bytes(20))  # Empty optional name: length byte + 19-byte field.
    return command(0x62, bytes(body) + settings(repeats, **options))


def validate_profile(profile: dict) -> dict:
    """Accept named selections, never an implicit whole-house fallback."""
    allowed = {"room_ids", "zones", "repeats", "fan_speed", "map_id", "map_signature",
               "clean_pattern", "water_level", "carpet_boost", "y_mop"}
    if not isinstance(profile, dict) or set(profile) - allowed:
        raise ValueError("Unknown profile fields")
    rooms, zones = profile.get("room_ids"), profile.get("zones")
    if bool(rooms) == bool(zones):
        raise ValueError("A profile must select either rooms or zones")
    repeats = profile.get("repeats", 1)
    options = {key: profile[key] for key in ("fan_speed", "clean_pattern", "water_level", "carpet_boost", "y_mop") if key in profile}
    if rooms:
        room_command(rooms, repeats, **options)
    else:
        zone_command(zones, repeats, **options)
    if type(profile.get("map_id")) is not int or not 0 <= profile["map_id"] <= 65535:
        raise ValueError("Profile must identify its map")
    return dict(profile)


def resolve_profile_name(name, names):
    if not isinstance(name,str):
        return None
    text = ' '.join(name.split()).casefold()
    candidates = [text]
    for prefix in ('el perfil ','el ','la '):
        if text.startswith(prefix): candidates.append(text[len(prefix):])
    for candidate in candidates:
        matches = [key for key in names if key.casefold()==candidate]
        if len(matches)==1: return matches[0]
    return None
