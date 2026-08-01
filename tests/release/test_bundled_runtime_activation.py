from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from tools.cli.app import cli
from tools.cli.release import bundle_runtime
from tools.cli.release.bundle_runtime import activate_bundled_runtime
from tools.cli.release.transaction import ClientReleaseStore


REVISION = "a" * 40


def _bundle(root: Path, version: str, *, payload: bytes = b"runtime") -> Path:
    resources = root / version / "FactorTester"
    binary = b"\xcf\xfa\xed\xfe" + payload
    files = {}
    for command in bundle_runtime.COMMANDS:
        path = resources / "bin" / command
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(binary)
        path.chmod(0o755)
        files[f"bin/{command}"] = sha256(binary).hexdigest()
    skill = resources / "skills/factortester-research-skill/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: factortester-research-skill\n"
        "description: Test skill.\n---\n\n# Test\n",
        encoding="utf-8",
    )
    files["skills/factortester-research-skill/SKILL.md"] = sha256(
        skill.read_bytes()
    ).hexdigest()
    (resources / "bundle-receipt.json").write_text(json.dumps({
        "schema_version": 1,
        "version": version,
        "source_revision": REVISION,
        "files": files,
    }))
    return resources


def test_bundle_activation_is_hash_verified_atomic_and_idempotent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    resources = _bundle(tmp_path / "bundles", "2.0.0")
    root = tmp_path / "support"
    copied = 0
    original = bundle_runtime._copy_durable

    def counted(source: Path, target: Path) -> None:
        nonlocal copied
        copied += 1
        original(source, target)

    monkeypatch.setattr(bundle_runtime, "_copy_durable", counted)
    skill_root = tmp_path / "agent-skills"
    first = activate_bundled_runtime(
        resources, root, local_skill_root=skill_root,
    )
    pointer_before = (root / "current.json").read_bytes()
    target = root / "releases" / "2.0.0"
    receipt_before = (target / "receipt.json").read_bytes()
    inodes = {
        command: (
            target / "runtime" / "standalone" / "bin" / command
        ).stat().st_ino
        for command in bundle_runtime.COMMANDS
    }

    second = activate_bundled_runtime(
        resources, root, local_skill_root=skill_root,
    )

    assert first["activated"] is True
    assert second["activated"] is False
    assert copied == 2
    assert (root / "current.json").read_bytes() == pointer_before
    assert (target / "receipt.json").read_bytes() == receipt_before
    assert inodes == {
        command: (
            target / "runtime" / "standalone" / "bin" / command
        ).stat().st_ino
        for command in bundle_runtime.COMMANDS
    }
    assert (
        skill_root / "factortester-research-skill/SKILL.md"
    ).read_bytes() == (
        resources / "skills/factortester-research-skill/SKILL.md"
    ).read_bytes()
    launcher = (root / "bin" / "factortester").read_text()
    assert "'standalone/bin'" in launcher
    assert "'python/bin'" in launcher

    (root / "bin" / "factortester").write_text("tampered")
    registered = skill_root / "factortester-research-skill/SKILL.md"
    registered.write_text("stale", encoding="utf-8")
    pointer_before_repair = (root / "current.json").read_bytes()
    repaired = activate_bundled_runtime(
        resources, root, local_skill_root=skill_root,
    )
    assert repaired["activated"] is True
    assert copied == 2
    assert (root / "current.json").read_bytes() == pointer_before_repair
    assert "'standalone/bin'" in (
        root / "bin" / "factortester"
    ).read_text()
    assert registered.read_bytes() == (
        resources / "skills/factortester-research-skill/SKILL.md"
    ).read_bytes()


