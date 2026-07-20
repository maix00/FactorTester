"""Local bootstrap profile loading without credentials."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from .locations import default_client_root, validate_client_root


MAX_MANIFEST_BYTES = 256 * 1024


def load_release_inputs(
    profile_path: Path,
) -> tuple[dict[str, Any], Path, Path]:
    profile = _json_object(profile_path.read_bytes(), "client profile")
    if profile.get("schema_version") != 1:
        raise ValueError("client profile schema_version is unsupported")
    release = profile.get("release")
    if not isinstance(release, dict):
        raise ValueError("client profile release object is required")
    manifest_url = str(release.get("manifest_url") or "").strip()
    if not manifest_url.startswith("https://"):
        raise ValueError("release manifest URL must use https")
    if "public_key" in release:
        raise ValueError("release public key is fixed by the client package")
    public_key = Path(str(
        files("tools.cli.release").joinpath("trusted-release-public.pem")
    ))
    if not public_key.is_file():
        raise ValueError(f"release public key not found: {public_key}")
    configured_root = str(release.get("install_root") or "").strip()
    root = (
        validate_client_root(Path(configured_root).expanduser())
        if configured_root
        else default_client_root()
    )
    with urlopen(manifest_url, timeout=30) as response:
        raw = response.read(MAX_MANIFEST_BYTES + 1)
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError("release manifest exceeds size limit")
    return _json_object(raw, "release manifest"), public_key, root


def load_profile_root(profile_path: Path | None) -> Path:
    if profile_path is None:
        return default_client_root()
    profile = _json_object(profile_path.read_bytes(), "client profile")
    release = profile.get("release")
    if not isinstance(release, dict):
        raise ValueError("client profile release object is required")
    configured = str(release.get("install_root") or "").strip()
    return (
        validate_client_root(Path(configured).expanduser())
        if configured
        else default_client_root()
    )


def _json_object(raw: bytes, label: str) -> dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value
