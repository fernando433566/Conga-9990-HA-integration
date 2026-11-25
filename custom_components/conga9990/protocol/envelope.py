"""Structural parser derived from the captured 6699 stream.

This module does not decrypt or authenticate messages. Field names describe
observed behavior; the command values have not been assigned product semantics.
"""

from dataclasses import dataclass
import struct

HEADER = struct.Struct(">IHIII")
PREFIX = 0x6699
SUFFIX = bytes.fromhex("00009966")


@dataclass(frozen=True)
class Envelope:
    reserved: int
    counter: int
    command: int
    payload: bytes


class EnvelopeError(ValueError):
    """A stream fails the observed structural constraints."""


class EnvelopeReader:
    """Accept fragmented/coalesced TCP data in one direction of one connection."""

    def __init__(self, max_payload: int = 1024 * 1024) -> None:
        if max_payload < 0:
            raise ValueError("max_payload must be nonnegative")
        self.max_payload = max_payload
        self._buffer = bytearray()

    @property
    def pending_bytes(self) -> int:
        return len(self._buffer)

    def feed(self, data: bytes) -> list[Envelope]:
        self._buffer.extend(data)
        frames = []
        while len(self._buffer) >= HEADER.size:
            prefix, reserved, counter, command, length = HEADER.unpack_from(self._buffer)
            if prefix != PREFIX:
                raise EnvelopeError("Unexpected prefix; not a complete observed 6699 stream")
            if length > self.max_payload:
                raise EnvelopeError("Declared payload exceeds configured limit")
            total = HEADER.size + length + len(SUFFIX)
            if len(self._buffer) < total:
                break
            if self._buffer[total - len(SUFFIX):total] != SUFFIX:
                raise EnvelopeError("Unexpected suffix")
            payload = bytes(self._buffer[HEADER.size:total - len(SUFFIX)])
            del self._buffer[:total]
            frames.append(Envelope(reserved, counter, command, payload))
        return frames

    def finish(self) -> None:
        if self._buffer:
            raise EnvelopeError(f"Incomplete stream: {len(self._buffer)} bytes remain")