def test_bundle_identity_hash_and_installed_tamper_fail_closed(
    tmp_path: Path,
) -> None:
    resources = _bundle(tmp_path / "bundles", "2.0.0")
    root = tmp_path / "support"
    factortester = resources / "bin" / "factortester"
    factortester.write_bytes(b"\xcf\xfa\xed\xfetampered")
    with pytest.raises(ValueError, match="checksum"):
        activate_bundled_runtime(resources, root)
    assert not (root / "current.json").exists()

    resources = _bundle(tmp_path / "bundles-2", "2.0.0")
    activate_bundled_runtime(resources, root)
    installed = (
        root / "releases" / "2.0.0"
        / "runtime" / "standalone" / "bin" / "factortester"
    )
    installed.write_bytes(b"\xcf\xfa\xed\xfetampered")
    pointer = (root / "current.json").read_bytes()
    with pytest.raises(ValueError, match="tampered"):
        activate_bundled_runtime(resources, root)
    assert (root / "current.json").read_bytes() == pointer

    invalid = _bundle(tmp_path / "invalid", "3.0.0")
    receipt_path = invalid / "bundle-receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["source_revision"] = "not-a-revision"
    receipt_path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="source revision"):
        activate_bundled_runtime(invalid, tmp_path / "invalid-support")


def test_bundle_identity_accepts_executable_script_launcher(
    tmp_path: Path,
) -> None:
    launcher = tmp_path / "cli-anything-factortester-research"
    launcher.write_bytes(b"#!/bin/sh\nexec \"$0.real\" \"$@\"\n")
    launcher.chmod(0o755)

    bundle_runtime._verify_source_identity(launcher)


@pytest.mark.parametrize("failure_point", ["before_publish", "before_pointer"])
def test_bundle_activation_crash_never_changes_pointer_early(
    tmp_path: Path,
    failure_point: str,
) -> None:
    first = _bundle(tmp_path / "bundles", "1.0.0", payload=b"first")
    second = _bundle(tmp_path / "bundles", "2.0.0", payload=b"second")
    root = tmp_path / "support"
    activate_bundled_runtime(first, root)
    original = (root / "current.json").read_bytes()

    def fail(name: str) -> None:
        if name == failure_point:
            raise RuntimeError("simulated crash")

    with pytest.raises(RuntimeError, match="simulated crash"):
        activate_bundled_runtime(second, root, checkpoint=fail)
    assert (root / "current.json").read_bytes() == original

    result = activate_bundled_runtime(second, root)
    assert result["current_version"] == "2.0.0"
    assert json.loads((root / "current.json").read_text())["version"] == "2.0.0"


def test_bundle_runtime_prunes_previous_release_after_switch(
    tmp_path: Path,
) -> None:
    first = _bundle(tmp_path / "bundles", "1.0.0", payload=b"first")
    second = _bundle(tmp_path / "bundles", "2.0.0", payload=b"second")
    root = tmp_path / "support"
    activate_bundled_runtime(first, root)
    legacy_cache = root / "release-runtime" / "old-cache"
    legacy_cache.mkdir(parents=True)
    account_state = root / "account" / "session.json"
    account_state.parent.mkdir(parents=True)
    account_state.write_text('{"keep_login":true}')
    profile_state = root / "profiles" / "maxa.json"
    profile_state.parent.mkdir(parents=True)
    profile_state.write_text('{"profile":"maxa"}')
    activate_bundled_runtime(second, root)

    status = ClientReleaseStore(root).status()
    assert status["current_version"] == "2.0.0"
    assert status["installed_versions"] == ["2.0.0"]
    assert not (root / "releases" / "1.0.0").exists()
    assert (root / "releases" / "2.0.0" / "receipt.json").is_file()
    assert not (root / "release-runtime").exists()
    assert account_state.read_text() == '{"keep_login":true}'
    assert profile_state.read_text() == '{"profile":"maxa"}'
    with pytest.raises(ValueError, match="rollback target is not installed"):
        ClientReleaseStore(root).rollback()


def test_hidden_cli_activation_command_uses_no_profile_or_network(
    tmp_path: Path,
) -> None:
    resources = _bundle(tmp_path / "bundles", "2.0.0")
    root = tmp_path / "support"
    result = CliRunner().invoke(cli, [
        "client",
        "activate-bundle",
        "--bundle-resources",
        str(resources),
        "--client-root",
        str(root),
        "--local-skill-root",
        str(tmp_path / "agent-skills"),
        "--json",
    ])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["current_version"] == "2.0.0"
    assert not (root / "profiles").exists()
