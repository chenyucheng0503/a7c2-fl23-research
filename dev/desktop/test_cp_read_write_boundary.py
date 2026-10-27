"""Replay CP read -> changed unit write, with device-side response ownership."""
from array import array
from collections import deque
from types import SimpleNamespace
import struct

import pytest
from looktool import devicesession

transport,_=devicesession.modules()


@pytest.fixture(autouse=True)
def simulated_writes_only(monkeypatch):
    # CpBoundary below is the only device; the root fixture blocks real USB.
    monkeypatch.setenv('A7C2_ALLOW_CAMERA_WRITES', '1')
    monkeypatch.setenv('A7C2_CAMERA_READ_ONLY', '0')


class CpBoundary:
    idVendor=0x054c
    idProduct=0x0336
    _ctx=SimpleNamespace(dispose=lambda device:None)

    def __init__(self,key,raw):
        self.key,self.raw=key,raw
        self.replies=deque();self.calls=[];self.reads=[];self.pending_end=False;self.writes=0
        self.default_timeout=0

    def get_active_configuration(self):
        return {(0,0):[SimpleNamespace(bmAttributes=2,bEndpointAddress=n) for n in (2,0x81)]}

    def write(self,ep,data):
        assert ep==2;data=bytes(data);self.calls.append(data)
        # Until the previous IN response finishes, the device accepts only
        # the next command's first control packet, not its long OUT payload.
        if self.pending_end and len(data)>512:return 512
        header=transport.SonySenserDevice.SenserPacketHeader.unpack(data)
        payload=data[transport.SonySenserDevice.SenserPacketHeader.size:]
        category,command,key,chip=struct.unpack_from('<HHII',payload)
        assert (category,key,chip)==(0x603,self.key,1)
        if command==0x40:
            response=self.raw;self.pending_end=True
        else:
            assert command==0x41 and len(payload[12:])==len(self.raw)
            self.raw=payload[12:];self.writes+=1;response=b''
        head=transport.SonySenserDevice.SenserPacketHeader.pack(size=len(response),pFunc=header.pFunc,
            sequence=header.sequence,version=0,miconType=0,offsetType=0,response=0)
        self.replies.append(head)
        if response:self.replies.extend([response,b''])
        return len(data)

    def read(self,ep,size,timeout=None):
        assert ep==0x81;self.reads.append((size,timeout))
        assert self.replies,'No response was queued'
        raw=self.replies.popleft()
        if not raw:self.pending_end=False
        if len(raw)>size:self.replies.appendleft(raw[size:]);raw=raw[:size]
        return array('B',raw)


@pytest.mark.parametrize('size,key',[(8192,0x02a40001),(28672,0x02a4000d)])
def test_actual_cp_read_then_write_finishes_previous_response_first(size,key):
    device=CpBoundary(key,bytes(size));value=transport.Session()
    value.backend=transport.Bounded(device)
    value.channel=transport.SonySenserDevice(transport.GenericUsbDriver(value.backend))
    value.camera=transport.SonySenserCamera(value.channel)
    replacement=bytes([17])*size
    assert value.cp_read(key)!=replacement
    assert not device.pending_end
    value.cp_write(key,replacement)
    assert device.writes==1 and len(device.calls[1])==size+24
    assert value.cp_read(key)==replacement and not device.pending_end
    assert value.healthy and value.channel._sequence==4


def test_without_the_302_response_finish_the_field_512_short_write_reproduces():
    device=CpBoundary(0x02a40001,bytes(8192));value=transport.Session()
    value.backend=transport.Bounded(device)
    value.channel=transport.SonySenserDevice(transport.GenericUsbDriver(value.backend))
    value.camera=transport.SonySenserCamera(value.channel)
    value.channel._end_packet=lambda:None
    assert value.cp_read(device.key)==bytes(8192) and device.pending_end
    with pytest.raises(transport.GenericUsbException,match='expected_bytes=8216 actual_bytes=512'):
        value.cp_write(device.key,bytes([17])*8192)
    assert device.writes==0 and not value.healthy
