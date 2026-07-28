"""Read and validate retired document files during one-shot migration only."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .tree_assets import validate_asset
from .tree_schema import NODE_KINDS, identifier, validate_binding, validate_content


_DOCUMENT_FIELDS = {
    "schema_version", "document_id", "title", "language", "revision",
    "components", "assets",
}
_COMPONENT_FIELDS = {
    "component_id", "kind", "parent_id", "title", "body", "content",
    "display_kind", "created_at",
}
_BINDING_FIELDS = {
    "schema_version", "document_id", "document_hash", "bindings", "migration",
}


def load_legacy_document(path: Path) -> dict[str, Any]:
    value = _load_json(path, "旧报告")
    if set(value) != _DOCUMENT_FIELDS or value.get("schema_version") != 2:
        raise ValueError("旧报告格式无效")
    identifier(value.get("document_id"), "document_id")
    if not isinstance(value.get("title"), str) or not value["title"].strip():
        raise ValueError("旧报告标题无效")
    if not isinstance(value.get("language"), str) or not value["language"]:
        raise ValueError("旧报告语言无效")
    if not isinstance(value.get("revision"), int) or value["revision"] < 0:
        raise ValueError("旧报告版本无效")
    components = value.get("components")
    assets = value.get("assets")
    if not isinstance(components, list) or not isinstance(assets, list):
        raise ValueError("旧报告内容无效")
    ids: set[str] = set()
    for item in components:
        _component(item, ids)
    for item in components:
        parent = item["parent_id"]
        if parent is not None and parent not in ids:
            raise ValueError("旧报告父条目不存在")
    asset_refs: set[str] = set()
    for asset in assets:
        normalized = validate_asset(asset)
        if normalized["asset_ref"] in asset_refs:
            raise ValueError("旧报告生成物重复")
        asset_refs.add(normalized["asset_ref"])
    return value


def load_legacy_bindings(path: Path, document: dict[str, Any]) -> dict[str, Any]:
    value = _load_json(path, "旧报告绑定")
    if set(value) != _BINDING_FIELDS or value.get("schema_version") != 1:
        raise ValueError("旧报告绑定格式无效")
    if value.get("document_id") != document["document_id"]:
        raise ValueError("旧报告绑定的文档标识不匹配")
    if value.get("document_hash") != legacy_document_hash(document):
        raise ValueError("旧报告绑定的文档哈希不匹配")
    if value.get("migration") is not None and not isinstance(value["migration"], dict):
        raise ValueError("旧报告绑定迁移字段无效")
    items = value.get("bindings")
    if not isinstance(items, list):
        raise ValueError("旧报告绑定列表无效")
    component_ids = {item["component_id"] for item in document["components"]}
    binding_ids: set[str] = set()
    for item in items:
        if not isinstance(item, dict) or set(item) != {
            "binding_id", "component_id", "kind", "target_ref", "label", "data",
        }:
            raise ValueError("旧报告绑定字段无效")
        binding = validate_binding({
            key: item[key]
            for key in ("binding_id", "kind", "target_ref", "label", "data")
        })
        if binding["binding_id"] in binding_ids:
            raise ValueError("旧报告绑定重复")
        if item["component_id"] not in component_ids:
            raise ValueError("旧报告绑定条目不存在")
        binding_ids.add(binding["binding_id"])
    return value


def legacy_document_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()


def legacy_bindings_path(document_path: Path) -> Path:
    return document_path.with_suffix(document_path.suffix + ".bindings.json")


def _component(value: Any, ids: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != _COMPONENT_FIELDS:
        raise ValueError("旧报告条目字段无效")
    identifier(value.get("component_id"), "component_id")
    if value["component_id"] in ids or value.get("kind") not in NODE_KINDS:
        raise ValueError("旧报告条目无效")
    parent = value.get("parent_id")
    if parent is not None:
        identifier(parent, "parent_id")
    if not isinstance(value.get("title"), str) or not value["title"].strip():
        raise ValueError("旧报告条目标题无效")
    if not isinstance(value.get("body"), str) or not isinstance(value.get("display_kind"), str):
        raise ValueError("旧报告条目文本无效")
    if value["kind"] == "special" and not value["display_kind"].strip():
        raise ValueError("旧报告特殊条目缺少显示类型")
    if not isinstance(value.get("created_at"), (int, float)):
        raise ValueError("旧报告条目时间无效")
    validate_content(value["kind"], value.get("content"))
    ids.add(value["component_id"])


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取{label}: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label}必须是对象")
    return value
