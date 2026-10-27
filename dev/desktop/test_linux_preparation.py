"""准备流程只在主机规划/编译，CLI 不默认启用写入。"""
import copy
import json
from pathlib import Path
from unittest.mock import Mock
import pytest
from desktopapp import preparation, linuxcli
from looktool import direct, checkpointworker
from test_checkpoint import Camera, values, fake_compile, KEYS


def test_prepare_compiles_and_checks_inverse_without_camera_writes(tmp_path,monkeypatch):
    monkeypatch.setenv('A7C2_CAMERA_READ_ONLY','1')
    camera=Camera(values())
    before=copy.deepcopy((camera.files,camera.ram,camera.saved))
    original=direct.DirectJob
    def factory(folder):
        job=original(folder,factory=lambda:camera)
        job.native=Mock(side_effect=AssertionError('Preparation must not stage native code'))
        return job
    monkeypatch.setattr(direct,'DirectJob',factory)
    def plan(current,*args,**kwargs):
        target=dict(current)
        changed=bytearray(current['appFw.so']);changed[3:5]=b'XY'
        target['appFw.so']=bytes(changed)
        return target,[{KEYS[0]:b'\x05'},{}],None
    monkeypatch.setattr(direct,'plan',plan)
    monkeypatch.setattr(checkpointworker,'compile_worker',fake_compile)
    result=preparation.prepare(dict(firmware='2.01',workspace=str(tmp_path/'preview'),mode='fl23_enable'),tmp_path)
    assert result['phase']=='PREPARED_READ_ONLY' and result['program_workers']==1
    assert (camera.files,camera.ram,camera.saved)==before
    assert not camera.native_calls and not camera.saves
    state=json.loads((tmp_path/'preview/preparation.private.json').read_text())
    assert all(state['inverse_bytes_verified'].values())
    assert not state['camera_worker_uploaded'] and not state['native_preflight_executed']
    assert not (tmp_path/'preview/direct.private.json').exists()


def test_prepare_requires_readonly_guard_before_camera_access(tmp_path,monkeypatch):
    import read_only
    monkeypatch.setattr(read_only,'enabled',lambda:False)
    camera=Mock();monkeypatch.setattr(direct,'DirectJob',camera)
    with pytest.raises(ValueError,match='READ_ONLY'):preparation.prepare({},tmp_path)
    camera.assert_not_called()


def test_doctor_does_not_create_worker(monkeypatch,capsys):
    create=Mock();monkeypatch.setattr(linuxcli,'new_job',create)
    assert linuxcli.main(['doctor'])==0
    create.assert_not_called()
    assert json.loads(capsys.readouterr().out)['camera_io'] is False


def test_cli_requires_explicit_write_option(tmp_path,monkeypatch):
    monkeypatch.setattr(linuxcli.sys,'platform','linux')
    monkeypatch.setenv('A7C2_CAMERA_READ_ONLY','0')
    monkeypatch.delenv('A7C2_ALLOW_CAMERA_WRITES',raising=False)
    args=tmp_path/'args.json';args.write_text('{"firmware":"2.01"}')
    job=tmp_path/'job';job.mkdir();(job/'worker.log').write_text('test')
    create=Mock(return_value=job);monkeypatch.setattr(linuxcli,'new_job',create)
    from desktopapp import worker
    execute=Mock(return_value=0);monkeypatch.setattr(worker,'execute_request',execute)
    assert linuxcli.main(['run','--action','restore_auto','--arguments',str(args)])==0
    assert linuxcli.os.environ['A7C2_CAMERA_READ_ONLY']=='1'
    assert create.call_args.args[0]=='restore_auto'


def test_readonly_deployment_cannot_be_overridden_by_cli(tmp_path,monkeypatch):
    monkeypatch.setattr(linuxcli.sys,'platform','linux')
    monkeypatch.setenv('A7C2_CAMERA_READ_ONLY','1')
    args=tmp_path/'args.json';args.write_text('{}')
    create=Mock();monkeypatch.setattr(linuxcli,'new_job',create)
    with pytest.raises(SystemExit):
        linuxcli.main(['run','--action','setup_all','--arguments',str(args),'--allow-camera-writes'])
    create.assert_not_called()

