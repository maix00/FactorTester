"""Apply one explicitly reviewed rich-text migration to report source."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from typing import Any

from ..authoring.inline_links import MARKDOWN_LINK_PATTERN
from ..authoring.tree_model import apply_batch, load_snapshot
from ..references.preflight import preflight_component
from .rich_text_normalization import semantic_text


_PROTECTED = re.compile(
    MARKDOWN_LINK_PATTERN + r"|(?<!`)`[^`\n]+`(?!`)"
    r"|\\\(.+?\\\)|\\\[.+?\\\]|\$\$.+?\$\$",
    re.DOTALL,
)


def migrate_component_semantics(
    *, package_root, branch_id: str, scope: Any, plan: dict[str, Any],
) -> dict[str, Any]:
    """Validate and atomically apply exact, component-scoped replacements."""
    prepared = prepare_component_semantics(
        package_root=package_root, branch_id=branch_id, scope=scope, plan=plan,
    )
    saved = apply_batch(
        package_root=package_root, branch_id=branch_id,
        operations=prepared.pop("operations"), include_snapshot=True,
    )
    prepared["generation_after"] = saved["head"]["generation"]
    return prepared


def prepare_component_semantics(
    *, package_root, branch_id: str, scope: Any, plan: dict[str, Any],
) -> dict[str, Any]:
    """Validate a reviewed migration and build its transaction without writes."""
    snapshot = load_snapshot(package_root=package_root, branch_id=branch_id)
    _validate_review_scope(snapshot["components"], plan)
    by_id = {item["component_id"]: item for item in snapshot["components"]}
    operations: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = []
    changed_ids: set[str] = set()
    for change in plan.get("changes") or []:
        component_id = str(change.get("component_id") or "")
        if component_id in changed_ids:
            raise ValueError(f"reviewed component is duplicated: {component_id}")
        changed_ids.add(component_id)
        current = by_id.get(component_id)
        if current is None:
            raise ValueError(f"reviewed component does not exist: {component_id}")
        updated = _apply_replacements(current, change.get("replacements") or [])
        bindings = preflight_component(
            component_id=component_id, kind=updated["kind"],
            title=updated["title"], body=updated["body"],
            content=updated["content"],
            display_kind=updated["display_kind"], scope=scope,
        )
        operations.append({
            "op": "replace", "component_id": component_id,
            "title": updated["title"], "body": updated["body"],
            "content": updated["content"],
            "display_kind": updated["display_kind"], "bindings": bindings,
        })
        changes.append({
            "component_id": component_id,
            "replacement_count": len(change.get("replacements") or []),
        })
    for current in snapshot["components"]:
        if current["component_id"] in changed_ids:
            continue
        preflight_component(
            component_id=current["component_id"], kind=current["kind"],
            title=current["title"], body=current["body"],
            content=current["content"],
            display_kind=current["display_kind"], scope=scope,
        )
    if not operations:
        raise ValueError("semantic migration has no changes")
    return {
        "migration_id": str(plan.get("migration_id") or ""),
        "generation_before": snapshot["head"]["generation"],
        "generation_after": snapshot["head"]["generation"] + 1,
        "reviewed_component_count": len(snapshot["components"]),
        "changed_component_count": len(changes),
        "changes": changes,
        "operations": operations,
    }


def _validate_review_scope(
    components: list[dict[str, Any]], plan: dict[str, Any],
) -> None:
    if plan.get("schema_version") != 1 or not plan.get("migration_id"):
        raise ValueError("semantic migration plan is invalid")
    identities = sorted(item["component_id"] for item in components)
    digest = hashlib.sha256(
        json.dumps(identities, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    if (
        plan.get("reviewed_component_count") != len(identities)
        or plan.get("reviewed_component_digest") != digest
    ):
        raise ValueError("semantic migration review scope does not match report")


def _apply_replacements(
    component: dict[str, Any], replacements: list[dict[str, Any]],
) -> dict[str, Any]:
    updated = deepcopy(component)
    for rule in replacements:
        field = str(rule.get("field") or "")
        if field not in {"title", "body", "content"}:
            raise ValueError("semantic replacement field is invalid")
        source = str(rule.get("source") or "")
        replacement = str(rule.get("replacement") or "")
        match_mode = str(rule.get("match_mode") or "exact")
        expected = rule.get("count")
        before = deepcopy(updated[field])
        updated[field], observed = _replace_value(
            before, source, replacement, match_mode,
        )
        if not source or observed != expected:
            raise ValueError(
                f"{component['component_id']}:{field} expected "
                f"{expected} replacements for {source!r}, observed {observed}"
            )
        if semantic_text(_flatten(before)) != semantic_text(
            _flatten(updated[field])
        ):
            raise ValueError(
                f"{component['component_id']}:{field} semantic replacement "
                f"changed report prose for {source!r} -> {replacement!r}"
            )
    return updated


def _replace_value(
    value: Any, source: str, replacement: str, match_mode: str,
) -> tuple[Any, int]:
    if isinstance(value, str):
        return _replace_unformatted(
            value, source, replacement, match_mode=match_mode,
        )
    if isinstance(value, list):
        result, count = [], 0
        for item in value:
            changed, observed = _replace_value(
                item, source, replacement, match_mode,
            )
            result.append(changed)
            count += observed
        return result, count
    if isinstance(value, dict):
        result, count = {}, 0
        for key, item in value.items():
            changed, observed = _replace_value(
                item, source, replacement, match_mode,
            )
            result[key] = changed
            count += observed
        return result, count
    return value, 0


def _replace_unformatted(
    value: str, source: str, replacement: str, *, match_mode: str = "exact",
) -> tuple[str, int]:
    if match_mode not in {"exact", "token"}:
        raise ValueError("semantic replacement match_mode is invalid")
    ranges = [match.span() for match in _PROTECTED.finditer(value)]
    matches = (
        re.finditer(
            rf"(?<![A-Za-z0-9_]){re.escape(source)}(?![A-Za-z0-9_])",
            value,
        )
        if match_mode == "token" and source
        else re.finditer(re.escape(source), value) if source else ()
    )
    starts: list[int] = []
    for match in matches:
        position, end = match.span()
        if not any(position < right and end > left for left, right in ranges):
            starts.append(position)
    result = value
    for position in reversed(starts):
        result = (
            result[:position] + replacement + result[position + len(source):]
        )
    return result, len(starts)


def _flatten(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_flatten(item) for item in value)
    if isinstance(value, dict):
        return "\n".join(_flatten(item) for item in value.values())
    return ""
