"""Automated tests must never access a physical camera."""
import pytest
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent/'src/shutter_sound'))
sys.path.insert(0,str(Path(__file__).resolve().parent/'src/camera_runtime'))


@pytest.fixture(autouse=True)
def no_physical_usb(monkeypatch):
    import usb.core
    def forbidden(*args,**kwargs):
        raise AssertionError('Physical USB enumeration is forbidden in offline tests; supply a fake camera')
    monkeypatch.setattr(usb.core,'find',forbidden)
    # Linux 会在打开 libusb 前卸载存储卷，必须同时封住主机准备入口。
    import linux_host
    original = linux_host.CameraHost.__enter__
    def no_host_media(self):
        if linux_host.USB == Path('/sys/bus/usb/devices') and linux_host.os.geteuid() == 0:
            raise AssertionError('Physical Linux USB preparation is forbidden in offline tests')
        return original(self)
    monkeypatch.setattr(linux_host.CameraHost,'__enter__',no_host_media)
