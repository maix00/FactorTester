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
    research_ref: str = "",
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    after = ""
    seen = set()
    while True:
        if research_ref:
            page = client.list_profile_research_timeline(
                research_ref, limit=50, after=after,
            )
        else:
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
    return [
        context
        for item in items
        for context in (
            _context(item, source=True),
            _context(item, source=False),
        )
    ]


def obligation_history_contexts(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Project accepted obligation facts without replaying report placement.

    Historical Graph continuations can carry a deliberately unresolved report
    container while preserving complete obligation deltas.  The obligation
    ledger migration must therefore depend only on immutable obligation facts,
    not on a later report-placement schema.
    """
    return [{
        "step_ref": item["step_ref"],
        "side": "target",
        "from_node": item["from_node"],
        "to_node": item["to_node"],
        "created_at": item["created_at"],
        "obligation_changes": item["obligation_changes"],
        "obligation_presentations": item["obligation_presentations"],
        "requirement_presentations": item.get(
            "requirement_presentations", []
        ),
    } for item in items]


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
        "from_node": item["from_node"],
        "to_node": item["to_node"],
        "created_at": item["created_at"],
        "obligation_changes": (
            [] if source else item["obligation_changes"]
        ),
        "obligation_presentations": (
            [] if source else item["obligation_presentations"]
        ),
        "requirement_presentations": (
            [] if source else item.get("requirement_presentations", [])
        ),
        "packet": packet,
        "container": _historical_container(
            raw=container,
            detour=state,
            current_node=node,
            latest_trace_id=item["step_ref"].removeprefix("trace:"),
        ),
        "report_component_ids": (
            [] if source else _report_component_ids(item["evidence_refs"])
        ),
    }


def _historical_container(
    *,
    raw: dict[str, Any],
    detour: dict[str, Any] | None,
    current_node: str,
    latest_trace_id: str,
) -> dict[str, Any]:
    """Validate persisted placement without applying today's Graph policy.

    Timeline rows are immutable historical facts. Their detour statuses may
    predate the current graph contract, so only structural identity and
    containment are validated here.
    """
    kind = str(raw.get("kind") or "")
    anchor = str(raw.get("anchor_node") or "")
    if kind == "chapter":
        if not anchor or anchor != current_node:
            raise ValueError("historical chapter report_container is invalid")
        return {
            "kind": "chapter",
            "anchor_node": anchor,
            "current_node": current_node,
            "latest_trace_id": latest_trace_id,
        }
    if kind != "special" or not isinstance(detour, dict):
        raise ValueError("historical special report_container is invalid")
    episode = str(detour.get("episode_id") or "")
    resume = str(detour.get("resume_node") or "")
    origin = str(detour.get("origin_trace_id") or "")
    status = str(detour.get("status") or "")
    recorded = detour.get("report_container")
    if (
        not all((anchor, episode, resume, origin, status, current_node))
        or anchor != resume
        or raw.get("episode_ref") != episode
        or not isinstance(recorded, dict)
        or raw != recorded
    ):
        raise ValueError("historical capability report_container is invalid")
    normalized = {
        **detour,
        "schema_version": int(detour.get("schema_version") or 1),
        "episode_id": episode,
        "status": status,
        "resume_node": resume,
        "origin_trace_id": origin,
        "latest_trace_id": str(
            detour.get("latest_trace_id") or latest_trace_id
        ),
        "report_container": dict(raw),
    }
    return {
        "kind": "special",
        "anchor_node": anchor,
        "current_node": current_node,
        "latest_trace_id": normalized["latest_trace_id"],
        "detour": normalized,
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
    changes = value.get("obligation_changes") or []
    presentations = value.get("obligation_presentations") or []
    if (
        not isinstance(changes, list)
        or not all(_valid_obligation_change(item) for item in changes)
        or not isinstance(presentations, list)
        or not all(_valid_obligation_presentation(item) for item in presentations)
    ):
        raise ValueError("server timeline obligation changes are invalid")
    return {
        **value,
        "obligation_changes": changes,
        "obligation_presentations": presentations,
    }


def _valid_obligation_change(value: Any) -> bool:
    if (
        not isinstance(value, dict)
        or not all(
            isinstance(value.get(field), str) and value[field]
            for field in ("obligation_id", "from_state", "to_state")
        )
    ):
        return False
    for field in ("from_requirement_refs", "to_requirement_refs"):
        refs = value.get(field, [])
        if not isinstance(refs, list) or not all(
            isinstance(item, str) for item in refs
        ):
            return False
    return True


def _valid_obligation_presentation(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("obligation_ref"), str)
        and str(value["obligation_ref"]).startswith("obligation:")
        and isinstance(value.get("question_summary"), str)
    )


def _report_component_ids(refs: list[str]) -> list[str]:
    return list(dict.fromkeys(
        identifier(ref.removeprefix("report:"), "report component_id")
        for ref in refs if ref.startswith("report:")
    ))
