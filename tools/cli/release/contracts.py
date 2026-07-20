"""Strict release-manifest schema and compatibility checks."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse

from tools.cli.protocol import (
    CLIENT_PROTOCOL_CURRENT,
    CLIENT_PROTOCOL_MINIMUM,
)

from .signature import verify_ecdsa_sha256


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
_ASSET_KINDS = {
    "python-wheel",
    "macos-app",
    "harness-wheel",
    "adapter-archive",
}


@dataclass(frozen=True, slots=True)
class ReleaseAsset:
    asset_id: str
    kind: str
    filename: str
    url: str
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class ValidatedRelease:
    release_id: str
    version: str
    source_revision: str
    manifest_hash: str
    assets: tuple[ReleaseAsset, ...]


def canonical_unsigned_manifest(manifest: dict[str, Any]) -> bytes:
    unsigned = dict(manifest)
    unsigned.pop("signature", None)
    return json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def validate_release_manifest(
    manifest: dict[str, Any],
    *,
    public_key: Path,
) -> ValidatedRelease:
    if set(manifest) != {
        "schema_version",
        "release",
        "client_protocol",
        "assets",
        "signature",
    }:
        raise ValueError("release manifest fields are invalid")
    if manifest.get("schema_version") != 1:
        raise ValueError("release manifest schema_version is unsupported")
    payload = canonical_unsigned_manifest(manifest)
    signature = _object(manifest.get("signature"), "signature")
    if set(signature) != {"algorithm", "key_id", "value"}:
        raise ValueError("release signature fields are invalid")
    if signature.get("algorithm") != "ecdsa-sha256":
        raise ValueError("release signature algorithm is unsupported")
    expected_key_id = sha256(public_key.read_bytes()).hexdigest()
    if signature.get("key_id") != expected_key_id:
        raise ValueError("release signature key ID is not trusted")
    verify_ecdsa_sha256(
        payload,
        str(signature.get("value") or ""),
        public_key=public_key,
    )

    release = _object(manifest.get("release"), "release")
    if set(release) != {"id", "version", "source_revision"}:
        raise ValueError("release fields are invalid")
    release_id = _text(release.get("id"), "release.id")
    version = _text(release.get("version"), "release.version")
    if not _VERSION.fullmatch(version):
        raise ValueError("release.version must be semantic version")
    source_revision = _text(
        release.get("source_revision"), "release.source_revision"
    )
    if not _REVISION.fullmatch(source_revision):
        raise ValueError("release.source_revision must be a Git commit")

    protocol = _object(manifest.get("client_protocol"), "client_protocol")
    if set(protocol) != {"minimum", "maximum"}:
        raise ValueError("client_protocol fields are invalid")
    minimum = _positive_int(protocol.get("minimum"), "client_protocol.minimum")
    maximum = _positive_int(protocol.get("maximum"), "client_protocol.maximum")
    if minimum > maximum or (
        CLIENT_PROTOCOL_CURRENT < minimum
        or maximum < CLIENT_PROTOCOL_MINIMUM
    ):
        raise ValueError("release client protocol is incompatible")

    assets_value = manifest.get("assets")
    if not isinstance(assets_value, list) or not assets_value:
        raise ValueError("release assets must be a non-empty list")
    assets = tuple(_asset(item) for item in assets_value)
    if len({item.asset_id for item in assets}) != len(assets):
        raise ValueError("release asset IDs must be unique")
    if len({item.filename for item in assets}) != len(assets):
        raise ValueError("release asset filenames must be unique")
    return ValidatedRelease(
        release_id=release_id,
        version=version,
        source_revision=source_revision,
        manifest_hash=sha256(payload).hexdigest(),
        assets=assets,
    )


def _asset(value: Any) -> ReleaseAsset:
    item = _object(value, "asset")
    if set(item) != {"id", "kind", "filename", "url", "sha256", "size"}:
        raise ValueError("release asset fields are invalid")
    kind = _text(item.get("kind"), "asset.kind")
    if kind not in _ASSET_KINDS:
        raise ValueError(f"release asset kind is unsupported: {kind}")
    filename = _text(item.get("filename"), "asset.filename")
    if Path(filename).name != filename or filename in {".", ".."}:
        raise ValueError("release asset filename is unsafe")
    digest = _text(item.get("sha256"), "asset.sha256")
    if not _SHA256.fullmatch(digest):
        raise ValueError("release asset sha256 is invalid")
    url = _text(item.get("url"), "asset.url")
    if urlparse(url).scheme not in {"https", "file"}:
        raise ValueError("release asset URL must use https")
    size = _positive_int(item.get("size"), "asset.size")
    return ReleaseAsset(
        asset_id=_text(item.get("id"), "asset.id"),
        kind=kind,
        filename=filename,
        url=url,
        sha256=digest,
        size=size,
    )


def _object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def _text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value
