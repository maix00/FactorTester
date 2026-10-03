"""Bounded public access to report image assets."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import unquote, urlparse


MAX_ASSET_BYTES = 32 * 1024 * 1024


def load_asset(
    *, package_root: Path, asset: dict, public_metadata: dict,
) -> dict:
    path = asset_path(package_root, asset)
    if path.is_symlink() or not path.is_file():
        raise ValueError("public research asset is unavailable")
    size = path.stat().st_size
    if size < 0 or size > MAX_ASSET_BYTES:
        raise ValueError("public research asset exceeds size limit")
    raw = path.read_bytes()
    expected = str(asset.get("content_hash") or "")
    if expected and hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("public research asset integrity check failed")
    if str(asset.get("media_type") or "") == "image/svg+xml":
        validate_svg(raw)
    return {**public_metadata, "path": path, "raw": raw}


def asset_path(package_root: Path, asset: dict) -> Path:
    filename = Path(str(asset.get("filename") or "")).name
    local_ref = str(asset.get("local_ref") or "")
    if local_ref:
        candidate = (package_root / unquote(local_ref)).resolve()
        if package_root.resolve() not in candidate.parents:
            raise ValueError("public research asset escapes its Report Workspace")
        return candidate
    external = urlparse(str(asset.get("external_ref") or ""))
    parts = [part for part in external.path.split("/") if part]
    if (
        external.scheme == "factortester-artifact"
        and external.netloc == "jobs" and len(parts) == 2
        and re.fullmatch(r"[A-Za-z0-9._-]{1,128}", parts[0])
    ):
        return Path.home() / "Documents" / "FactorTester" / "jobs" / parts[0] / filename
    return package_root / "assets" / filename


def validate_svg(raw: bytes) -> None:
    try:
        value = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("public SVG is not UTF-8") from exc
    lower = value.lower()
    forbidden = ("<script", "<foreignobject", "<!doctype", "<!entity", "javascript:")
    if (
        not lower.lstrip().startswith("<svg")
        or any(item in lower for item in forbidden)
        or re.search(r"\son[a-z]+\s*=", lower)
        or re.search(r"(?:href|src)\s*=\s*[\"']\s*(?:https?:|file:|javascript:)", lower)
    ):
        raise ValueError("public SVG contains active or external content")
