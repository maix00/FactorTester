from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

from script.release import assets, beta
from script.release.beta import DEFAULT_IDENTITY, publish_beta_files
from tools.cli.release import app_update


def _runtime_repo(root: Path) -> Path:
    for relative in (
        "tools/cli/pyproject.toml",
        "tools/cli/tools/app.py",
        "tools/cli/agent-harness/pyproject.toml",
        "tools/cli/agent-harness/cli_anything/harness.py",
        "client-adapters/vibe-trading/adapter.py",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative)
    return root


def test_runtime_cache_key_ignores_swift_and_changes_for_cli(tmp_path: Path) -> None:
    repo = _runtime_repo(tmp_path / "repo")
    first = assets.runtime_input_digest(repo)
    swift = repo / "apple/Sources/View.swift"
    swift.parent.mkdir(parents=True)
    swift.write_text("struct View {}")
    assert assets.runtime_input_digest(repo) == first
    docs = repo / "tools/cli/docs/guide.md"
    docs.parent.mkdir()
    docs.write_text("changed documentation")
    tests = repo / "tools/cli/tests/test_app.py"
    tests.parent.mkdir()
    tests.write_text("changed test")
    assert assets.runtime_input_digest(repo) == first
    (repo / "tools/cli/tools/app.py").write_text("changed")
    assert assets.runtime_input_digest(repo) != first


def test_cached_runtime_is_reused_with_a_fresh_release_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _runtime_repo(tmp_path / "repo")
    cache = tmp_path / "cache"
    key = assets.runtime_input_digest(repo)
    frozen = cache / key / "bin/factortester"
    frozen.parent.mkdir(parents=True)
    frozen.write_bytes(b"cached executable")
    harness = cache / key / "bin/cli-anything-factortester-research"
    harness.write_bytes(b"cached executable")
    adapter = cache / key / "adapters/vibe-trading-adapter.zip"
    adapter.parent.mkdir()
    adapter.write_bytes(b"cached adapter")
    assets._write_cache_descriptor(cache / key, key)
    app = tmp_path / "FTClient.app"

    monkeypatch.setattr(
        assets.subprocess, "run",
        lambda *_args, **_kwargs: pytest.fail("cache hit rebuilt runtime"),
    )
    receipt = assets.embed_client_runtime(
        repo, app, version="bundle-b2-r" + "a" * 40,
        source_revision="a" * 40, cache_dir=cache,
    )

    value = json.loads(receipt.read_text())
    assert value["runtime_input_sha256"] == key
    assert value["source_revision"] == "a" * 40
    assert (
        app / "Contents/Resources/FactorTester/bin/factortester"
    ).read_bytes() == b"cached executable"


def test_beta_publish_writes_digest_asset_before_atomic_manifest(
    tmp_path: Path,
) -> None:
    dmg = tmp_path / "release.dmg"
    dmg.write_bytes(b"new beta")
    digest = sha256(dmg.read_bytes()).hexdigest()
    root = tmp_path / "channels"
    root.mkdir()
    (root / "beta.json").write_text('{"old":true}\n')
    manifest = {"schema_version": 1, "sha256": digest}

    asset, channel = publish_beta_files(
        dmg=dmg, manifest=manifest, release_root=root,
    )

    assert asset == root / "assets/beta" / f"{digest}.dmg"
    assert asset.read_bytes() == b"new beta"
    assert json.loads(channel.read_text()) == manifest
    assert not list(root.rglob("*.staging"))


def test_manifest_failure_keeps_old_channel_but_retains_safe_asset(
    tmp_path: Path, monkeypatch,
) -> None:
    dmg = tmp_path / "release.dmg"
    dmg.write_bytes(b"new beta")
    root = tmp_path / "channels"
    root.mkdir()
    channel = root / "beta.json"
    channel.write_text('{"old":true}\n')
    monkeypatch.setattr(
        beta, "write_update_manifest",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("signing write failed")
        ),
    )
    with pytest.raises(RuntimeError, match="signing write"):
        publish_beta_files(
            dmg=dmg, manifest={"schema_version": 1}, release_root=root,
        )
    assert json.loads(channel.read_text()) == {"old": True}
    assert len(list((root / "assets/beta").glob("*.dmg"))) == 1


