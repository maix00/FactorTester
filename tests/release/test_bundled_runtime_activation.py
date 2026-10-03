from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess

import pytest
from click.testing import CliRunner

from tools.cli.app import cli
from tools.cli.commands import client_release
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
    source = resources / "sources/Tiger/source.json"
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps({
        "schema_version": 1,
        "managed_by": "factortester-client",
        "source_id": "Tiger",
        "source_name": "Tiger",
        "source_kind": "external_connector",
        "provider_kind": "live_connector",
        "version": "0.2.0",
        "connector": {
            "entrypoint": "connector.py",
            "probe_mode": "explicit",
            "credential_store": "keychain",
        },
        "availability": {
            "status": "not_probed",
            "available_product_refs": [],
        },
        "members": [{
            "id": "TigerOSEFuturesL2",
            "label": "Tiger OSE Futures L2",
            "timezone": "Asia/Tokyo",
            "time_columns": {},
            "data_columns": {},
            "data_mode": {
                "id": "realtime_l2",
                "title_zh": "实时 L2 行情",
                "available": True,
                "sampling_mode": "snapshot",
                "frequency": None,
                "data_kind": "order_book",
                "market_depth": "l2",
                "delivery_mode": "live_stream",
            },
        }],
        "categories": [{
            "id": "exchange",
            "alias": "交易所",
            "title_zh": "交易所",
            "dimensions": ["exchange"],
            "composable": True,
            "is_composite": False,
        }],
        "products": [{
            "product_ref": "product:tiger:JNI.OSE",
            "alias": "JNI.OSE",
            "display_name": "OSE Nikkei 225",
            "class_path": "Product/Futures/JPFutures",
            "category_values": {"exchange": ["OSE"]},
            "product_kind": "continuous_contract",
            "metadata": {"tiger_identifier": "JNImain"},
        }],
    }), encoding="utf-8")
    connector = source.with_name("connector.py")
    connector.write_text("# managed local connector\n", encoding="utf-8")
    for path in (source, connector):
        files[path.relative_to(resources).as_posix()] = sha256(
            path.read_bytes()
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
        local_source_root=tmp_path / "local-sources",
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
        local_source_root=tmp_path / "local-sources",
    )

    assert first["activated"] is True
    assert second["activated"] is False
    assert copied == len(bundle_runtime.COMMANDS)
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
    assert launcher.startswith("#!/bin/sh\n")
    assert "/runtime/standalone/bin/factortester" in launcher
    assert "/runtime/python/bin/factortester" in launcher
    assert "python3" not in launcher
    environment = (root / "bin" / "factortester-env.sh").read_text()
    assert "FACTORTESTER_CLI=" in environment
    assert "FACTORTESTER_MANAGER_CLI=" in environment
    assert "FACTORTESTER_CLIENT_BIN=" in environment

    (root / "bin" / "factortester").write_text("tampered")
    registered = skill_root / "factortester-research-skill/SKILL.md"
    registered.write_text("stale", encoding="utf-8")
    pointer_before_repair = (root / "current.json").read_bytes()
    repaired = activate_bundled_runtime(
        resources, root, local_skill_root=skill_root,
        local_source_root=tmp_path / "local-sources",
    )
    assert repaired["activated"] is True
    assert copied == len(bundle_runtime.COMMANDS)
    assert (root / "current.json").read_bytes() == pointer_before_repair
    assert "/runtime/standalone/bin/factortester" in (
        root / "bin" / "factortester"
    ).read_text()
    assert registered.read_bytes() == (
        resources / "skills/factortester-research-skill/SKILL.md"
    ).read_bytes()
    assert (
        tmp_path / "local-sources/Tiger/source.json"
    ).read_bytes() == (resources / "sources/Tiger/source.json").read_bytes()


def test_bundle_activation_preserves_unrelated_user_sources(tmp_path: Path) -> None:
    resources = _bundle(tmp_path / "bundles", "2.0.0")
    source_root = tmp_path / "local-sources"
    user_source = source_root / "PrivateFeed"
    user_source.mkdir(parents=True)
    user_manifest = user_source / "source.json"
    user_manifest.write_text('{"owner":"user"}\n', encoding="utf-8")

    activate_bundled_runtime(
        resources,
        tmp_path / "support",
        local_source_root=source_root,
    )

    assert user_manifest.read_text(encoding="utf-8") == '{"owner":"user"}\n'
    assert (source_root / "Tiger/source.json").is_file()


def test_environment_script_exposes_active_app_commands(tmp_path: Path) -> None:
    resources = _bundle(tmp_path / "bundles", "2.0.0")
    root = tmp_path / "support"
    activate_bundled_runtime(
        resources,
        root,
        local_source_root=tmp_path / "local-sources",
    )

    environment = root / "bin" / "factortester-env.sh"
    result = subprocess.run(
        [
            "sh",
            "-c",
            "source_path=$1; . \"$source_path\"; "
            "printf '%s\\n' \"$FACTORTESTER_CLI\" "
            "\"$FACTORTESTER_MANAGER_CLI\" \"$FACTORTESTER_CLIENT_BIN\" "
            "\"$PATH\"",
            "sh",
            str(environment),
        ],
        capture_output=True,
        check=True,
        text=True,
    )
    values = result.stdout.splitlines()
    assert values[:3] == [
        str(root / "bin" / "factortester"),
        str(root / "bin" / "factortester-manager"),
        str(root / "bin"),
    ]
    assert values[3].split(":", 1)[0] == str(root / "bin")


def test_bundle_activation_rejects_generated_source_cache(tmp_path: Path) -> None:
    resources = _bundle(tmp_path / "bundles", "2.0.0")
    generated = resources / "sources/Tiger/__pycache__/connector.pyc"
    generated.parent.mkdir()
    generated.write_bytes(b"generated bytecode")
    receipt = json.loads((resources / "bundle-receipt.json").read_text())
    receipt["files"][generated.relative_to(resources).as_posix()] = sha256(
        generated.read_bytes()
    ).hexdigest()
    (resources / "bundle-receipt.json").write_text(json.dumps(receipt))

    with pytest.raises(ValueError, match="generated cache"):
        activate_bundled_runtime(
            resources,
            tmp_path / "support",
            local_source_root=tmp_path / "local-sources",
        )

    assert not (tmp_path / "local-sources/Tiger").exists()


def test_bundle_activation_rejects_user_owned_source_name_before_pointer(
    tmp_path: Path,
) -> None:
    resources = _bundle(tmp_path / "bundles", "2.0.0")
    source_root = tmp_path / "local-sources"
    collision = source_root / "Tiger"
    collision.mkdir(parents=True)
    (collision / "source.json").write_text(
        '{"owner":"user"}\n', encoding="utf-8",
    )
    runtime_root = tmp_path / "support"

    with pytest.raises(ValueError, match="belongs to the user"):
        activate_bundled_runtime(
            resources,
            runtime_root,
            local_source_root=source_root,
        )

    assert not (runtime_root / "current.json").exists()


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
    launcher = tmp_path / "factortester-manager"
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
    monkeypatch,
) -> None:
    resources = _bundle(tmp_path / "bundles", "2.0.0")
    root = tmp_path / "support"
    monkeypatch.setattr(
        client_release,
        "default_local_sources_root",
        lambda: tmp_path / "local-sources",
    )
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
    assert (tmp_path / "local-sources/Tiger/source.json").is_file()
