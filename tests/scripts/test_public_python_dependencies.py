from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import pytest

from scripts.server import public_python_dependencies as cache


def repo(tmp_path, name, *, stage=cache._LEGACY, requirements="flask==3.1.3\n"):
    root = tmp_path / name
    deploy = root / "deploy"
    dockerfile = deploy / "docker/factortester-public/FactorTester.Dockerfile"
    dockerfile.parent.mkdir(parents=True)
    dockerfile.write_text("FROM python:3.14-slim@sha256:abc AS factortester-public-deps\n"
                          + stage + "\nFROM factortester-public-deps AS traderesearch-cli-builder\n")
    (deploy / "requirements-public-linux.txt").write_text(requirements)
    return root


def test_identity_supports_legacy_bootstrap_and_invalidates_changed_inputs(tmp_path):
    old = repo(tmp_path, "old")
    dockerfile = (Path(__file__).resolve().parents[2] / "deploy/docker/factortester-public/FactorTester.Dockerfile").read_text()
    stage = cache._BEGIN + dockerfile.split(cache._BEGIN, 1)[1].split(cache._END, 1)[0] + cache._END
    new = repo(tmp_path, "new", stage=stage)
    identity = cache.dependency_identity(old, "linux/amd64", {})
    assert cache.dependency_identity(new, "linux/amd64", {}) == identity
    assert cache.dependency_identity(new, "linux/arm64", {}) != identity
    assert cache.dependency_identity(new, "linux/amd64", {"FACTORTESTER_PIP_INDEX_URL": "https://other.invalid"}) != identity
    (new / "deploy/requirements-public-linux.txt").write_text("flask==4.0\n")
    assert cache.dependency_identity(new, "linux/amd64", {}) != identity
    (new / "deploy/requirements-public-linux.txt").write_text("flask==3.1.3\n")
    path = new / "deploy/docker/factortester-public/FactorTester.Dockerfile"
    path.write_text(path.read_text().replace("pip check", "pip --version"))
    assert cache.dependency_identity(new, "linux/amd64", {}) != identity


def test_requirements_include_changes_are_part_of_identity(tmp_path):
    project = repo(tmp_path, "repo", requirements="-rnested.txt # tracked\n")
    nested = project / "deploy/nested.txt"
    nested.write_text("numpy==1\n")
    before = cache.dependency_identity(project, "linux/amd64", {})
    nested.write_text("numpy==2\n")
    assert cache.dependency_identity(project, "linux/amd64", {}) != before
    (project / "deploy/requirements-public-linux.txt").write_text("-r ../outside.txt\n")
    with pytest.raises(ValueError, match="escapes"):
        cache.dependency_identity(project, "linux/amd64", {})


def test_distribution_inventory_excludes_both_native_wheels(tmp_path, monkeypatch):
    from types import SimpleNamespace

    prefix = tmp_path / "prefix"
    site = prefix / "lib/python/site-packages"
    site.mkdir(parents=True)
    bin_dir = prefix / "bin"
    bin_dir.mkdir()
    (bin_dir / "tool").write_text("#!/bin/sh\n")
    monkeypatch.setattr(sys, "prefix", str(prefix))

    class Dist:
        def __init__(self, name, paths):
            self.metadata = {"Name": name}
            self.files = paths

        def locate_file(self, path):
            return site / path

    distributions = [Dist("nautilus-trader", [Path("nautilus_trader/native.so")]),
                     Dist("py-alpha-lib", [Path("alpha/engine.so")]),
                     Dist("safe-package", [Path("../../../bin/tool"), Path("safe.py")])]
    monkeypatch.setattr(cache.importlib.metadata, "distributions", lambda **_: distributions)
    excluded, commands, native_roots = cache._distribution_paths(site)
    assert excluded == {(site / "nautilus_trader/native.so").resolve(), (site / "alpha/engine.so").resolve()}
    assert commands == {(bin_dir / "tool").resolve()}
    assert native_roots == {"nautilus_trader", "alpha"}
    monkeypatch.setattr(cache.importlib.metadata, "distributions", lambda **_: distributions[1:])
    with pytest.raises(ValueError, match="native distributions"):
        cache._distribution_paths(site)


