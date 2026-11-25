"""Own encoder for the file-session initialization observed in the client SDK.

Source boundary: native client library static instructions, summarized in
docs/IMPLEMENTATION.md. This is authentication and read-only capability
negotiation, not an OTA installer, shell or arbitrary filesystem interface.
"""
import struct

MAGIC=0x12345678


def authorization(identity: str, owner_secret: str, request_id: int = 1) -> bytes:
    identity_bytes=identity.encode('utf-8')
    secret_bytes=owner_secret.encode('utf-8')
    if not 1<=len(identity_bytes)<=31 or not 1<=len(secret_bytes)<=63:
        raise ValueError('Authentication fields outside observed bounds')
    if b'\0' in identity_bytes or b'\0' in secret_bytes or not 0<=request_id<=65535:
        raise ValueError('Invalid authentication fields')
    return struct.pack('<II32s64s',MAGIC,request_id,identity_bytes,secret_bytes)


def control_request(request_id: int, service: int, operation: int, payload: bytes) -> bytes:
    if not 0<=request_id<=0xffffffff or not 0<=service<=65535 or not 0<=operation<=65535:
        raise ValueError('Invalid control fields')
    if len(payload)>4096:raise ValueError('Control payload exceeds limit')
    return struct.pack('<IIIHHI',MAGIC,request_id,0,service,operation,len(payload))+payload


def negotiate_protocol() -> bytes:
    return control_request(0,10,0,struct.pack('<I',65536))


def sweeper_query(request_id: int = 2) -> bytes:
    """Observed read-only album listing, without arbitrary file paths."""
    return control_request(request_id, 100, 12,
                           struct.pack('<I112s', 0xffffffff, b'ipc_sweeper_robot'))


def sweeper_stream(request_id: int = 65539) -> bytes:
    """Read the three standard map/route streams on channel five."""
    payload = struct.pack('<II48sII48s48s48s', 5, 0, b'ipc_sweeper_robot', 0, 3,
                          b'map.bin.stream', b'cleanPath.bin.stream', b'navPath.bin.stream')
    return control_request(request_id, 100, 13, payload)


def sweeper_cancel(request_id: int = 4) -> bytes:
    return control_request(request_id, 100, 13, struct.pack('<II64s', 0, 4, b''))
