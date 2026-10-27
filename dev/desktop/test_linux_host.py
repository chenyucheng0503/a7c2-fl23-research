"""Linux USB 隔离、只读屏障与恢复会话，全部使用假设备。"""
import importlib.util
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
from unittest.mock import Mock
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src/camera_runtime'))
import linux_host as host
import read_only as policy


@pytest.fixture
def topology(tmp_path, monkeypatch):
    usb = tmp_path/'usb'
    block = tmp_path/'block'
    usb.mkdir(); block.mkdir()
    camera = usb/'3-7'
    camera.mkdir()
    for name, value in {'idVendor':'054c','idProduct':'0e8a','product':'ILCE-7CM2',
                        'busnum':'3','devnum':'7'}.items():
        (camera/name).write_text(value)
    for name, number in [('sdd1','8:49'),('sde1','8:65')]:
        real = camera/'storage'/name
        real.mkdir(parents=True)
        (real/'dev').write_text(number)
        (block/name).symlink_to(real, target_is_directory=True)
    other=usb/'3-5';other.mkdir()
    (other/'idVendor').write_text('0781');(other/'idProduct').write_text('5591')
    real=other/'sda1';real.mkdir();(real/'dev').write_text('8:1')
    (block/'sda1').symlink_to(real,target_is_directory=True)
    mounts=tmp_path/'mountinfo'
    mounts.write_text('1 0 8:1 / /boot rw - vfat /dev/sda1 rw\n'
                      '2 0 0:99 / /mnt/disks/Sony\\040DSC rw - fuseblk /dev/sdd1 rw\n'
                      '3 0 8:65 / /mnt/disks/PMHOME ro - vfat /dev/sde1 ro\n')
    monkeypatch.setattr(host,'USB',usb);monkeypatch.setattr(host,'BLOCK',block)
    monkeypatch.setattr(host,'MOUNTS',mounts);monkeypatch.setattr(host,'LOCK',tmp_path/'lock')
    return camera,mounts


def test_only_camera_mounts_including_fuseblk_and_spaces(topology):
    camera,_=topology
    assert set(host.camera_mounts(camera))=={
        ('/mnt/disks/Sony DSC','/dev/sdd1'),('/mnt/disks/PMHOME','/dev/sde1')}
    assert host.cameras()==[(camera,'0e8a')]


def test_busy_mount_never_forces_or_touches_boot(topology,monkeypatch):
    camera,_=topology
    h=host.CameraHost();h.path=camera
    monkeypatch.setattr(host.time,'monotonic',Mock(side_effect=range(100)))
    monkeypatch.setattr(host.time,'sleep',lambda _:None)
    run=Mock(return_value=SimpleNamespace(returncode=1,stderr='busy'))
    monkeypatch.setattr(host.subprocess,'run',run)
    with pytest.raises(RuntimeError,match='未强制'):h.prepare()
    assert run.call_args.args[0][:2]==['umount','--']
    assert run.call_args.args[0][2] in {'/mnt/disks/Sony DSC','/mnt/disks/PMHOME'}


def test_boot_mount_is_refused_even_if_source_is_camera(topology):
    camera,mounts=topology
    mounts.write_text('1 0 8:49 / /boot rw - vfat /dev/sdd1 rw\n')
    with pytest.raises(RuntimeError,match='系统'):host.camera_mounts(camera)


def test_claim_validates_port_and_restores_driver_on_failure(topology,monkeypatch):
    camera,mounts=topology;mounts.write_text('')
    h=host.CameraHost();h.path=camera;h.address=(3,(7,))
    device=Mock(bus=3,port_numbers=(8,),idVendor=0x054c,idProduct=0x0e8a)
    with pytest.raises(RuntimeError,match='物理端口'):h.claim(device)
    device.detach_kernel_driver.assert_not_called()
    device.port_numbers=(7,)
    device.get_active_configuration.return_value={(0,0):SimpleNamespace(
        bInterfaceClass=8,bInterfaceSubClass=6,bInterfaceProtocol=80)}
    device.is_kernel_driver_active.return_value=True
    monkeypatch.setattr('usb.util.claim_interface',Mock(side_effect=RuntimeError('busy')))
    monkeypatch.setattr('usb.util.dispose_resources',Mock())
    with pytest.raises(RuntimeError,match='busy'):h.claim(device,(8,6,80))
    device.attach_kernel_driver.assert_called_once_with(0)


def test_restore_releases_lock_even_if_kernel_attach_fails(topology,monkeypatch):
    camera,_=topology
    h=host.CameraHost();h.path=camera;h.address=(3,(7,));h.detached=True;h.lock=Mock()
    locked=h.lock
    device=Mock(bus=3,port_numbers=(7,),idVendor=0x054c,idProduct=0x0e8a)
    device.is_kernel_driver_active.return_value=False
    device.attach_kernel_driver.side_effect=RuntimeError('reattach')
    monkeypatch.setattr('usb.util.dispose_resources',Mock())
    with pytest.raises(RuntimeError,match='reattach'):h.close(lambda:device)
    locked.close.assert_called_once()


