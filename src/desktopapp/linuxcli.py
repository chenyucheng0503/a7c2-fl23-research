"""Linux 无界面入口：准备默认只读，写入必须显式选择并沿用原事务。"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
from .jobs import CAMERA_ACTIONS, new_job


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor', help='只检查本机环境，不枚举 USB')
    sub.add_parser('connect', help='只读服务连接')
    sub.add_parser('usb-test', help='至少两分钟的只读传输检查')
    prepare = sub.add_parser('prepare', help='读取并编译所选计划，不上传相机 worker')
    prepare.add_argument('--arguments', type=Path, required=True)
    run = sub.add_parser('run', help='执行/续接已有项目动作，保留原有读回及恢复状态')
    run.add_argument('--action', choices=sorted(CAMERA_ACTIONS-{'driver_uninstall'}), required=True)
    run.add_argument('--arguments', type=Path, required=True)
    run.add_argument('--allow-camera-writes', action='store_true')
    args = parser.parse_args(argv)
    if args.command == 'doctor':
        names=('usb','libusb_package','Cryptodome','numpy','scipy','elftools','ziglang')
        print(json.dumps(dict(platform=sys.platform,python=sys.version.split()[0],camera_io=False,
            dependencies={n:importlib.util.find_spec(n) is not None for n in names}),indent=2))
        return 0
    if not sys.platform.startswith('linux'):
        parser.error('此入口仅用于 Linux 宿主；其他系统保留原入口。')
    # 显式只读部署优先，调用方不能通过请求 JSON 绕过。
    allow = getattr(args,'allow_camera_writes',False)
    if allow and os.environ.get('A7C2_CAMERA_READ_ONLY') == '1':
        parser.error('环境已锁定只读，不能启用写入。')
    os.environ['A7C2_CAMERA_READ_ONLY'] = '0' if allow else '1'
    if allow:os.environ['A7C2_ALLOW_CAMERA_WRITES']='1'
    values=json.loads(args.arguments.read_text()) if hasattr(args,'arguments') else {}
    if not isinstance(values,dict):parser.error('arguments 必须是 JSON 对象')
    action={'connect':'connect','usb-test':'usb_stability','prepare':'linux_prepare'}.get(
        args.command,getattr(args,'action',None))
    job=new_job(action,values)
    print('任务目录：'+str(job),flush=True)
    from .worker import execute_request
    result=execute_request(job/'request.private.json')
    print((job/'worker.log').read_text(),end='',flush=True)
    return result

