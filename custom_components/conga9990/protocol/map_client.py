"""Native, owner-authenticated LAN ICE/KCP map streaming. No cloud or Android.

Only the fixed sweeper album and its three standard map/route filenames are
requested. No arbitrary file paths, firmware, motion or camera commands.
"""
import asyncio
import hashlib
import hmac
import itertools
import json
import os
import re
import secrets
import socket
import string
import struct
import time

from .envelope import HEADER, PREFIX
from .local import LocalProtocolError, encrypt_message, decrypt_message, derive_session_key
from .file_session import authorization, sweeper_query, sweeper_stream, sweeper_cancel
from .map_stream import MapStream
from .p2p import Segment, P2PFormatError, decode_datagram, encode_datagram
from .stun import attribute, binding_success, build as build_stun, parse as parse_stun


class MapClient:
    def __init__(self, host, device_id, local_key, owner_uid, file_password_hash):
        if (not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', owner_uid)
                or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', device_id)
                or not re.fullmatch(r'[0-9a-fA-F]{32}', file_password_hash)
                or len(local_key.encode()) != 16):
            raise ValueError('Invalid owner map connection credentials')
        self.host,self.device_id,self.local_key = host,device_id,local_key.encode()
        self.owner_uid,self.file_password_hash = owner_uid,file_password_hash

    async def stream(self, on_file, seconds=120):
        if not 10 <= seconds <= 300:
            raise ValueError('Map session duration outside bounds')
        loop = asyncio.get_running_loop()
        resolved = await loop.getaddrinfo(self.host,6668,family=socket.AF_INET,type=socket.SOCK_DGRAM)
        robot_ip = resolved[0][4][0]
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as probe:
            probe.connect((robot_ip,6668)); local_ip = probe.getsockname()[0]
        udp = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        udp.bind((local_ip,0)); udp.setblocking(False)
        port = udp.getsockname()[1]
        alphabet = string.ascii_letters + string.digits
        local_user = ''.join(secrets.choice(alphabet) for _ in range(4))
        local_password = ''.join(secrets.choice(alphabet) for _ in range(24))
        data_key = os.urandom(16)
        session_id = self.device_id + str(int(time.time())) + secrets.token_hex(4)
        sdp = '\r\n'.join([
            'v=0',f'o=- {int(time.time())} 1 IN IP4 127.0.0.1','s=-','t=0 0',
            'a=group:BUNDLE imm0',f'a=msid-semantic: WMS {session_id}',
            'm=application 9 imm 6001','c=IN IP4 0.0.0.0','a=rtcp:9 IN IP4 0.0.0.0',
            f'a=ice-ufrag:{local_user}',f'a=ice-pwd:{local_password}',
            'a=ice-options:trickle',f'a=aes-key:{data_key.hex()}',
            'a=mid:imm0','a=rtpmap:6001 AES/KCP 330',f'a=ssrc:0 cname:{self.owner_uid}',''])
        header = {'from':self.owner_uid,'to':self.device_id,'sessionid':session_id,
                  'moto_id':'','type':'offer','trace_id':secrets.token_hex(16),
                  'is_pre':0,'p2p_skill':1603,'security_level':3,'path':'lan'}
        offer = {'header':header,'msg':{'sdp':sdp,'preconnect':True,
                                      'token':[{'urls':f'stun:{local_ip}:{port}'}]}}
        candidate = {'header':{**header,'type':'candidate'},'msg':{
            'candidate':f'a=candidate:1 1 UDP 2130706431 {local_ip} {port} typ host generation 0'}}
        reader = writer = None
        tcp_key = self.local_key
        counter = itertools.count(1)
        peer = None
        nominated = False
        remote = {}
        transactions = set()
        received = {}
        pending = {}
        next_send = 0
        files = MapStream()
        started = False
        tasks = []

        async def tcp_send(command,payload):
            writer.write(encrypt_message(tcp_key,next(counter),command,payload))
            await writer.drain()

        async def tcp_receive():
            raw = await reader.readexactly(HEADER.size)
            prefix,_,_,_,length = HEADER.unpack(raw)
            if prefix != PREFIX or not 28 <= length <= 1024 * 1024:
                raise LocalProtocolError('Invalid map signaling envelope')
            return decrypt_message(tcp_key,raw + await reader.readexactly(length+4))

        def una(conversation):
            return received.get(conversation,0)

        async def control(payload):
            nonlocal next_send
            sequence = next_send; next_send += 1
            packet = encode_datagram(Segment(0,81,0,512,int(time.time()*1000)&0xffffffff,
                                             sequence,una(0),payload),data_key)
            await loop.sock_sendto(udp,packet,peer)
            pending[sequence] = [packet,loop.time(),0]

        async def start_files():
            nonlocal started
            if started:
                return
            started = True
            for payload in (authorization('admin',self.file_password_hash,0),sweeper_query(),sweeper_stream()):
                await control(payload)
                await asyncio.sleep(.15)

        async def check_peer():
            if peer is None or 'ice-pwd' not in remote or transactions:
                return
            transaction = os.urandom(12); transactions.add(transaction)
            attrs = [attribute(6,(remote['ice-ufrag']+':'+local_user).encode()),
                     attribute(0x24,struct.pack('>I',0x6e0001ff)),
                     attribute(0x8029,os.urandom(8)),attribute(0x8022,b'3.5.5\0\0\0')]
            await loop.sock_sendto(udp,build_stun(1,transaction,attrs,remote['ice-pwd'].encode()),peer)

        async def signal():
            nonlocal peer
            while True:
                command,body = await tcp_receive()
                if command != 32:
                    continue
                if body.startswith(bytes(4)): body = body[4:]
                if body.startswith(b'3.5'): body = body[15:]
                try: message = json.loads(body)
                except (ValueError,UnicodeDecodeError): continue
                if not isinstance(message,dict) or not isinstance(message.get('msg'),dict):
                    continue
                kind = message.get('header',{}).get('type')
                if kind == 'answer':
                    for name in ('ice-ufrag','ice-pwd','aes-key'):
                        match = re.search(r'(?m)^a='+name+r':([^\r\n]*)',message['msg'].get('sdp',''))
                        if match: remote[name] = match[1]
                    if remote.get('aes-key') != data_key.hex():
                        raise LocalProtocolError('Map data key did not match the owner offer')
                    await check_peer()
                elif kind == 'candidate':
                    values = message['msg'].get('candidate','').split()
                    if (not nominated and len(values)>=8 and values[2].upper()=='UDP'
                            and values[4]==robot_ip and values[5].isdigit() and 1<=int(values[5])<=65535):
                        peer = (robot_ip,int(values[5])); await check_peer()

        async def receive_data():
            nonlocal peer,nominated
            gaps = {}
            while True:
                packet,address = await loop.sock_recvfrom(udp,65507)
                if address[0] != robot_ip:
                    continue
                if len(packet)>=20 and packet[4:8]==bytes.fromhex('2112a442'):
                    try:
                        stun = parse_stun(packet)
                        if stun['kind']==1:
                            usernames = [value.decode() for kind,value in stun['attributes'] if kind==6]
                            if not usernames or not usernames[0].startswith(local_user+':'):
                                continue
                            parse_stun(packet,local_password.encode())
                            reply = binding_success(stun['transaction'],address,local_password.encode(),b'3.5.5\0\0\0')
                            await loop.sock_sendto(udp,reply,address)
                            if any(kind==0x25 for kind,_ in stun['attributes']):
                                peer,nominated = address,True
                                await start_files()
                        elif stun['kind']==0x101 and stun['transaction'] in transactions and 'ice-pwd' in remote:
                            parse_stun(packet,remote['ice-pwd'].encode())
                    except (ValueError,UnicodeDecodeError):
                        continue
                    continue
                if not nominated or address != peer:
                    continue
                try: segment = decode_datagram(packet,data_key)
                except P2PFormatError: continue
                if segment.conversation == 0:
                    for sequence in list(pending):
                        if sequence < segment.unacknowledged or (segment.command==82 and sequence==segment.sequence):
                            pending.pop(sequence,None)
                if segment.command != 81 or segment.conversation not in (0,5):
                    continue
                current = una(segment.conversation)
                if segment.sequence >= current:
                    if segment.sequence-current>128:
                        raise LocalProtocolError('Map receive window exceeded')
                    seen = gaps.setdefault(segment.conversation,set()); seen.add(segment.sequence)
                    while current in seen:
                        seen.remove(current); current += 1
                    received[segment.conversation] = current
                ack = Segment(segment.conversation,82,0,512,segment.timestamp,
                              segment.sequence,current,b'')
                await loop.sock_sendto(udp,encode_datagram(ack,data_key),peer)
                for update in files.feed(segment):
                    await on_file(update.name,update.data)

        async def maintenance():
            start = loop.time()
            while True:
                await asyncio.sleep(.25)
                if not started and loop.time()-start>15:
                    raise TimeoutError('Map ICE negotiation timed out')
                for sequence,(packet,sent,retries) in list(pending.items()):
                    if loop.time()-sent < 2**retries:
                        continue
                    if retries>=3:
                        raise TimeoutError('Map control request was not acknowledged')
                    await loop.sock_sendto(udp,packet,peer)
                    pending[sequence] = [packet,loop.time(),retries+1]

        try:
            async with asyncio.timeout(seconds):
                reader,writer = await asyncio.wait_for(asyncio.open_connection(robot_ip,6668),timeout=10)
                nonce = os.urandom(16)
                await tcp_send(3,nonce)
                command,payload = await tcp_receive()
                if command!=4 or len(payload)!=52 or payload[:4]!=bytes(4):
                    raise LocalProtocolError('Invalid map signaling handshake')
                proof = hmac.new(self.local_key,nonce,hashlib.sha256).digest()
                if not hmac.compare_digest(payload[20:],proof):
                    raise LocalProtocolError('Map signaling proof failed')
                robot_nonce = payload[4:20]
                await tcp_send(5,hmac.new(self.local_key,robot_nonce,hashlib.sha256).digest())
                tcp_key = derive_session_key(self.local_key,nonce,robot_nonce)
                await tcp_send(16,b'{}')
                for _ in range(8):
                    command,_ = await tcp_receive()
                    if command in (8,16): break
                await tcp_send(32,json.dumps(offer,separators=(',',':')).encode())
                await tcp_send(32,json.dumps(candidate,separators=(',',':')).encode())
                tasks = [asyncio.create_task(coro) for coro in (signal(),receive_data(),maintenance())]
                await asyncio.gather(*tasks)
        finally:
            for task in tasks: task.cancel()
            if tasks: await asyncio.gather(*tasks,return_exceptions=True)
            if started and peer is not None:
                try:
                    await asyncio.wait_for(control(sweeper_cancel()),timeout=.5)
                except (OSError,TimeoutError): pass
            udp.close()
            if writer:
                writer.close()
                try: await asyncio.wait_for(writer.wait_closed(),timeout=1)
                except (OSError,TimeoutError): pass
