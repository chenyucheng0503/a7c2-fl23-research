"""只读准备：复用现有规划、设置保留和编译，不上传或执行相机 worker。"""
import hashlib
from pathlib import Path
import uuid


def prepare(arguments, job):
    from looktool import bundle, checkpoint, checkpointworker, nameworker
    from looktool.direct import DirectJob, plan
    from . import official, presets
    import read_only
    if not read_only.enabled():
        raise ValueError('准备流程必须启用 A7C2_CAMERA_READ_ONLY=1')
    if arguments.get('firmware') != '2.01':
        raise ValueError('仅支持用户确认的 ILCE-7CM2 2.01')
    mode = arguments.get('mode', 'install_all')
    if mode not in ('install_all', 'fl23_enable', 'fl23_disable', 'factory_reset'):
        raise ValueError('不支持的只读准备模式')
    root = Path(arguments['workspace']).resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError('准备使用独立空目录，保留已有事务')
    root.mkdir(parents=True, exist_ok=True)
    owner = DirectJob(root)
    owner.state_path = root/'preparation.private.json'
    owner.state = dict(schema='a7c2-readonly-preparation/1', mode=mode,
                       job_id=uuid.uuid4().hex[:16], journal=[], camera_written=False)
    options, rows = {}, []
    if mode == 'install_all':
        inputs = root/'inputs';inputs.mkdir()
        options, rows = bundle.documents(presets.resolve(arguments.get('options', {})), inputs)
        options['vertical_persistent'] = bool(options.get('vertical', True))
    owner.save('READING')
    try:
        with owner.factory() as camera:
            owner.state['identity'] = camera.identity
            current = owner.capture(camera)
            planning = dict(current)
            portrait = None
            if mode == 'install_all' and options.get('vertical', True):
                from looktool.portraitjob import vertical_modules
                _, _, portraitstage = vertical_modules()
                from verticaltool import portraitworker
                frames = portraitstage.Stage(camera, owner, ap=current['appFw.so'])
                portrait = portraitworker.build(frames.plans, frames.ap, root/'portrait-worker',
                                                ap_windows=frames.windows)
                # 一键流程先安装竖屏引用，再按当时的程序字节规划外观。
                planning['appFw.so'] = frames.target_ap
            records = camera.records(current['settings-ram.bin'])
            if mode == 'install_all':
                target, wanted, rename = bundle.plan(planning, records, options, rows)
            else:
                target, wanted, rename = plan(planning, records, mode,
                    factory=official.builtin() if mode == 'factory_reset' else None)
            owner.settings(camera, planning, wanted)
            programs = checkpointworker.build_programs(planning, target, root/'worker',
                window_priority=(lambda row:(row[0],row[1])) if mode=='factory_reset' else None)
            names = None
            if rename:
                _, names = nameworker.prepare(
                    {n:planning['resources/'+n] for n in nameworker.filenames()},
                    rename[0], planning['appFw.so'], owner.state['job_id'], root/'names',
                    target_ap=target['appFw.so'], label_ids=rename[1], byte_only=True)
            else:
                names = checkpointworker.build_names(planning, target, root/'worker',
                    owner.state['job_id'], defer_busy_readonly=mode=='factory_reset')
            # 按相同差异算法验证逆向字节，不保存/发布完整相机程序。
            inverses = {}
            for name in checkpoint.PROGRAM_PATHS:
                restored = bytearray(target[name])
                for at, before, after in checkpointworker.differences(planning[name], target[name]):
                    if restored[at:at+len(after)] != after:
                        raise ValueError('逆向窗口冲突')
                    restored[at:at+len(before)] = before
                if restored != planning[name]:
                    raise ValueError('逆向字节重建失败')
                inverses[name] = True
            owner.save('PREPARED_READ_ONLY', options=options, program_builds=programs,
                names_build=names, portrait_build=portrait, inverse_bytes_verified=inverses,
                source_programs={n:dict(bytes=len(current[n]), sha256=hashlib.sha256(current[n]).hexdigest())
                                 for n in checkpoint.PROGRAM_PATHS},
                settings_keys=[[hex(k) for k in chip] for chip in wanted],
                native_preflight_executed=False, camera_worker_uploaded=False)
        return dict(workspace=str(root), phase='PREPARED_READ_ONLY',
                    program_workers=len(programs), portrait_prepared=portrait is not None,
                    camera_written=False, native_preflight_executed=False)
    except BaseException as exc:
        owner.save('PREPARATION_FAILED', error_type=type(exc).__name__, error=str(exc))
        raise

