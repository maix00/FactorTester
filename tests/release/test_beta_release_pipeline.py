from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

from scripts.release import assets, beta
from scripts.release.beta import DEFAULT_IDENTITY, publish_beta_files


def _runtime_repo(root: Path) -> Path:
    for relative in (
        "tools/cli/pyproject.toml",
        "tools/cli/tools/app.py",
        "skills/factortester-research-skill/SKILL.md",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative)
    client = root / "tools/cli"
    (client / "__init__.py").write_text("", encoding="utf-8")
    (client / "pyproject.toml").write_text(
        """
[tool.setuptools]
packages = ["tools.cli"]

[tool.setuptools.package-dir]
"tools.cli" = "."
""",
        encoding="utf-8",
    )
    return root


def _external_client_assets(root: Path) -> tuple[Path, Path]:
    sources = root / "client-sources"
    source = sources / "Tiger/source.json"
    source.parent.mkdir(parents=True)
    source.write_text('{"source_id":"tiger-test"}\n', encoding="utf-8")
    adapters = root / "client-adapters"
    builder = adapters / "vibe-trading/build_archive.py"
    builder.parent.mkdir(parents=True)
    builder.write_text("# external client builder\n", encoding="utf-8")
    return sources, adapters


def test_runtime_cache_key_ignores_swift_and_changes_for_cli(tmp_path: Path) -> None:
    repo = _runtime_repo(tmp_path / "repo")
    sources, adapters = _external_client_assets(tmp_path / "external")
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
    external_first = assets.runtime_input_digest(
        repo, client_sources_root=sources, client_adapters_root=adapters,
    )
    source_file = sources / "Tiger/source.json"
    source_file.write_text('{"source_id":"changed"}\n', encoding="utf-8")
    assert assets.runtime_input_digest(
        repo, client_sources_root=sources, client_adapters_root=adapters,
    ) != external_first


def test_runtime_cache_key_includes_cli_command_modules(tmp_path: Path) -> None:
    repo = _runtime_repo(tmp_path / "repo")
    first = assets.runtime_input_digest(repo)
    command = repo / "tools/cli/commands/client_release.py"
    command.parent.mkdir(parents=True)
    command.write_text("changed command")
    assert assets.runtime_input_digest(repo) != first


def test_runtime_uses_one_frozen_binary_and_a_script_entrypoint() -> None:
    source = (Path(__file__).resolve().parents[2] / "scripts/release/assets.py").read_text()
    assert "RUNTIME_CACHE_SCHEMA = 8" in source
    assert "FACTORTESTER_ENTRYPOINT" in source
    assert '"--collect-data",\n                "tools.cli.release"' in source
    assert "manager_launcher.write_text" in source
    assert "shutil.copy2(\n            bin_dir / \"factortester\"" not in source


def test_cached_runtime_is_reused_with_a_fresh_release_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _runtime_repo(tmp_path / "repo")
    sources, adapters = _external_client_assets(tmp_path / "external")
    cache = tmp_path / "cache"
    key = assets.runtime_input_digest(
        repo, client_sources_root=sources, client_adapters_root=adapters,
    )
    frozen = cache / key / "bin/factortester"
    frozen.parent.mkdir(parents=True)
    frozen.write_bytes(b"cached executable")
    frozen.chmod(0o755)
    manager = cache / key / "bin/factortester-manager"
    manager.write_bytes(b"cached executable")
    manager.chmod(0o755)
    renderer = cache / key / "bin/factortester-report-renderer"
    renderer.write_bytes(b"cached executable")
    renderer.chmod(0o755)
    adapter = cache / key / "adapters/vibe-trading-adapter.zip"
    adapter.parent.mkdir()
    adapter.write_bytes(b"cached adapter")
    skill = cache / key / "skills/factortester-research-skill/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: factortester-research-skill\n---\n")
    cached_source = cache / key / "sources/Tiger/source.json"
    cached_source.parent.mkdir(parents=True)
    cached_source.write_text('{"source_id":"tiger-test"}\n', encoding="utf-8")
    assets._write_cache_descriptor(cache / key, key)
    app = tmp_path / "FTClient.app"

    monkeypatch.setattr(
        assets.subprocess, "run",
        lambda *_args, **_kwargs: pytest.fail("cache hit rebuilt runtime"),
    )
    receipt = assets.embed_client_runtime(
        repo, app, version="bundle-b2-r" + "a" * 40,
        source_revision="a" * 40, cache_dir=cache,
        client_sources_root=sources, client_adapters_root=adapters,
    )

    value = json.loads(receipt.read_text())
    assert value["runtime_input_sha256"] == key
    assert value["source_revision"] == "a" * 40
    assert (
        app / "Contents/Resources/FactorTester/bin/factortester"
    ).read_bytes() == b"cached executable"


def test_runtime_receipt_rejects_short_source_revision(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="full 40-character Git revision"):
        assets.embed_client_runtime(
            tmp_path / "repo",
            tmp_path / "FTClient.app",
            version="bundle-b1-rshort",
            source_revision="fb35e13c",
        )


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


def test_beta_release_identity_is_stable_and_not_adhoc() -> None:
    assert DEFAULT_IDENTITY == "FTClient Beta Release"
    assert DEFAULT_IDENTITY != "-"
    publisher = (
        Path(__file__).resolve().parents[2] / "scripts/release/beta.py"
    ).read_text()
    assert "/Applications" not in publisher
    assert "update_application" not in publisher


def test_cli_has_no_second_application_updater() -> None:
    root = Path(__file__).resolve().parents[2] / "tools/cli/release"
    assert not (root / "app_update.py").exists()
    control = (root / "app_update_control.py").read_text()
    assert "def _update_open_command" in control
    assert 'return ["open", url]' in control
    for forbidden in ("hdiutil", "codesign", "copytree"):
        assert forbidden not in control


def test_incomplete_or_corrupt_runtime_cache_is_rejected(tmp_path: Path) -> None:
    cached = tmp_path / "cache"
    cli = cached / "bin/factortester"
    cli.parent.mkdir(parents=True)
    cli.write_bytes(b"only one executable")
    assert assets._valid_runtime_cache(cached, "a" * 64) is False
    manager = cached / "bin/factortester-manager"
    manager.write_bytes(b"manager")
    manager.chmod(0o755)
    renderer = cached / "bin/factortester-report-renderer"
    renderer.write_bytes(b"renderer")
    adapter = cached / "adapters/vibe-trading-adapter.zip"
    adapter.parent.mkdir()
    adapter.write_bytes(b"adapter")
    assets._write_cache_descriptor(cached, "a" * 64)
    cli.write_bytes(b"corrupt")
    assert assets._valid_runtime_cache(cached, "a" * 64) is False
