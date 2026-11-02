from pathlib import Path
import os
import subprocess
import sys

import pytest

from scripts.server import native_target_cache as cache


def populate(tmp_path):
    target = tmp_path / 'target-reusable'
    (target / 'release/incremental').mkdir(parents=True)
    (target / 'release/incremental/state').write_bytes(b'rolling compiler state')
    (target / 'release/deps').mkdir()
    (target / 'release/deps/unchanged.rlib').write_bytes(b'compiled dependency')
    return target


def test_under_budget_keeps_incremental_and_compiled_dependencies(tmp_path):
    target = populate(tmp_path)
    before = cache.allocated_kib(target)
    assert cache.trim(tmp_path, target, limit_kib=before)['action'] == 'retained'
    assert (target / 'release/incremental/state').exists()
    assert (target / 'release/deps/unchanged.rlib').read_bytes() == b'compiled dependency'


def test_prunes_incremental_first_and_preserves_reusable_dependency_bytes(tmp_path):
    target = populate(tmp_path)
    dependency = target / 'release/deps/unchanged.rlib'
    before = cache.allocated_kib(target)
    result = cache.trim(tmp_path, target, limit_kib=before - 4)
    assert result['action'] == 'incremental-pruned'
    assert result['after_kib'] <= before - 4
    assert not (target / 'release/incremental').exists()
    assert dependency.read_bytes() == b'compiled dependency'


def test_still_oversized_evicts_only_owned_target(tmp_path):
    target = populate(tmp_path)
    wheel = tmp_path / 'completed.whl'
    wheel.write_bytes(b'finished release')
    assert cache.trim(tmp_path, target, limit_kib=1)['action'] == 'evicted'
    assert not target.exists()
    assert wheel.read_bytes() == b'finished release'


def test_external_target_and_symlinked_release_are_not_pruned(tmp_path):
    target = populate(tmp_path)
    outside = tmp_path / 'external'
    outside.mkdir()
    (outside / 'keep').write_bytes(b'other build')
    with pytest.raises(ValueError, match='external'):
        cache.trim(tmp_path, outside, limit_kib=1)
    import shutil
    shutil.rmtree(target / 'release')
    (target / 'release').symlink_to(outside, target_is_directory=True)
    (target / 'compiler-state').write_bytes(b'owned state')
    with pytest.raises(ValueError, match='symlink'):
        cache.trim(tmp_path, target, limit_kib=1)
    assert (outside / 'keep').read_bytes() == b'other build'


def test_cli_refuses_to_touch_cache_without_build_lock(tmp_path):
    target = populate(tmp_path)
    result = subprocess.run([sys.executable, str(Path(cache.__file__)), str(tmp_path), str(target), '1'],
        env={key: value for key, value in os.environ.items() if key != 'TR_NATIVE_BUILD_LOCK_HELD'},
        capture_output=True, text=True)
    assert result.returncode != 0 and 'requires the build lock' in result.stderr
    assert (target / 'release/incremental/state').exists()


def test_cli_runs_under_existing_build_lock_and_reports_budget(tmp_path):
    target = populate(tmp_path)
    lock_script = Path(cache.__file__).with_name('native_build_lock.py')
    result = subprocess.run([sys.executable, str(lock_script), str(tmp_path / '.build.lock'),
        sys.executable, str(Path(cache.__file__)), str(tmp_path), str(target), '1'],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert '"action": "retained"' in result.stdout
    assert 'native build exit=0' in result.stdout
    build_script = Path(cache.__file__).with_name('native_wheel_build.sh').read_text()
    assert build_script.count('python3 "$ROOT/scripts/server/native_target_cache.py"') == 2
    assert build_script.index('refusing to build Nautilus on the public application host') < build_script.index(
        'python3 "$ROOT/scripts/server/native_target_cache.py"')
