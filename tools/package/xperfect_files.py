#!/usr/bin/env python3
"""Refresh the reviewed file list from the SHA-256-pinned upstream archive and this patch series."""
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from core.downloads import digest, files


def record(archive):
    pin, expected = (ROOT / 'brain/xperfect.archive.sha256.txt').read_text().split()
    if digest(archive) != expected:
        raise SystemExit('The upstream archive did not verify; the file list was left unchanged.')
    with tempfile.TemporaryDirectory(prefix='vx-file-list-') as temp:
        with tarfile.open(archive) as package:
            package.extractall(temp, filter='data')
        xp = Path(temp) / ('xPerfect-' + pin)
        patches = sorted((ROOT / 'brain/patches').glob('xperfect-*.patch'))
        for patch in patches:
            subprocess.run(['git', '-C', str(xp), 'apply', '--whitespace=nowarn', str(patch)], check=True)
        proof = {'pin': pin, 'patches': {p.name: {"sha256": digest(p)} for p in patches}, 'files': files(xp)}
        target = ROOT / 'brain/xperfect.files.json'
        target.write_text(json.dumps(proof, indent=2, sort_keys=True) + '\n')


if __name__ == '__main__':
    record(Path(sys.argv[1]))