def test_publisher_behavior_never_calls_client_installer(
    tmp_path: Path, monkeypatch,
) -> None:
    called = False

    def forbidden(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("publisher invoked client installer")

    monkeypatch.setattr(app_update, "atomic_replace_application", forbidden)
    dmg = tmp_path / "release.dmg"
    dmg.write_bytes(b"publisher only")
    publish_beta_files(
        dmg=dmg,
        manifest={"schema_version": 1},
        release_root=tmp_path / "channel",
    )
    assert called is False


def test_beta_release_identity_is_stable_and_not_adhoc() -> None:
    assert DEFAULT_IDENTITY == "FTClient Beta Release"
    assert DEFAULT_IDENTITY != "-"
    publisher = (
        Path(__file__).resolve().parents[2] / "script/release/beta.py"
    ).read_text()
    assert "/Applications" not in publisher
    assert "update_application" not in publisher


def test_client_updater_has_no_build_sign_or_publish_authority() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "tools/cli/release/app_update.py"
    ).read_text()
    for forbidden in ("xcodebuild", "xcodegen", "--sign", "beta.json"):
        assert forbidden not in source


def test_incomplete_or_corrupt_runtime_cache_is_rejected(tmp_path: Path) -> None:
    cached = tmp_path / "cache"
    cli = cached / "bin/factortester"
    cli.parent.mkdir(parents=True)
    cli.write_bytes(b"only one executable")
    assert assets._valid_runtime_cache(cached, "a" * 64) is False
    harness = cached / "bin/cli-anything-factortester-research"
    harness.write_bytes(b"harness")
    adapter = cached / "adapters/vibe-trading-adapter.zip"
    adapter.parent.mkdir()
    adapter.write_bytes(b"adapter")
    assets._write_cache_descriptor(cached, "a" * 64)
    cli.write_bytes(b"corrupt")
    assert assets._valid_runtime_cache(cached, "a" * 64) is False


def test_update_requires_an_existing_app_with_same_identity(
    tmp_path: Path, monkeypatch,
) -> None:
    candidate = tmp_path / "candidate.app"
    candidate.mkdir()
    with pytest.raises(ValueError, match="initial install"):
        app_update._require_installed_identity(
            candidate, tmp_path / "Applications/FTClient.app"
        )
    installed = tmp_path / "Applications/FTClient.app"
    installed.mkdir(parents=True)
    requirements = {
        candidate: "designated => anchor candidate",
        installed: "designated => anchor installed",
    }
    monkeypatch.setattr(
        app_update, "_designated_requirement", requirements.__getitem__,
    )
    with pytest.raises(ValueError, match="identity differs"):
        app_update._require_installed_identity(candidate, installed)


def test_runtime_preflight_requires_both_commands_and_adapter(
    tmp_path: Path,
) -> None:
    app = tmp_path / "FTClient.app"
    root = app / "Contents/Resources/FactorTester"
    cli = root / "bin/factortester"
    cli.parent.mkdir(parents=True)
    cli.write_bytes(b"cli")
    cli.chmod(0o755)
    receipt = root / "bundle-receipt.json"
    receipt.write_text(json.dumps({
        "files": {"bin/factortester": sha256(b"cli").hexdigest()}
    }))
    with pytest.raises(ValueError, match="incomplete"):
        app_update._validate_embedded_runtime(app)


def _fake_app(root: Path, payload: bytes) -> Path:
    app = root / "FTClient.app"
    for relative in (
        "Contents/Info.plist",
        "Contents/Resources/FactorTester/bundle-receipt.json",
        "Contents/Resources/FactorTester/bin/factortester",
    ):
        path = app / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    return app


def test_client_atomic_replace_rolls_back_and_keeps_backup_outside_applications(
    tmp_path: Path,
    monkeypatch,
) -> None:
    applications = tmp_path / "Applications"
    installed = _fake_app(applications, b"old")
    candidate = _fake_app(tmp_path / "download", b"new")
    backup_root = tmp_path / "Application Support/backups"
    calls = 0

    def verify(_source, _target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("post-install verification failed")

    monkeypatch.setattr(app_update, "_verify_same_app", verify)
    with pytest.raises(ValueError, match="post-install"):
        app_update.atomic_replace_application(
            candidate, application=installed, backup_root=backup_root,
        )

    assert (
        installed / "Contents/Resources/FactorTester/bin/factortester"
    ).read_bytes() == b"old"
    assert not list(applications.glob(".*.staging-*"))
    assert not list(applications.glob("*backup*"))


def test_client_replace_behavior_never_calls_signer_or_publisher(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setattr(app_update, "_verify_same_app", lambda *_: None)
    monkeypatch.setattr(
        beta, "_sign_embedded_app",
        lambda *_args, **_kwargs: pytest.fail("client invoked signer"),
    )
    monkeypatch.setattr(
        beta, "publish_beta_files",
        lambda *_args, **_kwargs: pytest.fail("client invoked publisher"),
    )
    installed = _fake_app(tmp_path / "Applications", b"old")
    candidate = _fake_app(tmp_path / "download", b"new")
    backup = app_update.atomic_replace_application(
        candidate,
        application=installed,
        backup_root=tmp_path / "Application Support/backups",
    )
    assert backup is not None
    assert (
        installed / "Contents/Resources/FactorTester/bin/factortester"
    ).read_bytes() == b"new"
