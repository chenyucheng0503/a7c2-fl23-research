"""Bundled six-look selection, resolved before opening a device.

The actual A7Look/DCP assets are distribution attachments, not MIT source.
No fitting or downloading occurs during installation.
"""
import copy
from pathlib import Path
from .paths import ROOT

PACK = 'default-six-v1'
# 发行包文件编号固定；调整相机槽位时只改映射，不重命名或重做外观资源。
ASSET_NAMES = ('Classic Neg.', 'Classic Chrome', 'Nostalgic Neg.', 'Astia',
               'GR Positive Film', 'GR Negative Film')
SLOT_SOURCES = (4, 5, 6, 3, 2, 1)
NAMES = tuple(ASSET_NAMES[source - 1] for source in SLOT_SOURCES)
SUMMARY = '1 Astia · 2 GR 正片 · 3 GR 负片 · 4 NN · 5 CC · 6 NC'


def catalog():
    """Default file choices without disk access or validation during UI startup."""
    return [dict(slot=slot, path=str(ROOT / 'desktop-assets/presets' / PACK / ('slot%d.a7look' % source)),
                 name=ASSET_NAMES[source - 1])
            for slot, source in enumerate(SLOT_SOURCES, 1)]


def resolve(options):
    """Expand an explicit pack choice; ordinary selected-slot jobs stay intact."""
    options = copy.deepcopy(options)
    pack = options.get('preset_pack')
    if not pack:
        return options
    if pack != PACK:
        raise ValueError('Unknown built-in look pack: ' + str(pack))
    if options.get('looks'):
        raise ValueError('Choose the built-in six looks or custom files, not both')
    from looktool import lookfile
    rows = []
    for row in catalog():
        slot, name, path = row['slot'], row['name'], Path(row['path'])
        if not path.is_file():
            raise ValueError('内置六款外观文件缺失，请使用完整工具包；尚未连接相机：' + str(path))
        doc = lookfile.read(path)
        lookfile.writer_document(doc)
        if doc['name'] != name or not doc.get('native_photo'):
            raise ValueError('内置外观名称／照片阶段不符：' + str(path))
        rows.append(dict(slot=slot, path=str(path), name=name))
    options['looks'] = rows
    return options
