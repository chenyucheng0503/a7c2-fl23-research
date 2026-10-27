"""Linux 相机接口租约：只处理所选 Sony 设备，不解绑整台 USB 控制器。"""
import fcntl
import os
from pathlib import Path
import re
import subprocess
import time

USB = Path('/sys/bus/usb/devices')
BLOCK = Path('/sys/class/block')
MOUNTS = Path('/proc/self/mountinfo')
LOCK = Path('/run/lock/a7c2-usb.lock')
NORMAL_RETURN_SECONDS = 30


def unescape(value):
    return re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), value)


def cameras():
    found = []
    for path in USB.iterdir():
        try:
            if (path/'idVendor').read_text().strip().lower() != '054c':
                continue
            pid = (path/'idProduct').read_text().strip().lower()
            if pid in ('0e8a', '0336'):
                found.append((path, pid))
        except FileNotFoundError:
            continue
    return found


def camera_mounts(path):
    """同时识别块设备 mountinfo 和 Unraid 的 fuseblk /dev 源。"""
    parent = path.resolve()
    devices = {}
    for block in BLOCK.iterdir():
        if block.resolve().is_relative_to(parent):
            devices[block.name] = (block/'dev').read_text().strip()
    result = []
    for line in MOUNTS.read_text().splitlines():
        fields = line.split()
        split = fields.index('-')
        source, target = unescape(fields[split+2]), unescape(fields[4])
        device = Path(source).resolve().name if source.startswith('/dev/') else None
        if fields[2] in devices.values() or device in devices:
            if target in ('/', '/boot', '/usr', '/var', '/mnt/user', '/mnt/cache'):
                raise RuntimeError('拒绝卸载系统或存储根目录：'+target)
            result.append((target, source))
    return sorted(set(result), key=lambda row: len(Path(row[0]).parts), reverse=True)


class CameraHost:
    """持有跨用户/进程锁，绑定物理端口，失败时仅恢复主机接口。"""
    def __init__(self, service=False):
        self.service = service
        self.lock = None
        self.path = None
        self.address = None
        self.detached = False
        self.service_started = False

    def __enter__(self):
        if os.geteuid() != 0:
            raise PermissionError('Linux 相机操作需要 root，请用 sudo 运行同一个 Python 环境。')
        if Path('/.dockerenv').exists() or Path('/run/.containerenv').exists():
            raise RuntimeError('当前 Linux 适配仅支持宿主机；容器可能看不到宿主相机挂载。')
        LOCK.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        self.lock = os.fdopen(fd, 'r+')
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            found = cameras()
            if len(found) != 1 or found[0][1] != ('0336' if self.service else '0e8a'):
                raise RuntimeError('Linux 准备要求恰好一台处于海量存储模式的 A7C II。')
            self.path = found[0][0]
            self.address = (int((self.path/'busnum').read_text()),
                            tuple(map(int, self.path.name.split('-', 1)[1].split('.'))))
            if not self.service and (self.path/'product').read_text().strip() != 'ILCE-7CM2':
                raise RuntimeError('Sony USB 产品名称不是 ILCE-7CM2。')
            try:
                previous = float(self.lock.read().strip() or 0)
            except ValueError:
                previous = 0
            elapsed = time.monotonic() - previous
            if not self.service and previous and 0 <= elapsed < 30:
                print('等待上一次服务模式退出后的冷却时间。', flush=True)
                time.sleep(30-elapsed)
            if not self.service:self.prepare()
            return self
        except BaseException:
            self.release()
            raise

    def check_device(self, device):
        address = (device.bus, tuple(device.port_numbers or ()))
        if address != self.address or device.idVendor != 0x054c or device.idProduct not in (0x0e8a, 0x0336):
            raise RuntimeError('相机 USB 身份或物理端口发生变化，停止接管。')

    def prepare(self):
        found = cameras()
        if len(found) != 1 or found[0] != (self.path, '0e8a'):
            raise RuntimeError('卸载前相机身份发生变化。')
        # 等待内核完成块设备枚举；没有存储卡也允许进入服务模式。
        previous = None
        stable = time.monotonic()
        deadline = stable + 20
        while True:
            current = camera_mounts(self.path)
            now = time.monotonic()
            if current != previous:
                previous, stable = current, now
            if now-stable >= 2:
                break
            if now >= deadline:
                raise RuntimeError('相机卷仍在变化，未接管 USB。')
            time.sleep(.25)
        for target, source in current:
            if cameras() != [(self.path, '0e8a')] or (target, source) not in camera_mounts(self.path):
                raise RuntimeError('卸载前相机或挂载发生变化。')
            print('临时卸载相机卷：'+target, flush=True)
            result = subprocess.run(['umount', '--', target], capture_output=True, text=True, timeout=30)
            if result.returncode:
                raise RuntimeError('相机卷正在使用或无法卸载；未强制卸载：'+result.stderr.strip())
        if camera_mounts(self.path):
            raise RuntimeError('相机卷重新挂载，未接管 USB。')

    def claim(self, device, interface_class=None):
        import usb.util
        self.check_device(device)
        if camera_mounts(self.path):
            raise RuntimeError('相机存储卷仍挂载，拒绝解绑接口。')
        interface = device.get_active_configuration()[(0, 0)]
        if interface_class and (interface.bInterfaceClass, interface.bInterfaceSubClass,
                                interface.bInterfaceProtocol) != interface_class:
            raise RuntimeError('相机 USB 接口类型不符。')
        detached = False
        try:
            if device.is_kernel_driver_active(0):
                device.detach_kernel_driver(0)
                detached = self.detached = True
            usb.util.claim_interface(device, 0)
        except BaseException:
            usb.util.dispose_resources(device)
            if detached:
                device.attach_kernel_driver(0)
            raise

    def restore(self, find):
        """只枚举并重新绑定正常接口，不重新认证、不发相机命令。"""
        import usb.util
        deadline = time.monotonic()+NORMAL_RETURN_SECONDS
        while time.monotonic() < deadline:
            try:device = find()
            except Exception as exc:
                print('等待普通 USB 枚举：'+str(exc), flush=True)
                device = None
            if device is not None:
                try:
                    self.check_device(device)
                    if not device.is_kernel_driver_active(0):
                        device.attach_kernel_driver(0)
                    print('Linux 相机接口已恢复；存储卷由系统原有自动挂载策略处理。', flush=True)
                    return True
                finally:
                    usb.util.dispose_resources(device)
            time.sleep(.5)
        print('相机尚未返回普通 MSC；请保留日志，结束操作后检查相机 USB 模式。', flush=True)
        return False

    def close(self, find):
        try:
            if self.detached or self.service_started:
                self.restore(find)
        finally:
            if self.lock and self.service_started:
                self.lock.seek(0)
                self.lock.truncate()
                self.lock.write(str(time.monotonic()))
                self.lock.flush()
            self.release()

    def release(self):
        if self.lock is not None:
            self.lock.close()
            self.lock = None

