from __future__ import annotations

import base64
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import zipfile

import pytest

from tools.cli.release.adapters.archive import install_adapter_archive
from tools.cli.release.adapters.manager import ClientAdapterManager
from tools.cli.release.contracts import canonical_unsigned_manifest
from tools.cli.release.transaction import ClientReleaseStore

from .test_release_manifest import _keys, signed_manifest


def _write_executable(
    archive: zipfile.ZipFile,
    path: str,
    body: str,
) -> None:
    info = zipfile.ZipInfo(path)
    info.external_attr = 0o100755 << 16
    archive.writestr(info, body)


def _adapter_archive(path: Path) -> bytes:
    contract = {
        "schema_version": 1,
        "adapter_id": "synthetic-ui",
        "version": "1.0.0",
        "display_name": "Synthetic UI",
        "ui": {"kind": "web", "url": "http://127.0.0.1:7899"},
        "actions": {
            "health": {
                "argv": ["bin/health"],
                "mode": "foreground",
                "timeout_seconds": 2,
            },
            "start": {
                "argv": ["bin/start"],
                "mode": "background",
                "timeout_seconds": 2,
            },
            "stop": {
                "argv": ["bin/stop"],
                "mode": "foreground",
                "timeout_seconds": 2,
            },
            "open": {
                "argv": ["bin/open"],
                "mode": "foreground",
                "timeout_seconds": 2,
            },
        },
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("adapter.json", json.dumps(contract))
        _write_executable(
            archive,
            "bin/start",
            "#!/usr/bin/env python3\nimport time\nwhile True: time.sleep(1)\n",
        )
        _write_executable(
            archive,
            "bin/health",
            "#!/usr/bin/env python3\nimport os\n"
            "raise SystemExit(0 if os.environ.get('FACTORTESTER_ADAPTER_PID') else 1)\n",
        )
        _write_executable(
            archive,
            "bin/stop",
            "#!/usr/bin/env python3\nraise SystemExit(0)\n",
        )
        _write_executable(
            archive,
            "bin/open",
            "#!/usr/bin/env python3\nprint('http://127.0.0.1:7899')\n",
        )
    return path.read_bytes()


def _signed_adapter_release(tmp_path: Path) -> tuple[dict, Path]:
    archive = tmp_path / "synthetic-adapter.zip"
    content = _adapter_archive(archive)
    manifest, _ = signed_manifest(
        tmp_path / "manifest",
        version="1.0.0",
        sha256=sha256(content).hexdigest(),
        size=len(content),
        kind="adapter-archive",
        filename=archive.name,
    )
    manifest["assets"][0]["url"] = archive.as_uri()
    private_key, public_key = _keys(tmp_path / "signing")
    payload = tmp_path / "payload.json"
    signature = tmp_path / "signature.bin"
    payload.write_bytes(canonical_unsigned_manifest(manifest))
    subprocess.run(
        [
            "openssl", "dgst", "-sha256", "-sign", str(private_key),
            "-out", str(signature), str(payload),
        ],
        check=True,
        capture_output=True,
    )
    manifest["signature"] = {
        "algorithm": "ecdsa-sha256",
        "key_id": sha256(public_key.read_bytes()).hexdigest(),
        "value": base64.b64encode(signature.read_bytes()).decode(),
    }
    return manifest, public_key


def test_signed_adapter_install_and_lifecycle_are_bounded(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    manifest, public_key = _signed_adapter_release(tmp_path)
    store = ClientReleaseStore(root)
    store.install(
        manifest,
        public_key=public_key,
        allow_file_urls=True,
    )
    manager = ClientAdapterManager(root)

    initial = manager.status("synthetic-ui")
    assert initial["ui_url"] == "http://127.0.0.1:7899"
    assert initial["running"] is False
    assert initial["healthy"] is False
    started = manager.start("synthetic-ui")
    try:
        assert started["running"] is True
        assert started["healthy"] is True
        assert manager.start("synthetic-ui")["running"] is True
        assert manager.open("synthetic-ui")["stdout"].strip().endswith("7899")
    finally:
        stopped = manager.stop("synthetic-ui")
    assert stopped["running"] is False
    assert not (root / "state" / "adapters" / "synthetic-ui.json").exists()


@pytest.mark.parametrize(
    ("name", "external_attr"),
    [
        ("../escape", 0o100644 << 16),
        ("link", 0o120777 << 16),
    ],
)
def test_adapter_archive_rejects_traversal_and_symlink(
    tmp_path: Path,
    name: str,
    external_attr: int,
) -> None:
    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        info = zipfile.ZipInfo(name)
        info.external_attr = external_attr
        archive.writestr(info, "unsafe")
        archive.writestr("adapter.json", "{}")
    with pytest.raises(ValueError, match="unsafe|symlink"):
        install_adapter_archive(archive_path, tmp_path / "adapters")


def test_adapter_hot_path_has_no_database_llm_or_shell_execution() -> None:
    source_root = (
        Path(__file__).resolve().parents[2]
        / "tools" / "cli" / "release" / "adapters"
    )
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in source_root.glob("*.py")
    ).lower()

    assert "sqlite" not in source
    assert "openai" not in source
    assert "anthropic" not in source
    assert "shell=true" not in source
