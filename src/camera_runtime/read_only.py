"""Linux 默认只读。准备阶段连临时 worker 上传、删除和执行都不允许。"""
import os
import struct
import sys


class ReadOnlyViolation(PermissionError):
    pass


def enabled():
    return (os.environ.get('A7C2_CAMERA_READ_ONLY') == '1'
            or (sys.platform.startswith('linux')
                and os.environ.get('A7C2_ALLOW_CAMERA_WRITES') != '1'))


def check(pfunc, data):
    if not enabled():
        return
    allowed = pfunc == 0x10 and data == struct.pack('<HHB', 0, 0x1f, 0)
    if pfunc == 0x40 and len(data) >= 4:
        from pmca.usb.sony import SonySenserCamera as Camera
        group, command = struct.unpack('<HH', data[:4])
        payload = data[4:]
        if group == 0x603:
            allowed = (((group, command) == Camera.SONY_ADJUST_BACKUP_PDT_READ and payload in (b'\0', b'\1'))
                       or ((group, command) == Camera.SONY_ADJUST_BACKUP_PDT_STAT and not payload)
                       or ((group, command) == Camera.SONY_ADJUST_BACKUP_READ and len(payload) == 4)
                       or (command == 0x40 and len(payload) == 8))
        elif group == 0x1001:
            allowed = ((command == 15 and payload.startswith(b'\0/tmp/jiritsu/')
                        and payload.endswith(b'\0') and b'\0' not in payload[1:-1])
                       or (command == 17 and payload == b'\0\xff\0'))
    if not allowed:
        raise ReadOnlyViolation('只读模式已拦截相机写入/执行；准备结果不是刷写许可。')



def require_writes():
    if enabled():
        raise ReadOnlyViolation("只读模式禁止写入、上传或执行相机 worker。")
