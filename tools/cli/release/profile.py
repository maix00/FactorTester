"""Local bootstrap profile loading without credentials."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
import time
from typing import Any
from urllib.request import urlopen

from .locations import default_client_root, validate_client_root
from .update_channel import (
    ValidatedUpdateManifest,
    resolve_update_manifest,
)


MAX_MANIFEST_BYTES = 256 * 1024
MAIN_GITHUB_MANIFEST_URL = (
    "https://github.com/maix00/FactorTester-Client/"
    "releases/latest/download/stable.json"
)


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
    raw = _read_manifest_with_retry(manifest_url)
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError("release manifest exceeds size limit")
    return _json_object(raw, "release manifest"), public_key, root


def load_update_inputs(
    profile_path: Path,
) -> tuple[dict[str, Any], ValidatedUpdateManifest, str]:
    """Resolve Beta from the server or Main from signed GitHub metadata."""
    profile = _json_object(profile_path.read_bytes(), "client profile")
    if profile.get("schema_version") != 1:
        raise ValueError("client profile schema_version is unsupported")
    release = profile.get("release")
    if not isinstance(release, dict):
        raise ValueError("client profile release object is required")
    if "public_key" in release:
        raise ValueError("release public key is fixed by the client package")
    configured_github_url = str(
        release.get("github_manifest_url") or ""
    ).strip()
    if configured_github_url and configured_github_url != MAIN_GITHUB_MANIFEST_URL:
        raise ValueError("Main update manifest URL is fixed to the public GitHub release")
    github_url = MAIN_GITHUB_MANIFEST_URL
    server_url = str(release.get("server_manifest_url") or "").strip() or None
    channel = str(release.get("channel") or "stable")
    if channel == "beta" and not server_url:
        raise ValueError("signed server Beta update manifest URL is required")
    key_name = (
        "trusted-beta-release-public.pem"
        if channel == "beta"
        else "trusted-release-public.pem"
    )
    public_key = Path(str(
        files("tools.cli.release").joinpath(key_name)
    ))
    if not public_key.is_file():
        raise ValueError(f"release public key not found: {public_key}")
    return resolve_update_manifest(
        server_manifest_url=server_url,
        github_manifest_url=github_url,
        channel=channel,
        public_key=public_key,
    )


def _read_manifest_with_retry(url: str) -> bytes:
    for attempt in range(3):
        try:
            with urlopen(url, timeout=30) as response:
                return response.read(MAX_MANIFEST_BYTES + 1)
        except OSError:
            if attempt == 2:
                raise
            time.sleep(0.25 * (attempt + 1))
    raise AssertionError("unreachable")


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
