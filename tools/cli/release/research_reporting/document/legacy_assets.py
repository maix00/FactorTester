"""Asset projection helpers for legacy report fragments."""

from __future__ import annotations

from typing import Any

from .model import add_asset


def ensure_asset(document: dict[str, Any], asset: dict[str, Any]) -> dict[str, Any]:
    ref = asset.get("asset_ref")
    if not ref or any(item.get("asset_ref") == ref for item in document["assets"]):
        return document
    return add_asset(document, {
        "asset_ref": ref,
        "media_type": asset.get("media_type") or "application/octet-stream",
        "filename": asset.get("filename") or str(ref).replace(":", "_") + ".bin",
        "caption": asset.get("caption") or "",
        "alt_text": asset.get("alt_text") or "",
    })
