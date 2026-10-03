"""Item-level semantic audit for migrated persistent report trees."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from pathlib import Path
from typing import Any

from ..authoring.tree_projection import load_snapshot
from ..authoring.tree_render import render_tree_markdown
from ..authoring.tree_schema import digest


_INLINE_CODE = re.compile(r"(?<!`)`[^`\n]+`(?!`)")
_FENCED_CODE = re.compile(r"(?m)^\s*(?:```|~~~)")
_INLINE_MATH = re.compile(r"\\\(.+?\\\)", re.DOTALL)
_DISPLAY_MATH = re.compile(r"(?:\\\[.+?\\\]|\$\$.+?\$\$)", re.DOTALL)


def audit_branch_report(
    *, package_root: Path, branch_id: str,
) -> dict[str, Any]:
    """Audit every component, binding, rich-text feature, and Markdown export."""
    snapshot = load_snapshot(package_root=package_root, branch_id=branch_id)
    bindings = _bindings_by_component(snapshot["bindings"])
    component_ids: set[str] = set()
    item_audits: list[dict[str, Any]] = []
    errors: list[str] = []
    kinds: Counter[str] = Counter()
    features: Counter[str] = Counter()

    for component in snapshot["components"]:
        component_id = component["component_id"]
        if component_id in component_ids:
            errors.append(f"duplicate component_id: {component_id}")
        component_ids.add(component_id)
        kinds[component["kind"]] += 1
        item = _audit_component(component, bindings.get(component_id, []))
        item_audits.append(item)
        features.update(item["features"])
        if component["parent_id"] is None and component["kind"] != "chapter":
            errors.append(f"non-chapter root component: {component_id}")
        errors.extend(item["errors"])

    for component in snapshot["components"]:
        parent_id = component["parent_id"]
        if parent_id is not None and parent_id not in component_ids:
            errors.append(
                f"missing parent {parent_id}: {component['component_id']}"
            )

    rendered = render_tree_markdown(snapshot)
    report_path = package_root / "branches" / branch_id / "REPORT.md"
    export_matches = report_path.is_file() and report_path.read_bytes() == rendered
    if not export_matches:
        errors.append("REPORT.md does not match the current report tree")

    binding_kinds = Counter(item["kind"] for item in snapshot["bindings"])
    semantic_payload = {
        "title": snapshot["head"]["title"],
        "items": [
            {
                "component_id": item["component_id"],
                "semantic_hash": item["semantic_hash"],
            }
            for item in item_audits
        ],
        "assets": snapshot["head"]["assets"],
    }
    return {
        "schema_version": 1,
        "branch_id": branch_id,
        "report_id": snapshot["head"]["report_id"],
        "generation": snapshot["head"]["generation"],
        "semantic_hash": digest(semantic_payload),
        "component_count": len(snapshot["components"]),
        "binding_count": len(snapshot["bindings"]),
        "asset_count": len(snapshot["head"]["assets"]),
        "root_chapter_count": sum(
            item["kind"] == "chapter" and item["parent_id"] is None
            for item in snapshot["components"]
        ),
        "component_kinds": dict(sorted(kinds.items())),
        "binding_kinds": dict(sorted(binding_kinds.items())),
        "rich_features": dict(sorted(features.items())),
        "report_markdown_sha256": hashlib.sha256(rendered).hexdigest(),
        "report_markdown_matches": export_matches,
        "valid": not errors,
        "errors": errors,
        "items": item_audits,
    }


def _audit_component(
    component: dict[str, Any], bindings: list[dict[str, Any]],
) -> dict[str, Any]:
    texts = [component["title"], component["body"]]
    texts.extend(_text_values(component["content"]))
    combined = "\n".join(texts)
    feature_names: list[str] = []
    for name, pattern in (
        ("inline_code", _INLINE_CODE),
        ("fenced_code", _FENCED_CODE),
        ("inline_math", _INLINE_MATH),
        ("display_math", _DISPLAY_MATH),
    ):
        if pattern.search(combined):
            feature_names.append(name)
    if component["kind"] in {"code", "math", "table", "image"}:
        feature_names.append(f"typed_{component['kind']}")
    if "factortester://" in combined:
        feature_names.append("typed_link")

    errors: list[str] = []
    for binding in bindings:
        if binding["target_ref"].startswith("legacy-link:"):
            errors.append(
                f"legacy binding target: {binding['binding_id']}"
            )
        if "legacy_target_ref" in binding["data"]:
            errors.append(
                f"legacy binding metadata: {binding['binding_id']}"
            )
    payload = {
        key: component[key]
        for key in (
            "component_id", "kind", "parent_id", "title", "body",
            "content", "display_kind",
        )
    }
    payload["bindings"] = sorted(bindings, key=lambda item: item["binding_id"])
    return {
        "component_id": component["component_id"],
        "kind": component["kind"],
        "parent_id": component["parent_id"],
        "semantic_hash": digest(payload),
        "binding_ids": [
            item["binding_id"] for item in payload["bindings"]
        ],
        "features": sorted(set(feature_names)),
        "errors": errors,
    }


def _bindings_by_component(
    bindings: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for binding in bindings:
        result.setdefault(binding["component_id"], []).append(binding)
    return result


def _text_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [
            text
            for item in value
            for text in _text_values(item)
        ]
    if isinstance(value, dict):
        return [
            text
            for item in value.values()
            for text in _text_values(item)
        ]
    return []