def test_root_required_before_enumeration(monkeypatch):
    monkeypatch.setattr(host.os,'geteuid',lambda:1000)
    find=Mock();monkeypatch.setattr(host,'cameras',find)
    with pytest.raises(PermissionError,match='root'):host.CameraHost().__enter__()
    find.assert_not_called()


@pytest.fixture
def read_only(monkeypatch):
    monkeypatch.setattr(policy.sys,'platform','linux')
    monkeypatch.delenv('A7C2_ALLOW_CAMERA_WRITES',raising=False)
    monkeypatch.delenv('A7C2_CAMERA_READ_ONLY',raising=False)


@pytest.mark.parametrize('command,payload',[
    (5,b'\0'),(5,b'\1'),(1,struct.pack('<I',0xe70003)),(0x40,struct.pack('<II',0x2a40001,1))])
def test_read_queries_allowed(read_only,command,payload):
    policy.check(0x40,struct.pack('<HH',0x603,command)+payload)


def test_actual_snapshot_and_property_apis_match_readonly_policy(read_only):
    from pmca.usb.sony import SonySenserCamera
    calls=[]
    def packet(function,data):
        policy.check(function,data)
        calls.append((function,data))
        return 0,b'read-data'
    camera=SonySenserCamera(SimpleNamespace(sendSenserPacket=packet))
    assert camera.getBackupPresetData(True)==b'read-data'
    assert camera.getBackupPresetData(False)==b'read-data'
    assert camera.getBackupPresetDataStatus()==b'read-data'
    assert camera.readBackup(0x00e70003)==b'read-data'
    assert len(calls)==4
    for write in [lambda:camera.writeBackup(0x02cf1287,b'\x0a'),
                  lambda:camera.saveBackup(0x02cf),
                  lambda:camera.setBackupPresetData(0,b'write-data')]:
        with pytest.raises(policy.ReadOnlyViolation):write()
    assert len(calls)==4


@pytest.mark.parametrize('pfunc,data',[
    (0x40,struct.pack('<HH',0x603,2)+bytes(8)),
    (0x40,struct.pack('<HH',0x603,3)+bytes(2)),
    (0x40,struct.pack('<HH',0x603,0x41)+bytes(8)),
    (0x40,struct.pack('<HH',0x1001,16)+b'\0\xff\0data'),
    (0x40,struct.pack('<HH',0x1001,18)+b'\0\xff'),
    (0xff01,b'\x01\0'),(0xff03,bytes(8)),(0x20,b''),
    (0x10,struct.pack('<HHB',0,0xf1,1))])
def test_mutations_denied_before_transport(read_only,pfunc,data):
    with pytest.raises(policy.ReadOnlyViolation):policy.check(pfunc,data)


def test_explicit_readonly_overrides_write_optin(read_only,monkeypatch):
    monkeypatch.setenv('A7C2_ALLOW_CAMERA_WRITES','1')
    assert not policy.enabled()
    monkeypatch.setenv('A7C2_CAMERA_READ_ONLY','1')
    with pytest.raises(policy.ReadOnlyViolation):policy.require_writes()


def test_blocked_write_keeps_session_healthy(read_only):
    from looktool.devicesession import modules
    transport,_=modules()
    session=transport.Session();session.backend=Mock();session.channel=Mock()
    with pytest.raises(policy.ReadOnlyViolation):session.jiritsu(16,b'\0\xff\0data')
    assert session.healthy and not session.mutating
    session.channel.sendSenserPacket.assert_not_called()


def test_recovery_linux_lease_does_not_authenticate(monkeypatch):
    from looktool.devicesession import modules
    transport,_=modules()
    monkeypatch.setattr(transport.sys,'platform','linux')
    lease=Mock();lease.__enter__=Mock(return_value=lease)
    lease.address=(3,(7,));lease.service_started=False
    factory=Mock(return_value=lease);monkeypatch.setattr(host,'CameraHost',factory)
    expected={'model':'ILCE-7CM2','serial_sha256':'body'}
    device=Mock();monkeypatch.setattr(transport,'get_device',lambda pid:device)
    monkeypatch.setattr(transport,'Bounded',lambda *a,**kw:Mock())
    monkeypatch.setattr(transport,'GenericUsbDriver',lambda backend:Mock())
    auth=Mock();monkeypatch.setattr(transport,'SonySenserAuthDevice',lambda driver:auth)
    monkeypatch.setattr(transport,'SonySenserDevice',lambda driver:Mock())
    monkeypatch.setattr(transport,'SonySenserCamera',lambda channel:Mock())
    monkeypatch.setattr(transport,'service_identity',lambda *a:expected)
    session=transport.RecoverySession(expected).__enter__()
    factory.assert_called_once_with(service=True)
    lease.claim.assert_called_once_with(device)
    auth.start.assert_not_called();auth.authenticate.assert_not_called()
    assert session.identity==expected and session.mutating
    session._close_linux()
    lease.close.assert_called_once()

