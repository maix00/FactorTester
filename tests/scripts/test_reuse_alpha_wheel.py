from pathlib import Path
import hashlib
import subprocess
from scripts.server.reuse_alpha_wheel import reuse


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()


def commit(repo):
    git(repo, 'add', '.')
    git(repo, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'fixture')
    return git(repo, 'rev-parse', 'HEAD')


def setup(tmp_path):
    repo = tmp_path / 'repo'; repo.mkdir()
    git(repo, 'init', '-q')
    (repo / 'alpha-algo').mkdir(); (repo / 'alpha-algo/core.rs').write_text('core')
    (repo / 'adapters/nautilus').mkdir(parents=True)
    adapter = repo / 'adapters/nautilus/rule.rs'; adapter.write_text('old')
    old = commit(repo)
    cache = tmp_path / 'wheels'
    wheel = cache / ('alpha-' + old) / 'py_alpha_lib-0.3.1-cp314-abi3-manylinux_2_34_x86_64.whl'
    wheel.parent.mkdir(parents=True); wheel.write_bytes(b'previously verified wheel')
    receipt = cache / 'runtime/checksums.sha256'; receipt.parent.mkdir()
    receipt.write_text(hashlib.sha256(wheel.read_bytes()).hexdigest() + '  ' + str(wheel) + '\n')
    adapter.write_text('corrected rule'); new = commit(repo)
    return repo, cache, wheel, old, new


def test_adapter_only_change_reuses_exact_verified_bytes(tmp_path):
    repo, cache, wheel, old, new = setup(tmp_path)
    result = reuse(repo, cache, new, 'linux/amd64')
    assert result['reused_revision'] == old
    assert Path(result['wheel']).read_bytes() == wheel.read_bytes()
    assert Path(result['wheel']).stat().st_ino == wheel.stat().st_ino
    assert (Path(result['wheel']).parent / 'reuse.json').is_file()


def test_algorithm_changes_cannot_reuse_adapter_only_artifact(tmp_path):
    repo, cache, _, _, _ = setup(tmp_path)
    (repo / 'alpha-algo/core.rs').write_text('new algorithm')
    assert reuse(repo, cache, commit(repo), 'linux/amd64') is None


def test_corrupt_or_wrong_architecture_wheel_is_not_reused(tmp_path):
    repo, cache, wheel, _, new = setup(tmp_path)
    assert reuse(repo, cache, new, 'linux/arm64') is None
    wheel.write_bytes(b'corruption')
    assert reuse(repo, cache, new, 'linux/amd64') is None


def test_unreceipted_wheel_is_not_reused(tmp_path):
    repo, cache, _, _, new = setup(tmp_path)
    (cache / 'runtime/checksums.sha256').unlink()
    assert reuse(repo, cache, new, 'linux/amd64') is None
