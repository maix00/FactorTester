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
    first = activate_bundled_runtime(resources, root)
    pointer_before = (root / "current.json").read_bytes()
    target = root / "releases" / "2.0.0"
    receipt_before = (target / "receipt.json").read_bytes()
    inodes = {
        command: (
            target / "runtime" / "standalone" / "bin" / command
        ).stat().st_ino
        for command in bundle_runtime.COMMANDS
    }

    second = activate_bundled_runtime(resources, root)

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
    launcher = (root / "bin" / "factortester").read_text()
    assert "'standalone/bin'" in launcher
    assert "'python/bin'" in launcher

    (root / "bin" / "factortester").write_text("tampered")
    pointer_before_repair = (root / "current.json").read_bytes()
    repaired = activate_bundled_runtime(resources, root)
    assert repaired["activated"] is True
    assert copied == 2
    assert (root / "current.json").read_bytes() == pointer_before_repair
    assert "'standalone/bin'" in (
        root / "bin" / "factortester"
    ).read_text()


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


def test_bundle_runtime_retains_previous_release_for_rollback(
    tmp_path: Path,
) -> None:
    first = _bundle(tmp_path / "bundles", "1.0.0", payload=b"first")
    second = _bundle(tmp_path / "bundles", "2.0.0", payload=b"second")
    root = tmp_path / "support"
    activate_bundled_runtime(first, root)
    activate_bundled_runtime(second, root)

    status = ClientReleaseStore(root).rollback()

    assert status["current_version"] == "1.0.0"
    assert status["healthy"] is True
    assert (root / "releases" / "2.0.0" / "receipt.json").is_file()


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
        "--json",
    ])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["current_version"] == "2.0.0"
    assert not (root / "profiles").exists()
