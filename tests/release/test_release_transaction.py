from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import subprocess
import zipfile

import pytest

from tools.cli.release.transaction import ClientReleaseStore

from .test_release_manifest import signed_manifest


def _release(
    root: Path,
    *,
    version: str,
) -> tuple[dict, Path]:
    root.mkdir(parents=True, exist_ok=True)
    content = _wheel(version)
    filename = f"factortester-{version}-py3-none-any.whl"
    asset = root / filename
    asset.write_bytes(content)
    manifest, public_key = signed_manifest(
        root,
        version=version,
        sha256=sha256(content).hexdigest(),
        size=len(content),
        filename=filename,
    )
    manifest["assets"][0]["url"] = asset.as_uri()

    # URL is signed, so rebuild the fixture after assigning it.
    from .test_release_manifest import _keys
    from tools.cli.release.contracts import canonical_unsigned_manifest
    import base64
    private_key, public_key = _keys(root / f"keys-{version}")
    payload = root / f"payload-{version}"
    signature = root / f"signature-{version}"
    payload.write_bytes(canonical_unsigned_manifest(manifest))
    subprocess.run(
        [
            "openssl", "dgst", "-sha256", "-sign", str(private_key),
            "-out", str(signature), str(payload),
        ],
        check=True,
        capture_output=True,
    )
    manifest["signature"]["value"] = base64.b64encode(
        signature.read_bytes()
    ).decode("ascii")
    manifest["signature"]["key_id"] = sha256(
        public_key.read_bytes()
    ).hexdigest()
    return manifest, public_key


def _wheel(version: str) -> bytes:
    output = BytesIO()
    dist_info = f"factortester-{version}.dist-info"
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("tools/__init__.py", "")
        archive.writestr("tools/cli/__init__.py", "")
        archive.writestr(
            "tools/cli/app.py",
            "def cli():\n"
            f"    print('fixture client {version}')\n",
        )
        archive.writestr(
            f"{dist_info}/METADATA",
            "Metadata-Version: 2.1\n"
            f"Name: factortester\nVersion: {version}\n",
        )
        archive.writestr(
            f"{dist_info}/WHEEL",
            "Wheel-Version: 1.0\nGenerator: tests\n"
            "Root-Is-Purelib: true\nTag: py3-none-any\n",
        )
        archive.writestr(
            f"{dist_info}/entry_points.txt",
            "[console_scripts]\n"
            "factortester = tools.cli.app:cli\n",
        )
        archive.writestr(f"{dist_info}/RECORD", "")
    return output.getvalue()


def test_install_update_status_and_rollback_are_atomic(
    tmp_path: Path,
) -> None:
    store = ClientReleaseStore(tmp_path / "support")
    first, first_key = _release(
        tmp_path / "first",
        version="1.0.0",
    )
    second, second_key = _release(
        tmp_path / "second",
        version="1.1.0",
    )

    planned = store.plan(first, public_key=first_key)
    assert planned["mutations"]
    assert planned["target_version"] == "1.0.0"
    assert not store.root.exists()
    first_receipt = store.install(
        first,
        public_key=first_key,
        allow_file_urls=True,
    )
    retry = store.install(
        first,
        public_key=first_key,
        allow_file_urls=True,
    )
    assert retry == first_receipt
    assert store.status()["current_version"] == "1.0.0"
    assert first_receipt["materialized"]["python"]["commands"] == [
        "factortester"
    ]
    launcher = store.root / "bin" / "factortester"
    assert subprocess.check_output([launcher], text=True).strip().endswith(
        "1.0.0"
    )

    second_receipt = store.install(
        second,
        public_key=second_key,
        allow_file_urls=True,
    )
    assert second_receipt["previous_version"] == "1.0.0"
    assert store.status()["current_version"] == "1.1.0"
    assert subprocess.check_output([launcher], text=True).strip().endswith(
        "1.1.0"
    )
    assert store.rollback()["current_version"] == "1.0.0"
    assert subprocess.check_output([launcher], text=True).strip().endswith(
        "1.0.0"
    )

    assert (store.root / "releases" / "1.0.0" / "receipt.json").is_file()
    assert (store.root / "releases" / "1.1.0" / "receipt.json").is_file()
    assert not list((store.root / "releases").glob(".staging-*"))
    (
        store.root / "releases" / "1.0.0"
        / "runtime" / "python" / "bin" / "factortester"
    ).unlink()
    assert store.status()["healthy"] is False


def test_failed_asset_verification_preserves_current_pointer(
    tmp_path: Path,
) -> None:
    store = ClientReleaseStore(tmp_path / "support")
    first, first_key = _release(
        tmp_path / "first",
        version="1.0.0",
    )
    store.install(first, public_key=first_key, allow_file_urls=True)
    broken, broken_key = _release(
        tmp_path / "broken",
        version="1.1.0",
    )
    Path(broken["assets"][0]["url"].removeprefix("file://")).write_bytes(
        b"tampered"
    )

    with pytest.raises(ValueError, match="checksum|size"):
        store.install(
            broken,
            public_key=broken_key,
            allow_file_urls=True,
        )

    assert store.status()["current_version"] == "1.0.0"
    pointer = json.loads((store.root / "current.json").read_text())
    assert pointer["version"] == "1.0.0"
    assert not (store.root / "releases" / "1.1.0").exists()


def test_local_status_is_read_only_and_needs_no_database(
    tmp_path: Path,
) -> None:
    root = tmp_path / "support"
    store = ClientReleaseStore(root)

    assert store.status() == {
        "schema_version": 1,
        "install_root": str(root.resolve()),
        "current_version": None,
        "manifest_hash": None,
        "installed_versions": [],
        "healthy": False,
        "receipt": None,
    }
    assert not root.exists()
    sources = " ".join(
        path.read_text(encoding="utf-8")
        for path in (
            Path(__file__).resolve().parents[2] / "tools" / "cli" / "release"
        ).glob("*.py")
    ).lower()
    assert "sqlite" not in sources


@pytest.mark.parametrize("unsafe", ["/", "~", "~/Documents"])
def test_release_store_rejects_broad_mutation_roots(unsafe: str) -> None:
    with pytest.raises(ValueError, match="unsafe client release root"):
        ClientReleaseStore(Path(unsafe).expanduser())
