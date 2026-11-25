"""Independent authenticated local client, verified against captured handshakes."""

import asyncio
import hashlib
import hmac
import itertools
import json
import os
import struct
import time

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .envelope import HEADER, PREFIX, SUFFIX


class LocalProtocolError(Exception):
    """Authentication, framing or peer data validation failed."""


def encrypt_message(key: bytes, counter: int, command: int, plaintext: bytes, nonce: bytes | None = None) -> bytes:
    nonce = os.urandom(12) if nonce is None else nonce
    if len(nonce) != 12:
        raise ValueError("AES-GCM nonce must be 12 bytes")
    header = HEADER.pack(PREFIX, 0, counter & 0xFFFFFFFF, command, len(plaintext) + 28)
    return header + nonce + AESGCM(key).encrypt(nonce, plaintext, header[4:]) + SUFFIX


def decrypt_message(key: bytes, message: bytes) -> tuple[int, bytes]:
    if len(message) < 50:
        raise LocalProtocolError("Truncated encrypted envelope")
    prefix, reserved, counter, command, length = HEADER.unpack_from(message)
    if prefix != PREFIX or length < 28 or length > 1024 * 1024:
        raise LocalProtocolError("Invalid encrypted envelope header")
    if len(message) != HEADER.size + length + 4 or message[-4:] != SUFFIX:
        raise LocalProtocolError("Invalid encrypted envelope length or suffix")
    try:
        plaintext = AESGCM(key).decrypt(message[18:30], message[30:-4], message[4:18])
    except InvalidTag as exc:
        raise LocalProtocolError("Message authentication failed") from exc
    return command, plaintext


def derive_session_key(local_key: bytes, client_nonce: bytes, robot_nonce: bytes) -> bytes:
    if len(client_nonce) != 16 or len(robot_nonce) != 16:
        raise LocalProtocolError("Invalid handshake nonce length")
    mixed = bytes(a ^ b for a, b in zip(client_nonce, robot_nonce))
    return AESGCM(local_key).encrypt(client_nonce[:12], mixed, None)[:16]


def extract_dps(payload: bytes) -> dict | None:
    if len(payload) < 4:
        raise LocalProtocolError("Missing peer return code")
    if payload[:4] != bytes(4):
        raise LocalProtocolError("Robot returned an error")
    body = payload[4:]
    if body.startswith(b"3.5"):
        if len(body) < 15:
            raise LocalProtocolError("Truncated protocol version prefix")
        body = body[15:]
    if not body:
        return None
    try:
        decoded = json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise LocalProtocolError("Invalid robot JSON") from exc
    if not isinstance(decoded, dict):
        raise LocalProtocolError("Robot JSON must be an object")
    dps = decoded.get("dps")
    if dps is None and isinstance(decoded.get("data"), dict):
        dps = decoded["data"].get("dps")
    if dps is not None and not isinstance(dps, dict):
        raise LocalProtocolError("Data points must be an object")
    return {str(k): v for k, v in dps.items()} if dps is not None else None


class LocalClient:
    """Open a short authenticated session for each query; no app or cloud needed."""

    def __init__(self, host: str, local_key: str, port: int = 6668, timeout: float = 10):
        self.host = host
        self.local_key = local_key.encode()
        if len(self.local_key) != 16:
            raise ValueError("The observed local protocol requires a 16-byte key")
        self.port = port
        self.timeout = timeout

    async def status(self, dp_ids: list[str] | None = None) -> dict:
        body = b"{}" if dp_ids is None else json.dumps({"dps": {str(dp): None for dp in dp_ids}}, separators=(",", ":")).encode()
        return await self._exchange(16, body, 16)

    async def set_dps(self, values: dict) -> None:
        if not values:
            raise ValueError("At least one data point is required")
        body = b"3.5" + bytes(12) + json.dumps(
            {"data": {"dps": {str(k): v for k, v in values.items()}}, "protocol": 5, "t": int(time.time())},
            separators=(",", ":"),
        ).encode()
        await self._exchange(13, body, 13)

    async def listen_map_updates(self, callback, seconds: float = 30) -> None:
        """Request map/path and retain the session for authenticated DP pushes."""
        await self.listen_dps(callback, {"16": "get_both"}, seconds)

    async def listen_dps(self, callback, request_dps: dict, seconds: float = 30) -> None:
        """Retain a bounded authenticated session after its initial DP request."""
        if not 1 <= seconds <= 60:
            raise ValueError("Invalid listening duration")
        body = b"3.5" + bytes(12) + json.dumps(
            {"data": {"dps": request_dps}, "protocol": 5, "t": int(time.time())},
            separators=(",", ":"),
        ).encode()
        await self._exchange(13, body, None, callback=callback, listen_seconds=seconds)

    async def _exchange(self, request_command: int, body: bytes, expected_command: int | None,
                        callback=None, listen_seconds: float | None = None) -> dict:
        async with asyncio.timeout(listen_seconds or self.timeout):
            reader, writer = await asyncio.open_connection(self.host, self.port)
            counter = itertools.count(1)
            key = self.local_key

            async def send(command, body):
                writer.write(encrypt_message(key, next(counter), command, body))
                await writer.drain()

            async def receive():
                header = await reader.readexactly(HEADER.size)
                prefix, _, _, _, length = HEADER.unpack(header)
                if prefix != PREFIX or not 28 <= length <= 1024 * 1024:
                    raise LocalProtocolError("Invalid peer message length")
                body = await reader.readexactly(length + 4)
                return decrypt_message(key, header + body)

            try:
                client_nonce = os.urandom(16)
                await send(3, client_nonce)
                command, reply = await receive()
                if command != 4 or len(reply) != 52 or reply[:4] != bytes(4):
                    raise LocalProtocolError("Unexpected handshake response")
                robot_nonce, proof = reply[4:20], reply[20:]
                expected = hmac.new(self.local_key, client_nonce, hashlib.sha256).digest()
                if not hmac.compare_digest(proof, expected):
                    raise LocalProtocolError("Robot handshake proof failed")
                await send(5, hmac.new(self.local_key, robot_nonce, hashlib.sha256).digest())
                key = derive_session_key(self.local_key, client_nonce, robot_nonce)
                await send(request_command, body)
                for _ in range(1024 if callback else 64):
                    command, payload = await receive()
                    if callback is not None and command == 13:
                        if payload != bytes(4):
                            raise LocalProtocolError("Robot rejected the map/path request")
                        continue
                    if expected_command == 13 and command == 13:
                        if payload != bytes(4):
                            raise LocalProtocolError("Robot did not acknowledge the data-point write")
                        return {}
                    if command in (8, 16):
                        dps = extract_dps(payload)
                        if dps is not None and callback is not None:
                            await callback(dps)
                            continue
                        if dps is not None and expected_command == 16:
                            return dps
                raise LocalProtocolError("No status response received")
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except OSError:
                    pass
