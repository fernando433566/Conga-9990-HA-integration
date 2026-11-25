"""Small IPv4 STUN codec for an owned, bounded local ICE experiment.

Independent implementation of RFC 5389. Does not open sockets or configure NAT.
"""
import hashlib
import hmac
import socket
import struct
import zlib

COOKIE=0x2112A442
HEADER=struct.Struct('>HHI12s')


def attribute(kind,value):
    return struct.pack('>HH',kind,len(value))+value+bytes((-len(value))%4)


def build(kind,transaction,attributes=(),key=None,fingerprint=True):
    if len(transaction)!=12:raise ValueError('STUN transaction must be 12 bytes')
    body=b''.join(attributes)
    if key is not None:
        signed=HEADER.pack(kind,len(body)+24,COOKIE,transaction)+body
        body+=attribute(8,hmac.new(key,signed,hashlib.sha1).digest())
    header=HEADER.pack(kind,len(body)+(8 if fingerprint else 0),COOKIE,transaction)
    result=header+body
    if fingerprint:result+=attribute(0x8028,struct.pack('>I',(zlib.crc32(result)^0x5354554e)&0xffffffff))
    return result


def parse(packet,key=None):
    if len(packet)<20:raise ValueError('Truncated STUN header')
    kind,size,cookie,tx=HEADER.unpack_from(packet)
    if kind&0xc000 or cookie!=COOKIE or size%4 or len(packet)!=20+size:raise ValueError('Invalid STUN header')
    attributes=[];offset=20;authenticated=False;fingerprinted=False
    while offset<len(packet):
        if offset+4>len(packet):raise ValueError('Truncated attribute')
        attr,n=struct.unpack_from('>HH',packet,offset)
        end=offset+4+n
        if end>len(packet):raise ValueError('Truncated attribute value')
        value=packet[offset+4:end]
        if attr==8:
            if n!=20:raise ValueError('Invalid integrity size')
            if key is not None:
                signed=packet[:2]+struct.pack('>H',end-20)+packet[4:offset]
                if not hmac.compare_digest(hmac.new(key,signed,hashlib.sha1).digest(),value):raise ValueError('Invalid integrity')
                authenticated=True
        elif attr==0x8028:
            if n!=4 or end!=len(packet):raise ValueError('Invalid fingerprint position')
            expected=(zlib.crc32(packet[:offset])^0x5354554e)&0xffffffff
            if struct.unpack('>I',value)[0]!=expected:raise ValueError('Invalid fingerprint')
            fingerprinted=True
        elif authenticated:
            raise ValueError('Unexpected attribute after integrity')
        attributes.append((attr,value))
        offset=end+(-n)%4
    if key is not None and not authenticated:raise ValueError('Missing integrity')
    return {'kind':kind,'transaction':tx,'attributes':attributes,'authenticated':authenticated,'fingerprint':fingerprinted}


def binding_success(transaction,address,key=None,software=None):
    host,port=address
    encoded=struct.pack('>BBHI',0,1,port^(COOKIE>>16),struct.unpack('>I',socket.inet_aton(host))[0]^COOKIE)
    attrs=[attribute(0x20,encoded)]
    if software is not None:
        if not 1<=len(software)<=128:raise ValueError('Invalid software identifier')
        attrs.append(attribute(0x8022,software))
    return build(0x101,transaction,attrs,key)
