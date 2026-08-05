"""Build a source-free report projection for upload to Manager 7998."""

from __future__ import annotations

import hashlib
import json
import re
import base64
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .attachments import build_related_objects


_MARKDOWN_LINK = re.compile(r"(!?)\[([^\]]*)\]\(([^)]+)\)")
_LOCAL_PATH = re.compile(r"(?<![A-Za-z0-9])/(?:Users|home)/[^\s)\]}>]+")


def build_upload_projection(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Freeze display content while withholding every owner-local path."""
    resources: dict[str, dict[str, str]] = {}
    assets = public_assets(snapshot)
    bindings = public_bindings(snapshot.get("bindings") or [])
    related_objects, attachments = build_related_objects(snapshot, bindings)
    binding_ids_by_component: dict[str, list[str]] = {}
    for binding in bindings:
        binding_ids_by_component.setdefault(binding["component_id"], []).append(binding["binding_id"])
    payload: dict[str, Any] = {
        "schema_version": 2,
        "report_id": str(snapshot["head"]["report_id"]),
        "title": _public_text(str(snapshot["head"]["title"]), resources),
        "language": snapshot["head"].get("language") or "zh-Hans",
        "generation": int(snapshot["head"]["generation"]),
        "components": [
            public_component(item, assets, resources, binding_ids_by_component)
            for item in snapshot["components"]
        ],
        "bindings": bindings,
        "assets": list(assets.values()),
        "local_resources": list(resources.values()),
        "related_objects": related_objects,
        "attachments": attachments,
    }
    payload["projection_hash"] = hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return payload


def public_assets(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    allowed = {
        "image/gif", "image/jpeg", "image/png", "image/svg+xml", "image/webp",
    }
    result: dict[str, dict[str, Any]] = {}
    values = snapshot["head"].get("assets") or []
    root = snapshot.get("paths", {}).get("root")
    # report_tree_paths.root is the branch's authoring directory while
    # staged assets live beside it at <branch>/assets.  Keep both candidates
    # so callers with an older snapshot layout still publish safely.
    asset_roots = []
    if root is not None:
        root_path = Path(root)
        asset_roots.extend((root_path.parent / "assets", root_path / "assets"))
    # Base64 expands the upload; keep the encoded JSON comfortably below the
    # manager's 32 MiB request limit.
    total_bytes = 0
    for value in values:
        media_type = str(value.get("media_type") or "")
        if media_type not in allowed:
            continue
        asset_id = asset_id_for(str(value["asset_ref"]))
        item = {
            "asset_id": asset_id,
            "media_type": media_type,
            "filename": str(value.get("filename") or "image").split("/")[-1],
            "caption": _plain_text(str(value.get("caption") or "")),
            "alt_text": _plain_text(str(value.get("alt_text") or "")),
            "content_hash": str(value.get("content_hash") or ""),
        }
        # The manager has no access to the owner's worktree.  Carry bounded,
        # content-addressed bytes once during publication; the manager stores
        # them separately and serves them through the authenticated/public
        # publication asset route.
        for asset_root in asset_roots:
            path = asset_root / item["filename"]
            try:
                raw = path.read_bytes()
            except OSError:
                continue
            if raw and len(raw) <= 8 * 1024 * 1024 and total_bytes + len(raw) <= 20 * 1024 * 1024:
                if hashlib.sha256(raw).hexdigest() == item["content_hash"]:
                    item["content_base64"] = base64.b64encode(raw).decode("ascii")
                    total_bytes += len(raw)
                    break
        result[asset_id] = item
    return result


def public_component(
    value: dict[str, Any],
    assets: dict[str, dict[str, Any]],
    resources: dict[str, dict[str, str]],
    binding_ids_by_component: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    content = public_value(value.get("content"), resources)
    if value.get("kind") == "image" and isinstance(value.get("content"), dict):
        asset_id = asset_id_for(str(value["content"].get("asset_ref") or ""))
        content = {"asset_id": asset_id} if asset_id in assets else None
    component_id = str(value["component_id"])
    return {
        "component_id": component_id,
        "parent_id": value.get("parent_id"),
        "kind": str(value["kind"]),
        "title": _public_text(str(value.get("title") or ""), resources),
        "body": _public_text(str(value.get("body") or ""), resources),
        "content": content,
        "display_kind": str(value.get("display_kind") or ""),
        "binding_ids": (binding_ids_by_component or {}).get(component_id, []),
        "created_at": value.get("created_at"),
        "graph_version": value.get("graph_version"),
    }


def public_bindings(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expose only the stable fields needed by the two report renderers."""
    result = []
    for value in values:
        item = {
            "binding_id": str(value.get("binding_id") or ""),
            "component_id": str(value.get("component_id") or ""),
            "kind": str(value.get("kind") or ""),
            "target_ref": str(value.get("target_ref") or ""),
            "label": _public_text(str(value.get("label") or ""), {}),
        }
        data = value.get("data")
        if isinstance(data, dict):
            item["data"] = public_value(data, {})
        if item["binding_id"] and item["target_ref"]:
            result.append(item)
    return result


def public_value(value: Any, resources: dict[str, dict[str, str]]) -> Any:
    if isinstance(value, str):
        return _public_text(value, resources)
    if isinstance(value, list):
        return [public_value(item, resources) for item in value]
    if isinstance(value, dict):
        return {
            str(key): public_value(item, resources)
            for key, item in value.items()
            if str(key) not in {
                "local_ref", "workspace_root", "receipt_path", "source_path",
            }
        }
    return value


def _public_text(
    value: str, resources: dict[str, dict[str, str]],
) -> str:
    def replace_link(match: re.Match[str]) -> str:
        image, label, target = match.groups()
        scheme = urlparse(target.strip()).scheme.lower()
        if scheme in {"http", "https"}:
            return match.group(0)
        if scheme == "file" and not image:
            resource_id = hashlib.sha256(target.encode("utf-8")).hexdigest()[:24]
            resources[resource_id] = {
                "resource_id": resource_id,
                "title": _plain_text(label) or "本地文件",
            }
            return f"[{label}](factortester-local://{resource_id})"
        if scheme == "factortester" and not image:
            kind = urlparse(target.strip()).netloc.lower()
            if kind in {
                "job", "evidence", "factor", "factor-family", "factor-set",
                "product", "product-group", "contract", "continuous-contract",
                "continuous_contract", "profile", "profile-revision", "run",
                "run_spec", "trial_plan", "obligation", "requirement",
                "report_requirement", "entry_requirement", "claim", "task",
                "artifact", "graph_reference", "checkpoint", "delta", "file",
                "url",
            }:
                return match.group(0)
        if scheme == "factortester-artifact" and not image:
            return match.group(0)
        return label

    result = _MARKDOWN_LINK.sub(replace_link, value)
    result = re.sub(r"file://[^\s)\]}>]+", "[本地路径已隐藏]", result)
    return _LOCAL_PATH.sub("[本地路径已隐藏]", result)


def _plain_text(value: str) -> str:
    return _LOCAL_PATH.sub("[本地路径已隐藏]", value)


def asset_id_for(asset_ref: str) -> str:
    return hashlib.sha256(asset_ref.encode("utf-8")).hexdigest()[:24]
