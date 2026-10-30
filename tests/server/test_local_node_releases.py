from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from server.manager.http.client_release_routes import ClientReleaseRoutesMixin
from server.services.local_node_releases import (
    LocalNodeReleaseCatalog,
    canonical_unsigned_catalog,
)


def _signed_release(root: Path, *, payload: bytes = b"local runtime") -> tuple[Path, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    public_path = root / "trusted.pem"
    public_bytes = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_path.write_bytes(public_bytes)
    digest = hashlib.sha256(payload).hexdigest()
    catalog: dict[str, object] = {
        "schema_version": 1,
        "packages": [{
            "platform": "windows-x86_64", "version": "1.2.3",
            "sha256": digest, "size_bytes": len(payload),
        }],
    }
    signature = key.sign(canonical_unsigned_catalog(catalog), ec.ECDSA(hashes.SHA256()))
    catalog["signature"] = {
        "algorithm": "ecdsa-sha256",
        "key_id": hashlib.sha256(public_bytes).hexdigest(),
        "value": base64.b64encode(signature).decode("ascii"),
    }
    (root / "local-node").mkdir(parents=True)
    (root / "local-node" / "index.json").write_text(json.dumps(catalog))
    asset_dir = root / "assets" / "local-node" / "windows-x86_64"
    asset_dir.mkdir(parents=True)
    (asset_dir / f"{digest}.tar.zst").write_bytes(payload)
    return public_path, digest


def test_signed_catalog_is_cached_and_asset_hash_is_verified(tmp_path: Path) -> None:
    public = tmp_path / "release" / "trusted.pem"
    public.parent.mkdir()
    public, digest = _signed_release(public.parent)
    releases = LocalNodeReleaseCatalog(public.parent, public)

    assert releases.package("windows-x86_64") == {
        "platform": "windows-x86_64", "version": "1.2.3",
        "sha256": digest, "size_bytes": len(b"local runtime"),
    }
    assert releases.asset("windows-x86_64", digest).is_file()
    assert releases.package("macos-arm64") is None

    asset = releases.asset("windows-x86_64", digest)
    # Keep the signed size unchanged so this specifically exercises the
    # content-digest check rather than the earlier size validation.
    asset.write_bytes(b"tampered run!")
    with pytest.raises(ValueError, match="digest"):
        releases.asset("windows-x86_64", digest)


def test_local_node_catalog_rejects_untrusted_or_unsafe_metadata(tmp_path: Path) -> None:
    public, _digest = _signed_release(tmp_path)
    index = tmp_path / "local-node" / "index.json"
    index.write_text('{"schema_version":1,"packages":[],"signature":{}}')
    with pytest.raises(ValueError, match="signature"):
        LocalNodeReleaseCatalog(tmp_path, public).package("windows-x86_64")
    with pytest.raises(ValueError, match="platform"):
        LocalNodeReleaseCatalog(tmp_path, public).package("../private")


class _FakeReleaseHandler(ClientReleaseRoutesMixin):
    def __init__(self, tmp_path: Path, *, roles: tuple[str, ...] = ()) -> None:
        from io import BytesIO

        self.state = SimpleNamespace(
            runtime_source_root=tmp_path,
            release_root=tmp_path / "releases",
        )
        self._roles = roles
        self.command = "GET"
        self.path = ""
        self.headers = {}
        self.responses: list[tuple[int, str, str]] = []
        self.wfile = BytesIO()

    def _session(self):
        return {"keycloak_roles": self._roles}

    def send_response(self, status: int) -> None:
        self._status = status

    def send_header(self, key: str, value: str) -> None:
        self.responses.append((self._status, key, value))

    def end_headers(self) -> None:
        return


def test_local_node_download_requires_keycloak_role_and_reports_missing_package(tmp_path: Path) -> None:
    handler = _FakeReleaseHandler(tmp_path)
    handler.path = "/api/local-node/releases?platform=windows-x86_64"
    handled = handler._serve_client_release("/api/local-node/releases")
    assert handled
    assert handler._status == 403

    handler = _FakeReleaseHandler(tmp_path, roles=("desktop_local_node:download",))
    handler.path = "/api/local-node/releases?platform=windows-x86_64"
    handled = handler._serve_client_release("/api/local-node/releases")
    assert handled
    assert handler._status == 200
    assert json.loads(handler.wfile.getvalue()) == {
        "success": True, "authorized": True,
        "available": False, "platform": "windows-x86_64",
        "reason": "not-published",
    }


@pytest.mark.parametrize("path", [
    "/api/local-node/register", "/api/local-node/jobs", "/api/local-node/dispatch",
])
def test_local_desktop_node_has_no_manager_registration_or_dispatch_route(
    tmp_path: Path, path: str,
) -> None:
    handler = _FakeReleaseHandler(tmp_path, roles=("desktop_local_node:download",))
    handler.path = path
    assert not handler._serve_client_release(path)