def test_snapshot_excludes_native_files_and_rejects_corruption(tmp_path, monkeypatch):
    prefix = tmp_path / "prefix"
    site = prefix / "lib/python3.14/site-packages"
    site.mkdir(parents=True)
    (site / "dependency.py").write_bytes(b"value = 42\n")
    (site / "native.so").write_bytes(b"native wheel")
    bin_dir = prefix / "bin"
    bin_dir.mkdir()
    (bin_dir / "public-command").write_bytes(b"#!/bin/sh\n")
    monkeypatch.setattr(sys, "prefix", str(prefix))
    monkeypatch.setattr(cache.sysconfig, "get_path", lambda key: str(site))
    monkeypatch.setattr(cache, "_distribution_paths", lambda path: ({site / "native.so"}, {bin_dir / "public-command"}, set()))
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    identity = "a" * 64
    manifest = cache.extract(snapshot, identity, "sha256:image")
    assert manifest["bytes"] == len(b"value = 42\n") + len(b"#!/bin/sh\n")
    assert not (snapshot / "tree/lib/python3.14/site-packages/native.so").exists()
    destination = tmp_path / "destination"
    stale = destination / "lib/python3.14/site-packages/old-pip.dist-info"
    stale.mkdir(parents=True)
    (stale / "METADATA").write_text("old version")
    cache.install(snapshot, identity, prefix=destination)
    assert not stale.exists()
    assert (destination / "lib/python3.14/site-packages/dependency.py").read_bytes() == b"value = 42\n"
    assert (destination / "bin/public-command").read_bytes() == b"#!/bin/sh\n"
    (snapshot / "tree/bin/public-command").write_bytes(b"corruption")
    untouched = tmp_path / "untouched"
    with pytest.raises(ValueError, match="checksum mismatch"):
        cache.install(snapshot, identity, prefix=untouched)
    assert not untouched.exists()


def test_snapshot_rejects_abi_changes_and_unsafe_manifest_paths(tmp_path):
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    identity = "a" * 64
    manifest = {"format": cache.FORMAT, "identity": identity, "python_tag": "other-python",
                "python_soabi": cache.sysconfig.get_config_var("SOABI"),
                "platform": f"{cache.platform.system().lower()}/{cache.platform.machine().lower()}",
                "site": "lib/python3.14/site-packages", "bytes": 1,
                "files": [{"path": "../../etc/passwd", "size": 1, "sha256": "a" * 64, "mode": 0o644}]}
    (snapshot / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="environment"):
        cache.install(snapshot, identity, prefix=tmp_path / "out")
    manifest["python_tag"] = sys.implementation.cache_tag
    manifest["site"] = Path(cache.sysconfig.get_path("purelib")).resolve().relative_to(Path(sys.prefix).resolve()).as_posix()
    (snapshot / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="unsafe"):
        cache.install(snapshot, identity, prefix=tmp_path / "out")


def test_prepare_reuses_source_image_only_for_identical_contract(tmp_path, monkeypatch):
    old = repo(tmp_path, "old")
    dockerfile = (Path(__file__).resolve().parents[2] / "deploy/docker/factortester-public/FactorTester.Dockerfile").read_text()
    stage = cache._BEGIN + dockerfile.split(cache._BEGIN, 1)[1].split(cache._END, 1)[0] + cache._END
    new = repo(tmp_path, "new", stage=stage)
    image = {"Os": "linux", "Architecture": "amd64", "Id": "sha256:image"}
    monkeypatch.setattr(cache, "_image", lambda ref: image)
    observed = []
    monkeypatch.setattr(cache, "_validate_source", lambda *args: observed.append("validated"))
    monkeypatch.setattr(cache, "capture", lambda ref, identity, root: root / identity)
    result = cache.prepare(new, old, "previous", tmp_path / "cache", {})
    assert result["reuse_required"] and observed == ["validated"]
    assert result["snapshot_mib"] == 0
    (new / "deploy/requirements-public-linux.txt").write_text("flask==4.0\n")
    result = cache.prepare(new, old, "previous", tmp_path / "cache", {})
    assert not result["reuse_required"] and observed == ["validated"]
    assert result["snapshot_mib"] == 2048


