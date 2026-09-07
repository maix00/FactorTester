from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "scripts" / "server" / "factortester_wireguard_inventory.py"


def _run(*args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *map(str, args)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_cli_generates_owner_only_keys_without_printing_private_material(
    tmp_path,
) -> None:
    signing = tmp_path / "authority"
    node = tmp_path / "node"

    signing_result = _run("generate-signing-key", "--output-dir", signing)
    node_result = _run("generate-node-key", "--output-dir", node)

    assert signing_result.returncode == node_result.returncode == 0
    assert "private" not in signing_result.stdout.lower()
    assert "private" not in node_result.stdout.lower()
    assert (signing / "inventory-signing.key").stat().st_mode & 0o777 == 0o600
    assert (signing / "inventory-signing.pub").stat().st_mode & 0o777 == 0o644
    assert (node / "wireguard.key").stat().st_mode & 0o777 == 0o600
    assert (node / "wireguard.pub").stat().st_mode & 0o777 == 0o644
    wireguard = shutil.which("wg")
    if wireguard:
        derived = subprocess.run(
            [wireguard, "pubkey"],
            input=(node / "wireguard.key").read_text(),
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        assert derived == (node / "wireguard.pub").read_text().strip()


def test_deployment_cli_import_does_not_load_runtime_settings() -> None:
    # Inspect deployment imports in a clean interpreter, without the suite's
    # child-worker database bootstrap preloading scripts.data_dir.
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            (
                "import sys; "
                f"sys.path.insert(0, {str(ROOT)!r}); "
                "import server.deployment.wireguard; "
                "assert 'scripts.data_dir' not in sys.modules"
            ),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_cli_signs_verifies_and_renders_owner_only_node_config(tmp_path) -> None:
    authority = tmp_path / "authority"
    local = tmp_path / "local"
    remote = tmp_path / "remote"
    assert _run("generate-signing-key", "--output-dir", authority).returncode == 0
    assert _run("generate-node-key", "--output-dir", local).returncode == 0
    assert _run("generate-node-key", "--output-dir", remote).returncode == 0
    payload = {
        "schema_version": 1,
        "cluster_id": "factor-test",
        "generation": 1,
        "tunnels": {
            "factortester": {
                "cidr": "10.77.0.0/24",
                "nodes": [
                    {
                        "server_id": "public-a",
                        "interface_address": "10.77.0.1/24",
                        "public_key": (remote / "wireguard.pub").read_text().strip(),
                        "endpoint": "198.51.100.10:51820",
                        "listen_port": 51820,
                        "gateway": True,
                    },
                    {
                        "server_id": "private-a",
                        "interface_address": "10.77.0.3/32",
                        "public_key": (local / "wireguard.pub").read_text().strip(),
                        "gateway_server_id": "public-a",
                    },
                ],
            },
        },
    }
    inventory = tmp_path / "inventory.json"
    signed = tmp_path / "inventory.signed.json"
    config = tmp_path / "federation.conf"
    inventory.write_text(json.dumps(payload), encoding="utf-8")

    sign_result = _run(
        "sign",
        "--inventory", inventory,
        "--signing-key-dir", authority,
        "--output", signed,
    )
    verify_result = _run(
        "verify",
        "--inventory", signed,
        "--trusted-public-key", authority / "inventory-signing.pub",
    )
    render_result = _run(
        "render",
        "--inventory", signed,
        "--trusted-public-key", authority / "inventory-signing.pub",
        "--server-id", "private-a",
        "--tunnel", "factortester",
        "--private-key", local / "wireguard.key",
        "--output", config,
    )

    assert sign_result.returncode == verify_result.returncode == 0
    assert render_result.returncode == 0
    assert signed.stat().st_mode & 0o777 == 0o644
    assert config.stat().st_mode & 0o777 == 0o600
    assert "PrivateKey =" in config.read_text()
    assert (local / "wireguard.key").read_text().strip() not in render_result.stdout
    assert os.linesep not in render_result.stdout.strip()
