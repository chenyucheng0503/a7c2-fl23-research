"""Bundle six owner-supplied compiled looks, in NC/CC/NN/Astia/GR+/GR- order.

python dev/desktop/prepare_presets.py --look file1 ... --look file6
This never opens USB. Generated assets stay outside the source repository.
"""
import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'src/looks')]
from desktopapp.presets import PACK, ASSET_NAMES
from looktool import lookfile


LICENSE = "Owner-supplied DCP, used with the author's permission; MIT"
NOTICE = ("Bundled fitted looks and their embedded original DCP profiles are used with the\n"
          "authors' permission and licensed under MIT, like the tool source. See credits.json.\n"
          "Camera rendering is an approximation; native-grid precision is not full DCP fidelity.\n")


def prepare(paths):
    if len(paths) != 6:
        raise ValueError('Provide exactly six compiled looks in NC/CC/NN/Astia/GR+/GR- order')
    sources = []
    for path, name in zip(map(Path, paths), ASSET_NAMES):
        document = lookfile.read(path)
        lookfile.writer_document(document)
        if document['name'] != name or not document.get('native_photo'):
            raise ValueError('Expected native-photo look ' + name + ': ' + str(path))
        sources.append((path, document))
    output = ROOT / 'desktop-assets/presets' / PACK
    output.mkdir(parents=True, exist_ok=True)
    entries = []
    for slot, (path, doc) in enumerate(sources, 1):
        filename = 'slot%d.a7look' % slot
        shutil.copy2(path, output / filename)
        profile = doc.get('raw_profile', {})
        entries.append(dict(slot=slot, name=doc['name'], file=filename, method=doc['method'],
            attribution=LICENSE, source_profile=profile.get('source_profile'),
            source_filename=(profile.get('source_filename') or '').replace('_MTriton',''),
            copyright=LICENSE))
    (output / 'credits.json').write_text(json.dumps(dict(pack=PACK, looks=entries),
        ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (output / 'NOTICE.txt').write_text(NOTICE, encoding='utf-8')
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--look', action='append', required=True)
    print(prepare(parser.parse_args().look))
