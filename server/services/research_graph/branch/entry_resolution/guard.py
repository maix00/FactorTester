"""Hash-bound resume guards for entry-resolution attempts."""

from __future__ import annotations

import hashlib
from typing import Any

import orjson


def resume_guard_hash(
    *,
    graph_ref: str,
    target_node: str,
    origin_checkpoint_ref: str,
    blocking_obligation_refs: list[str],
    entry_requirement_refs: list[str],
) -> str:
    if not graph_ref or not target_node or not origin_checkpoint_ref:
        raise ValueError("entry resume guard requires graph, target, checkpoint")
    payload = {
        "graph_ref": graph_ref,
        "target_node": target_node,
        "origin_checkpoint_ref": origin_checkpoint_ref,
        "blocking_obligation_refs": _refs(blocking_obligation_refs),
        "entry_requirement_refs": _refs(entry_requirement_refs),
    }
    return hashlib.sha256(
        orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()


def resume_guard_matches(
    frame: dict[str, Any],
    *,
    graph_ref: str,
    target_node: str,
    origin_checkpoint_ref: str,
    blocking_obligation_refs: list[str],
    entry_requirement_refs: list[str],
) -> bool:
    declared = str(frame.get("resume_guard_hash") or "")
    if not declared:
        return False
    return declared == resume_guard_hash(
        graph_ref=graph_ref,
        target_node=target_node,
        origin_checkpoint_ref=origin_checkpoint_ref,
        blocking_obligation_refs=blocking_obligation_refs,
        entry_requirement_refs=entry_requirement_refs,
    )


def _refs(value: list[str]) -> list[str]:
    return sorted({str(item) for item in value if str(item)})
