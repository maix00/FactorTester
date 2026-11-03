"""Reuse a checksummed standalone alpha wheel when only the NT adapter changed."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import os
import re
import subprocess
import tempfile


def source_identity(repo: Path, revision: str) -> bytes:
    tree = subprocess.check_output(['git', '-C', str(repo), 'ls-tree', '-r', revision])
    return b'\n'.join(line for line in tree.splitlines()
                      if not line.split(b'\t', 1)[-1].startswith(b'adapters/nautilus/'))


def verified(wheel: Path, cache: Path) -> str | None:
    with wheel.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    for receipt in cache.glob('*/checksums.sha256'):
        for line in receipt.read_text().splitlines():
            parts = line.split(maxsplit=1)
            if len(parts) != 2 or parts[0] != digest:
                continue
            value = Path(parts[1].lstrip('*'))
            if not value.is_absolute():
                value = receipt.parent / value
            if value.resolve() == wheel.resolve():
                return digest
    return None


def reuse(repo: Path, cache: Path, revision: str, platform: str) -> dict | None:
    tags = {'linux/amd64': 'x86_64', 'linux/arm64': 'aarch64'}
    arch = tags[platform]
    desired = source_identity(repo, revision)
    target = cache / ('alpha-' + revision)
    for candidate in sorted(cache.glob('alpha-*')):
        previous = candidate.name.removeprefix('alpha-')
        if not re.fullmatch(r"[0-9a-f]{40}", previous) or previous == revision:
            continue
        try:
            equivalent = source_identity(repo, previous) == desired
        except subprocess.CalledProcessError:
            continue
        if not equivalent:
            continue
        wheels = list(candidate.glob(f'py_alpha_lib-*-cp314-abi3-*linux*{arch}.whl'))
        if len(wheels) != 1 or not (digest := verified(wheels[0], cache)):
            continue
        target.mkdir(parents=True, exist_ok=True)
        destination = target / wheels[0].name
        if destination.exists():
            if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                raise ValueError('existing alpha wheel differs; preserve for inspection')
        else:
            # Hard links keep original bytes and avoid another full artifact copy.
            os.link(wheels[0], destination)
        receipt = {'source_revision': revision, 'reused_revision': previous,
                   'source_identity': hashlib.sha256(desired).hexdigest(),
                   'platform': platform, 'sha256': digest, 'wheel': str(destination)}
        with tempfile.NamedTemporaryFile(mode='w', dir=target, delete=False) as f:
            json.dump(receipt, f, indent=2)
            staging = Path(f.name)
        staging.replace(target / 'reuse.json')
        return receipt
    return None


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo', type=Path, required=True)
    p.add_argument('--cache', type=Path, required=True)
    p.add_argument('--revision', required=True)
    p.add_argument('--platform', choices=['linux/amd64', 'linux/arm64'], required=True)
    a = p.parse_args()
    result = reuse(a.repo, a.cache, a.revision, a.platform)
    if result is None:
        raise SystemExit(3)
    print('standalone alpha wheel cache=reused ' + json.dumps(result))
