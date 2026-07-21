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
_SEMVER_IDENTIFIER = r"(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
_VERSION = re.compile(
    r"^(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)"
    rf"(?:-{_SEMVER_IDENTIFIER}(?:\.{_SEMVER_IDENTIFIER})*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
_PUBLISHED_AT = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
    r"[0-2][0-9]:[0-5][0-9]:[0-5][0-9]"
    r"(?:\.[0-9]{1,6})?"
    r"(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])$"
)
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


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
    parsed_dmg = urlparse(dmg_url)
    if not is_dmg_url(dmg_url):
        raise ValueError(
            "update manifest dmg_url must be an HTTPS or loopback HTTP DMG URL"
        )
    digest = str(manifest.get("sha256") or "")
    if not _SHA256.fullmatch(digest):
        raise ValueError("update manifest sha256 is invalid")
    mandatory = manifest.get("mandatory")
    if not isinstance(mandatory, bool):
        raise ValueError("update manifest mandatory must be boolean")
    published_at = str(manifest.get("published_at") or "")
    if not is_published_at(published_at):
        raise ValueError("update manifest published_at is invalid")
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
    """Resolve one channel only from its authoritative source."""
    if channel not in _CHANNELS:
        raise ValueError("update channel is invalid")
    sources = (
        [("server", server_manifest_url)]
        if channel == "beta"
        else [("github", github_manifest_url)]
    )
    failures: list[str] = []
    for source, url in sources:
        if not url:
            continue
        try:
            raw, final_url = _read_https(url, opener=opener)
            if channel == "beta" and _origin(final_url) != _origin(url):
                raise ValueError("server Beta manifest redirected off origin")
            manifest = _json_object(raw)
            validated = validate_update_manifest(
                manifest,
                public_key=public_key,
                expected_channel=channel,
            )
            if (
                channel == "beta"
                and _origin(validated.dmg_url) != _origin(final_url)
            ):
                raise ValueError("server Beta DMG must use the manifest origin")
            return manifest, validated, source
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            failures.append(f"{source}: {exc}")
    detail = "; ".join(failures) or "authoritative source is not configured"
    raise ValueError(f"no trusted {channel} update manifest is available: {detail}")


def _read_https(url: str, *, opener) -> tuple[bytes, str]:
    parsed = urlparse(str(url))
    if not _trusted_update_transport(parsed):
        raise ValueError("update manifest URL must use HTTPS or loopback HTTP")
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "FactorTester-Client/update-manifest-v1",
        },
    )
    with opener(request, timeout=15) as response:
        final_url = (
            response.geturl()
            if callable(getattr(response, "geturl", None))
            else url
        )
        if not _trusted_update_transport(urlparse(str(final_url))):
            raise ValueError("update manifest redirected to an untrusted URL")
        raw = response.read(MAX_UPDATE_MANIFEST_BYTES + 1)
    if len(raw) > MAX_UPDATE_MANIFEST_BYTES:
        raise ValueError("update manifest exceeds size limit")
    return raw, str(final_url)


def _trusted_update_transport(parsed) -> bool:
    if not parsed.netloc or parsed.username is not None or parsed.password is not None:
        return False
    if parsed.scheme == "https":
        return True
    return parsed.scheme == "http" and parsed.hostname in _LOOPBACK_HOSTS


def _origin(url: str) -> tuple[str, str, int]:
    parsed = urlparse(url)
    if not _trusted_update_transport(parsed) or parsed.hostname is None:
        raise ValueError("update URL origin is invalid")
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    return parsed.scheme, parsed.hostname.lower(), port


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
    if not is_semantic_version(text):
        raise ValueError(f"update manifest {field} must be semantic version")
    return text


def is_semantic_version(value: str) -> bool:
    """Return whether *value* is exactly one SemVer 2.0 version."""
    return _VERSION.fullmatch(value) is not None


def is_published_at(value: str) -> bool:
    """Accept the shared, deliberately narrow RFC 3339 timestamp profile."""
    if _PUBLISHED_AT.fullmatch(value) is None:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def is_dmg_url(value: str) -> bool:
    """Accept a trusted transport whose path has an exact lowercase suffix."""
    parsed = urlparse(value)
    return _trusted_update_transport(parsed) and parsed.path.endswith(".dmg")
