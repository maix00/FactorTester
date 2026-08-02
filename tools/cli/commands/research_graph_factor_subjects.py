"""Derive explicit transition subjects from typed report bindings."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from tools.cli.factor_subject_refs import factor_subject_kind


def attach_transition_factor_subjects(
    evidence: dict[str, Any],
    *,
    action_contract: dict[str, Any],
    snapshot: dict[str, Any],
    chapter_component_id: str,
    requirement_ids: set[str],
) -> None:
    """Attach subjects only when the server declares the report source."""
    source = action_contract.get("factor_subject_source")
    if source is None:
        return
    if source != "current_report_requirement_bindings":
        raise ValueError("unsupported factor subject source")
    refs = factor_subject_refs_from_report(
        snapshot,
        chapter_component_id=chapter_component_id,
        requirement_ids=requirement_ids,
    )
    if not refs:
        raise ValueError(
            "current transition report components need a typed factor link"
        )
    evidence["factor_subject_refs"] = refs


def factor_subject_refs_from_report(
    snapshot: dict[str, Any],
    *,
    chapter_component_id: str,
    requirement_ids: set[str],
) -> list[str]:
    """Return factors attached to this transition's report components.

    The report tree is authoritative for which subject the Agent discussed.
    This deliberately does not inspect Markdown text, aliases, obligations, or
    historical EvidenceUse scope.
    """
    components = snapshot.get("components")
    bindings = snapshot.get("bindings")
    if not isinstance(components, list) or not isinstance(bindings, list):
        raise ValueError("report snapshot components and bindings are required")
    if not chapter_component_id or not requirement_ids:
        raise ValueError("current chapter and report requirements are required")

    parent_by_id = {
        str(item.get("component_id") or ""): str(item.get("parent_id") or "")
        for item in components
        if isinstance(item, dict) and item.get("component_id")
    }
    chapter_components = {
        component_id
        for component_id in parent_by_id
        if _belongs_to_chapter(
            component_id,
            chapter_component_id=chapter_component_id,
            parent_by_id=parent_by_id,
        )
    }
    by_component: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for binding in bindings:
        if not isinstance(binding, dict):
            raise ValueError("report binding must be an object")
        component_id = str(binding.get("component_id") or "")
        if component_id in chapter_components:
            by_component[component_id].append(binding)

    requirement_components = {
        component_id
        for component_id, rows in by_component.items()
        if any(
            row.get("kind") == "report_requirement"
            and str(row.get("target_ref") or "") in requirement_ids
            for row in rows
        )
    }
    refs: set[str] = set()
    for component_id, rows in by_component.items():
        if not any(
            _is_descendant_of(
                component_id,
                ancestor_id=requirement_component,
                parent_by_id=parent_by_id,
            )
            for requirement_component in requirement_components
        ):
            continue
        for row in rows:
            if row.get("kind") != "factor":
                continue
            target_ref = str(row.get("target_ref") or "")
            kind = factor_subject_kind(target_ref)
            if kind not in {"factor", "factor_family"}:
                raise ValueError(
                    "factor semantics requires a frozen factor or factor family"
                )
            refs.add(target_ref)
    return sorted(refs)


def _belongs_to_chapter(
    component_id: str,
    *,
    chapter_component_id: str,
    parent_by_id: dict[str, str],
) -> bool:
    return _is_descendant_of(
        component_id,
        ancestor_id=chapter_component_id,
        parent_by_id=parent_by_id,
    )


def _is_descendant_of(
    component_id: str,
    *,
    ancestor_id: str,
    parent_by_id: dict[str, str],
) -> bool:
    current = component_id
    seen: set[str] = set()
    while current and current not in seen:
        if current == ancestor_id:
            return True
        seen.add(current)
        current = parent_by_id.get(current, "")
    return False