def test_legacy_image_bootstrap_requires_matching_revision_and_build_arguments(tmp_path, monkeypatch):
    project = repo(tmp_path, "repo")
    source = {"Config": {"Labels": {"org.opencontainers.image.revision": "r"}}}
    aliases = {"FACTORTESTER_DEBIAN_MIRROR": "DEBIAN_MIRROR",
               "FACTORTESTER_DEBIAN_SECURITY_MIRROR": "DEBIAN_SECURITY_MIRROR",
               "FACTORTESTER_PIP_INDEX_URL": "PIP_INDEX_URL",
               "FACTORTESTER_CODEX_VERSION": "CODEX_VERSION",
               "FACTORTESTER_CODEX_NPM_REGISTRY": "CODEX_NPM_REGISTRY"}
    args = " ".join(f"{aliases.get(k, k)}={v}" for k, v in cache._ARGS.items())
    history = (f"RUN |12 {args} /bin/sh -c python -m pip install --no-cache-dir --no-deps ./nautilus_trader.whl\n"
               f"RUN |10 {args} /bin/sh -c python -m pip install --no-cache-dir -r /tmp/requirements-public-linux.txt")
    monkeypatch.setattr(cache, "_run", lambda cmd: "r" if cmd[0] == "git" else history)
    monkeypatch.setattr(cache.subprocess, "run", lambda *args, **kwargs: None)
    cache._validate_source(source, "sha256:image", project, "a" * 64, {})
    with pytest.raises(ValueError, match="arguments differ"):
        cache._validate_source(source, "sha256:image", project, "a" * 64,
                               {"FACTORTESTER_PIP_INDEX_URL": "https://other.invalid"})
    source["Config"]["Labels"]["org.opencontainers.image.revision"] = "wrong"
    with pytest.raises(ValueError, match="revision differ"):
        cache._validate_source(source, "sha256:image", project, "a" * 64, {})


def test_snapshot_capture_is_networkless_bounded_and_pins_image_id(tmp_path, monkeypatch):
    identity = "c" * 64
    image = {"Id": "sha256:immutable", "Config": {"Labels": {"org.traderesearch.python-deps.identity": identity}}}
    monkeypatch.setattr(cache, "_image", lambda ref: image)
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        mount = next(value for value in args if isinstance(value, str) and value.endswith(",dst=/snapshot"))
        payload = Path(mount.split("src=", 1)[1].split(",dst=", 1)[0])
        (payload / "tree").mkdir()
        (payload / "manifest.json").write_text(json.dumps({"format": cache.FORMAT,
            "identity": identity, "bytes": 1, "files": [{"path": "unused"}]}))

    monkeypatch.setattr(cache.subprocess, "run", run)
    target = cache.capture("moving-tag", identity, tmp_path / "cache", require_label=True)
    assert target.name == identity
    command = calls[0]
    assert command[command.index("--network") + 1] == "none"
    assert command[command.index("--memory") + 1] == "256m"
    assert command[command.index("--memory-swap") + 1] == "256m"
    assert command[command.index("--cpus") + 1] == "0.5"
    assert "--read-only" in command and "--cap-drop" in command
    assert "sha256:immutable" in command and "moving-tag" not in command


def test_release_promotes_one_snapshot_without_deleting_unknown_files(tmp_path):
    root = tmp_path / "cache"
    root.mkdir()
    for identity in ["a" * 64, "b" * 64]:
        directory = root / identity
        directory.mkdir()
        (directory / "tree").mkdir()
        (directory / "manifest.json").write_text(json.dumps({"format": cache.FORMAT,
            "identity": identity, "bytes": 1, "files": [{"path": "unused"}]}))
    (root / "unrelated").write_text("do not delete")
    cache.promote(root, "b" * 64)
    assert json.loads((root / "current.json").read_text())["identity"] == "b" * 64
    assert not (root / ("a" * 64)).exists()
    assert (root / "unrelated").read_text() == "do not delete"


def test_dependency_changes_cannot_replace_a_live_release_before_build():
    root = Path(__file__).resolve().parents[2]
    activate = (root / "scripts/server/activate_public_revision.sh").read_text()
    build = activate.index('bash "$public_script" build factortester-public')
    stop = activate.index('bash "$public_script" stop-app', build)
    assert build < stop
    wrapper = (root / "scripts/server/factortester_public_container.sh").read_text()
    assert wrapper.index('public_python_dependencies.py" prepare') < wrapper.index('"${compose[@]}" build --builder')
    assert 'public_python_dependencies.py" capture' in wrapper
