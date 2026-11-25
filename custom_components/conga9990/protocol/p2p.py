"""Independent decoder for the authenticated UDP profile observed in captures.

Research only: does not negotiate ICE, send traffic, or implement a KCP sender.
The key is the 16-byte hex-decoded aes-key carried by authenticated signaling.
"""

from dataclasses import dataclass
import hashlib
import hmac
import struct

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

KCP_HEADER = struct.Struct('<IBBHIIII')


class P2PFormatError(ValueError):
    """Packet integrity or the observed payload format is invalid."""


@dataclass(frozen=True)
class Segment:
    conversation: int
    command: int
    fragment: int
    window: int
    timestamp: int
    sequence: int
    unacknowledged: int
    payload: bytes


def encode_datagram(segment: Segment, key: bytes) -> bytes:
    """Encode a small observed KCP data/ACK profile with fresh CBC IV."""
    import os
    if len(key) != 16 or segment.command not in (81, 82):
        raise ValueError('Invalid key or unobserved command')
    if len(segment.payload) > 4096 or (segment.command == 82 and segment.payload):
        raise ValueError('Invalid research packet payload')
    if segment.command == 81:
        if not segment.payload:
            raise ValueError('Data packet requires payload')
        padder = padding.PKCS7(128).padder()
        padded = padder.update(segment.payload) + padder.finalize()
        iv = os.urandom(16)
        encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
        body = iv + encryptor.update(padded) + encryptor.finalize()
    else:
        body = b''
    header = KCP_HEADER.pack(segment.conversation, segment.command,
                             segment.fragment, segment.window, segment.timestamp,
                             segment.sequence, segment.unacknowledged, len(body))
    packet = header + body
    return packet + hmac.new(key, packet, hashlib.sha1).digest()


def decode_datagram(packet: bytes, key: bytes) -> Segment:
    """Verify HMAC before decoding CBC; ACK packets have no encrypted body."""
    if len(key) != 16:
        raise ValueError('Expected a 16-byte session key')
    if not 44 <= len(packet) <= 65507:
        raise P2PFormatError('Invalid UDP packet size')
    if not hmac.compare_digest(hmac.new(key, packet[:-20], hashlib.sha1).digest(), packet[-20:]):
        raise P2PFormatError('Invalid packet authentication')
    conv, cmd, frag, wnd, ts, sn, una, size = KCP_HEADER.unpack_from(packet)
    if cmd not in (81, 82) or len(packet) != 44 + size:
        raise P2PFormatError('Unsupported command or inconsistent length')
    body = packet[24:-20]
    if not body:
        if cmd != 82:
            raise P2PFormatError('Missing encrypted data')
        plaintext = b''
    else:
        if len(body) < 32 or len(body) % 16:
            raise P2PFormatError('Invalid CBC body size')
        decryptor = Cipher(algorithms.AES(key), modes.CBC(body[:16])).decryptor()
        padded = decryptor.update(body[16:]) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        try:
            plaintext = unpadder.update(padded) + unpadder.finalize()
        except ValueError as exc:
            raise P2PFormatError('Invalid authenticated padding') from exc
    return Segment(conv, cmd, frag, wnd, ts, sn, una, plaintext)


def reconstruct_saved_map(segments: list[Segment], max_size: int = 2 * 1024 * 1024) -> bytes:
    """Reassemble the first complete observed map transfer in conversation 5.

    KCP byte stream contains 80-byte file headers followed by size bytes.
    This narrow profile rejects gaps, differing duplicates, and unknown headers.
    """
    chunks = {}
    for segment in segments:
        if segment.conversation != 5 or segment.command != 81:
            continue
        if segment.sequence in chunks and chunks[segment.sequence] != segment.payload:
            raise P2PFormatError('Conflicting sequence data')
        chunks[segment.sequence] = segment.payload
    if not chunks or min(chunks) != 0:
        raise P2PFormatError('Missing beginning of map stream')
    contiguous = []
    for sequence in range(len(chunks)):
        if sequence not in chunks:
            raise P2PFormatError('Gap in map stream')
        contiguous.append(chunks[sequence])
    if sum(map(len, contiguous)) > max_size * 16:
        raise P2PFormatError('Captured stream exceeds size limit')
    stream = b''.join(contiguous)
    offset = 0
    result = bytearray()
    expected_index = 0
    total = None
    while offset + 80 <= len(stream):
        header = stream[offset:offset + 80]
        version, kind, profile, index, channel = struct.unpack_from('<5I', header)
        size, file_size, final = struct.unpack_from('<3I', header, 68)
        if (version, kind, profile) != (1, 1000, 65539) or channel not in (2, 3):
            raise P2PFormatError('Unobserved file header')
        if header[20:68].split(b'\0', 1)[0] != b'map.bin.stream':
            raise P2PFormatError('Not the observed map file')
        if index != expected_index or not 0 < size <= file_size <= max_size or final not in (0, 1):
            raise P2PFormatError('Invalid file chunk bounds or order')
        if total is not None and total != file_size:
            raise P2PFormatError('Changing file length')
        total = file_size
        end = offset + 80 + size
        if end > len(stream) or len(result) + size > total:
            raise P2PFormatError('Truncated or excessive file chunk')
        result.extend(stream[offset + 80:end])
        offset = end
        expected_index += 1
        if final:
            if len(result) != total:
                raise P2PFormatError('Incomplete final chunk')
            return bytes(result)
    raise P2PFormatError('No complete map transfer')
