"""Signed, provider-neutral client update channel discovery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .signature import verify_ecdsa_sha256


MAX_UPDATE_MANIFEST_BYTES = 64 * 1024
_CHANNELS = {"stable", "beta"}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")


@dataclass(frozen=True, slots=True)
class ValidatedUpdateManifest:
    version: str
    build: int
    channel: str
    dmg_url: str
    dmg_sha256: str
    minimum_client: str
    mandatory: bool
    published_at: str
    manifest_hash: str


def canonical_unsigned_update_manifest(
    manifest: dict[str, Any],
) -> bytes:
    unsigned = dict(manifest)
    unsigned.pop("signature", None)
    return json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def validate_update_manifest(
    manifest: dict[str, Any],
    *,
    public_key: Path,
    expected_channel: str | None = None,
) -> ValidatedUpdateManifest:
    if set(manifest) != {
        "schema_version", "version", "build", "channel", "dmg_url",
        "sha256", "minimum_client", "mandatory", "published_at",
        "signature",
    }:
        raise ValueError("update manifest fields are invalid")
    if manifest.get("schema_version") != 1:
        raise ValueError("update manifest schema_version is unsupported")
    signature = _object(manifest.get("signature"), "signature")
    if set(signature) != {"algorithm", "key_id", "value"}:
        raise ValueError("update manifest signature fields are invalid")
    if signature.get("algorithm") != "ecdsa-sha256":
        raise ValueError("update manifest signature algorithm is unsupported")
    expected_key_id = sha256(public_key.read_bytes()).hexdigest()
    if signature.get("key_id") != expected_key_id:
        raise ValueError("update manifest signature key ID is not trusted")
    payload = canonical_unsigned_update_manifest(manifest)
    verify_ecdsa_sha256(
        payload,
        str(signature.get("value") or ""),
        public_key=public_key,
    )

    version = _version(manifest.get("version"), "version")
    minimum = _version(manifest.get("minimum_client"), "minimum_client")
    build = manifest.get("build")
    if isinstance(build, bool) or not isinstance(build, int) or build < 1:
        raise ValueError("update manifest build must be a positive integer")
    channel = str(manifest.get("channel") or "")
    if channel not in _CHANNELS:
        raise ValueError("update manifest channel is invalid")
    if expected_channel is not None and channel != expected_channel:
        raise ValueError("update manifest channel does not match request")
    dmg_url = str(manifest.get("dmg_url") or "").strip()
    if (
        urlparse(dmg_url).scheme != "https"
        or not urlparse(dmg_url).netloc
        or not urlparse(dmg_url).path.endswith(".dmg")
    ):
        raise ValueError("update manifest dmg_url must be an HTTPS DMG URL")
    digest = str(manifest.get("sha256") or "")
    if not _SHA256.fullmatch(digest):
        raise ValueError("update manifest sha256 is invalid")
    mandatory = manifest.get("mandatory")
    if not isinstance(mandatory, bool):
        raise ValueError("update manifest mandatory must be boolean")
    published_at = str(manifest.get("published_at") or "")
    try:
        timestamp = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("update manifest published_at is invalid") from exc
    if timestamp.tzinfo is None:
        raise ValueError("update manifest published_at must include timezone")
    return ValidatedUpdateManifest(
        version=version,
        build=build,
        channel=channel,
        dmg_url=dmg_url,
        dmg_sha256=digest,
        minimum_client=minimum,
        mandatory=mandatory,
        published_at=published_at,
        manifest_hash=sha256(payload).hexdigest(),
    )


def resolve_update_manifest(
    *,
    server_manifest_url: str | None,
    github_manifest_url: str,
    channel: str,
    public_key: Path,
    opener=urlopen,
) -> tuple[dict[str, Any], ValidatedUpdateManifest, str]:
    """Try server metadata, then a signed public GitHub manifest."""
    if channel not in _CHANNELS:
        raise ValueError("update channel is invalid")
    sources = [
        ("server", server_manifest_url),
        ("github", github_manifest_url),
    ]
    failures: list[str] = []
    for source, url in sources:
        if not url:
            continue
        try:
            raw = _read_https(url, opener=opener)
            manifest = _json_object(raw)
            validated = validate_update_manifest(
                manifest,
                public_key=public_key,
                expected_channel=channel,
            )
            return manifest, validated, source
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            failures.append(f"{source}: {exc}")
    raise ValueError(
        "no trusted update manifest is available: " + "; ".join(failures)
    )


def _read_https(url: str, *, opener) -> bytes:
    parsed = urlparse(str(url))
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("update manifest URL must use HTTPS")
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "FactorTester-Client/update-manifest-v1",
        },
    )
    with opener(request, timeout=15) as response:
        raw = response.read(MAX_UPDATE_MANIFEST_BYTES + 1)
    if len(raw) > MAX_UPDATE_MANIFEST_BYTES:
        raise ValueError("update manifest exceeds size limit")
    return raw


def _json_object(raw: bytes) -> dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("update manifest must be a JSON object")
    return value


def _object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def _version(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not _VERSION.fullmatch(text):
        raise ValueError(f"update manifest {field} must be semantic version")
    return text
