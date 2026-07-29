"""Validated chronological Graph report placement from server history."""

from __future__ import annotations

from typing import Any

from tools.cli.release.research_reporting.authoring.tree_schema import (
    identifier,
)


def load_history(
    client: Any,
    *,
    work_package_ref: str,
    branch_id: str,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    after = ""
    seen = set()
    while True:
        page = client.list_profile_research_branch_timeline(
            work_package_ref, branch_id, limit=50, after=after,
        )
        values = page.get("items")
        if not isinstance(values, list):
            raise ValueError("server timeline items are invalid")
        items.extend(_step(item) for item in values)
        cursor = str(page.get("next_cursor") or "")
        if not cursor:
            break
        if cursor in seen:
            raise ValueError("server timeline cursor repeated")
        seen.add(cursor)
        after = cursor
    return sorted(
        items,
        key=lambda item: (float(item["created_at"]), item["step_ref"]),
    )


def history_contexts(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not items:
        return []
    contexts = [_context(items[0], source=True)]
    contexts.extend(_context(item, source=False) for item in items)
    return contexts


def _context(item: dict[str, Any], *, source: bool) -> dict[str, Any]:
    detour = item["capability_detour"]
    state = (
        detour["state_before"]
        if source else detour["delta"] or detour["state_after"]
    )
    node = item["from_node"] if source else item["to_node"]
    container = (
        item["source_report_container"]
        if source else item["report_container"]
    )
    packet = {
        "current_node": node,
        "latest_trace_id": item["step_ref"].removeprefix("trace:"),
        "report_container": container,
    }
    if state is not None:
        packet["capability_detour"] = state
    return {
        "step_ref": item["step_ref"],
        "side": "source" if source else "target",
        "packet": packet,
        "report_component_ids": (
            [] if source else _report_component_ids(item["evidence_refs"])
        ),
    }


def _step(value: Any) -> dict[str, Any]:
    required = {
        "step_ref", "from_node", "to_node", "created_at",
        "source_report_container", "report_container", "capability_detour",
        "evidence_refs",
    }
    if (
        not isinstance(value, dict)
        or not required.issubset(value)
        or not str(value["step_ref"]).startswith("trace:")
        or not isinstance(value["source_report_container"], dict)
        or not isinstance(value["report_container"], dict)
        or not isinstance(value["capability_detour"], dict)
        or not isinstance(value["evidence_refs"], list)
        or not all(isinstance(item, str) for item in value["evidence_refs"])
    ):
        raise ValueError("server timeline report placement is invalid")
    detour = value["capability_detour"]
    if set(detour) != {"state_before", "delta", "state_after"}:
        raise ValueError("server timeline capability placement is invalid")
    return value


def _report_component_ids(refs: list[str]) -> list[str]:
    return list(dict.fromkeys(
        identifier(ref.removeprefix("report:"), "report component_id")
        for ref in refs if ref.startswith("report:")
    ))
