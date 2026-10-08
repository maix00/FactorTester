"""Content-addressed local report assets with no source-code upload."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import stat
from typing import Any

from ..local_profile import LocalProfileStore
from .generation import publish_generation


MAX_REPORT_ASSET_BYTES = 8 * 1024 * 1024
_MEDIA_EXTENSIONS = {
    "image/svg+xml": ".svg",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}
_ACTIVE_SVG = re.compile(
    rb"<(?:script|foreignObject)\b|"
    rb"\bon[a-z]+\s*=|"
    rb"(?:href|src)\s*=\s*['\"]\s*(?:https?:|file:|javascript:)|"
    rb"<!DOCTYPE|<!ENTITY",
    re.IGNORECASE,
)


def stage_report_asset(
    *,
    client_root: Path,
    profile_id: str,
    report_workspace_id: str,
    source_path: Path,
    media_type: str,
    caption: str,
    alt_text: str,
    provenance_refs: list[str],
) -> dict[str, Any]:
    """Verify and stage one immutable asset in a report authoring workspace."""
    extension = _MEDIA_EXTENSIONS.get(str(media_type))
    if extension is None:
        raise ValueError("report asset media type is unsupported")
    profile = LocalProfileStore(client_root).load(profile_id)
    if not report_workspace_id or "/" in report_workspace_id or "\\" in report_workspace_id:
        raise ValueError("report_workspace_id is invalid")
    root = Path(profile["workspace_root"]) / "research" / report_workspace_id
    if not root.is_dir():
        raise ValueError("report workspace is not initialized locally")
    raw = _read_regular_file(Path(source_path))
    if media_type == "image/svg+xml":
        _validate_passive_svg(raw)
    digest = hashlib.sha256(raw).hexdigest()
    filename = f"{digest}{extension}"
    target = (
        root
        / "assets" / filename
    )
    changed = False
    if target.exists():
        if target.is_symlink() or target.read_bytes() != raw:
            raise ValueError("content-addressed report asset conflicts")
    else:
        changed = publish_generation([
            ("report_asset", target, raw),
        ])["report_asset"]
    asset = {
        "asset_ref": f"report-asset:sha256:{digest}",
        "content_hash": digest,
        "media_type": media_type,
        "filename": filename,
        "caption": _bounded_text(caption, "caption", allow_empty=False),
        "alt_text": _bounded_text(alt_text, "alt_text", allow_empty=True),
        "availability": "available",
        "provenance_refs": _references(provenance_refs),
    }
    return {"asset": asset, "changed": bool(changed)}


def stage_branch_image(*, package_root: Path, branch_id: str, source_path: Path,
                       caption: str = "", alt_text: str = "") -> dict[str, Any]:
    """复制图片到指定分支；上传原文件保留，描述使用当前报告树格式。"""
    from .authoring.tree_paths import report_tree_paths
    extension = source_path.suffix.lower()
    media_type = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                  ".webp": "image/webp", ".svg": "image/svg+xml"}.get(extension)
    if media_type is None:
        raise ValueError("仅支持 PNG、JPEG、WebP、SVG 图片")
    raw = _read_regular_file(source_path)
    if not raw:
        raise ValueError("图片不能为空")
    if media_type == "image/svg+xml":
        _validate_passive_svg(raw)
    digest = hashlib.sha256(raw).hexdigest()
    filename = digest + _MEDIA_EXTENSIONS[media_type]
    target = report_tree_paths(package_root, branch_id)["root"].parent / "assets" / filename
    if target.exists():
        if target.is_symlink() or target.read_bytes() != raw:
            raise ValueError("content-addressed report asset conflicts")
    else:
        publish_generation([("report_asset", target, raw)])
    return {"asset_ref": f"report-asset:sha256:{digest}", "content_hash": digest,
            "media_type": media_type, "filename": filename,
            "caption": _bounded_text(caption, "caption", allow_empty=True),
            "alt_text": _bounded_text(alt_text, "alt_text", allow_empty=True)}


def canonical_asset_descriptor(value: Any) -> dict[str, Any]:
    """Validate the source-free descriptor embedded in a figure block."""
    fields = {
        "asset_ref", "content_hash", "media_type", "filename", "caption",
        "alt_text", "availability", "provenance_refs",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("report figure asset fields are invalid")
    digest = str(value["content_hash"])
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("report figure content hash is invalid")
    media_type = str(value["media_type"])
    extension = _MEDIA_EXTENSIONS.get(media_type)
    if extension is None:
        raise ValueError("report figure media type is unsupported")
    filename = str(value["filename"])
    if filename != f"{digest}{extension}":
        raise ValueError("report figure filename is not content-addressed")
    asset_ref = str(value["asset_ref"])
    if asset_ref != f"report-asset:sha256:{digest}":
        raise ValueError("report figure asset reference is invalid")
    if value["availability"] != "available":
        raise ValueError("report figure must be locally available")
    return {
        "asset_ref": asset_ref,
        "content_hash": digest,
        "media_type": media_type,
        "filename": filename,
        "caption": _bounded_text(
            value["caption"], "caption", allow_empty=False,
        ),
        "alt_text": _bounded_text(
            value["alt_text"], "alt_text", allow_empty=True,
        ),
        "availability": "available",
        "provenance_refs": _references(value["provenance_refs"]),
    }


def verify_staged_asset(
    workspace_root: Path,
    report_workspace_id: str,
    descriptor: dict[str, Any],
) -> None:
    """Fail closed when a narrative names an absent or modified local asset."""
    filename = str(descriptor["filename"])
    target = (
        Path(workspace_root) / "research" / report_workspace_id
        / "assets" / filename
    )
    raw = _read_regular_file(target)
    if hashlib.sha256(raw).hexdigest() != descriptor["content_hash"]:
        raise ValueError("staged report asset hash mismatch")
    if descriptor["media_type"] == "image/svg+xml":
        _validate_passive_svg(raw)


def verify_snapshot_assets(
    workspace_root: Path,
    report_workspace_id: str,
    assets: list[dict[str, Any]],
) -> None:
    for descriptor in assets:
        verify_staged_asset(
            workspace_root,
            report_workspace_id,
            canonical_asset_descriptor(descriptor),
        )


def _read_regular_file(path: Path) -> bytes:
    descriptor = os.open(
        path,
        os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
    )
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size > MAX_REPORT_ASSET_BYTES
        ):
            raise ValueError("report asset must be a bounded regular file")
        chunks = []
        remaining = MAX_REPORT_ASSET_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(remaining, 64 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > MAX_REPORT_ASSET_BYTES:
            raise ValueError("report asset exceeds local size limit")
        return raw
    finally:
        os.close(descriptor)


def _validate_passive_svg(raw: bytes) -> None:
    stripped = raw.lstrip()
    if not stripped.startswith(b"<svg") or _ACTIVE_SVG.search(raw):
        raise ValueError("report SVG must be passive and self-contained")


def _ref_id(value: str, scheme: str) -> str:
    prefix = f"{scheme}:"
    if not str(value).startswith(prefix):
        raise ValueError(f"{scheme} reference is invalid")
    identifier = str(value)[len(prefix):]
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", identifier):
        raise ValueError(f"{scheme} reference is invalid")
    return identifier


def _bounded_text(
    value: str,
    field: str,
    *,
    allow_empty: bool,
) -> str:
    text = str(value).strip()
    if (not text and not allow_empty) or len(text) > 500:
        raise ValueError(f"report asset {field} is invalid")
    return text


def _references(values: list[str]) -> list[str]:
    if len(values) > 16:
        raise ValueError("report asset provenance is too large")
    result = []
    for value in values:
        text = str(value)
        if (
            len(text) > 512
            or ":" not in text
            or text.startswith(("/", "~"))
            or "://" in text
        ):
            raise ValueError("report asset provenance reference is invalid")
        result.append(text)
    if len(set(result)) != len(result):
        raise ValueError("report asset provenance references must be unique")
    return result
