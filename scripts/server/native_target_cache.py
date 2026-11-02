"""Bound the owned Cargo target after a completed, exclusively locked build."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def allocated_kib(path: Path) -> int:
    if not path.exists():
        return 0
    return int(subprocess.check_output(['du', '-sk', str(path)], text=True).split()[0])


def trim(cache: Path, target: Path, *, limit_kib: int) -> dict:
    """Keep compiled dependencies when dropping incremental state is sufficient.

    The caller holds native_build_lock for the entire build and cleanup. Only
    the build's own default target may be removed; an external target is never
    ours to prune. No running Cargo process may use this target during cleanup.
    """
    if limit_kib <= 0:
        raise ValueError('native target cache budget must be positive')
    cache, target = cache.absolute(), target.absolute()
    before = allocated_kib(target)
    result = dict(before_kib=before, after_kib=before, action='retained')
    if before <= limit_kib:
        return result
    if target != cache / 'target-reusable' or target.is_symlink():
        raise ValueError('external native target exceeds budget; left untouched')
    # Refuse a release-directory symlink before descending into it. rmtree of
    # the owned target itself never follows symlinks to external directories.
    release = target / 'release'
    if release.is_symlink():
        raise ValueError('native release cache is a symlink; left untouched')
    incremental = release / 'incremental'
    if incremental.is_symlink():
        raise ValueError('native incremental cache is a symlink; left untouched')
    if incremental.exists():
        shutil.rmtree(incremental)
        result['action'] = 'incremental-pruned'
    remaining = allocated_kib(target)
    if remaining > limit_kib:
        shutil.rmtree(target)
        result['action'] = 'evicted'
        remaining = 0
    result['after_kib'] = remaining
    return result


def main() -> None:
    if os.environ.get('TR_NATIVE_BUILD_LOCK_HELD') != '1':
        raise SystemExit('native target cleanup requires the build lock')
    cache, target, limit_gib = sys.argv[1:]
    receipt = trim(Path(cache), Path(target), limit_kib=int(limit_gib) * 1024 * 1024)
    print('native target cache=' + json.dumps(receipt, sort_keys=True))


if __name__ == '__main__':
    main()
