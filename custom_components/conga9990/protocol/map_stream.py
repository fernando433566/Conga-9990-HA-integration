"""Own bounded reassembly of the observed map/route streaming file frames."""
from dataclasses import dataclass
import struct

from .p2p import P2PFormatError

NAMES = {b'map.bin.stream', b'cleanPath.bin.stream', b'navPath.bin.stream'}


@dataclass(frozen=True)
class MapFile:
    name: str
    data: bytes


class MapStream:
    def __init__(self, request_id=65539, max_size=2 * 1024 * 1024):
        if not 1 <= max_size <= 4 * 1024 * 1024:
            raise ValueError('Invalid map stream limit')
        self.request_id = request_id
        self.max_size = max_size
        self.next_sequence = 0
        self.pending = {}
        self.recent = {}
        self.buffer = bytearray()
        self.next_index = 0
        self.active = None
        self.contents = bytearray()
        self.total = None

    def feed(self, segment):
        if segment.conversation != 5 or segment.command != 81:
            return []
        sequence = segment.sequence
        if sequence < self.next_sequence:
            if sequence in self.recent and self.recent[sequence] != segment.payload:
                raise P2PFormatError('Conflicting stream retransmission')
            return []
        if sequence - self.next_sequence > 128:
            raise P2PFormatError('Stream gap exceeds bounded receive window')
        if len(segment.payload) > 65536:
            raise P2PFormatError('Oversized stream segment')
        if sequence in self.pending and self.pending[sequence] != segment.payload:
            raise P2PFormatError('Conflicting pending stream segment')
        self.pending[sequence] = segment.payload
        if sum(map(len,self.pending.values())) > self.max_size + 65536:
            raise P2PFormatError('Pending stream exceeds bound')
        while self.next_sequence in self.pending:
            payload = self.pending.pop(self.next_sequence)
            self.recent[self.next_sequence] = payload
            self.buffer.extend(payload)
            self.next_sequence += 1
        self.recent = {k:v for k,v in self.recent.items() if k >= self.next_sequence - 128}
        if len(self.buffer) > self.max_size + 65536:
            raise P2PFormatError('Stream buffer exceeds bound')
        updates = []
        while len(self.buffer) >= 80:
            version, kind, request, index, count = struct.unpack_from('<5I',self.buffer)
            name = bytes(self.buffer[20:68]).split(b'\0',1)[0]
            size,total,final = struct.unpack_from('<3I',self.buffer,68)
            if ((version,kind,request) != (1,1000,self.request_id) or count not in (2,3)
                    or name not in NAMES or index != self.next_index or final not in (0,1)
                    or not 0 <= size <= min(total,65536) or total > self.max_size):
                raise P2PFormatError('Invalid observed map/route frame')
            if len(self.buffer) < 80 + size:
                break
            if self.active is None:
                self.active,self.total = name,total
            if self.active != name or self.total != total or len(self.contents)+size > total:
                raise P2PFormatError('Inconsistent file chunk sequence')
            self.contents.extend(self.buffer[80:80+size])
            del self.buffer[:80+size]
            self.next_index += 1
            if final:
                if len(self.contents) != total:
                    raise P2PFormatError('Incomplete final map/route file')
                updates.append(MapFile(name.decode('ascii'),bytes(self.contents)))
                self.contents.clear()
                self.active,self.total = None,None
        return updates
