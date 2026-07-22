"""Protocol validation and bounded serialization shared by Graph services."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Any

import orjson

from cli_anything.factortester_research.core.graph import (
    graph_content_hash as protocol_graph_content_hash,
    validate_graph as validate_protocol_graph,
)


MAX_AGENT_PACKET_BYTES = 6000
# Agent-facing packets and submitted transition deltas are model-context
# budgets.  A persisted trace is an audit/replay record and must retain the
# server-bound evidence plus the current Research Cycle projection; it has a
# separate storage budget rather than inheriting the context budget.
MAX_AGENT_TRANSITION_BYTES = MAX_AGENT_PACKET_BYTES
MAX_CAPABILITY_RESOLUTION_SUBMISSION_BYTES = 4096
MAX_PERSISTED_TRACE_BYTES = 16_384
MAX_TRACE_EVIDENCE_BYTES = MAX_PERSISTED_TRACE_BYTES
MAX_CONTEXT_EVIDENCE_REFS = 8
MAX_EVIDENCE_REF_BYTES = 256

_SERVER_FORBIDDEN_SKILL_FIELDS = {
    "skill_name",
    "implementation_id",
    "provider",
    "source_path",
    "source_fingerprint",
    "loaded_skill_ids",
    "loaded_skill_receipts",
}


class GraphVersionConflict(ValueError):
    """Raised when immutable Graph version identity is reused."""


class GraphActivationBlocked(ValueError):
    """Raised when a requested Graph lifecycle operation is not permitted."""


def loads(value: str | None) -> Any:
    return orjson.loads(value) if value else None


def graph_content_hash(graph: dict[str, Any]) -> str:
    return protocol_graph_content_hash(graph)


def json_hash(value: Any) -> str:
    return hashlib.sha256(
        orjson.dumps(value, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()


def assert_no_skill_identity(value: Any, *, location: str) -> None:
    if isinstance(value, dict):
        forbidden = sorted(
            str(key)
            for key in value
            if str(key) in _SERVER_FORBIDDEN_SKILL_FIELDS
        )
        if forbidden:
            raise ValueError(
                f"{location} may persist descriptions, not Skill identity: "
                + ", ".join(forbidden)
            )
        for item in value.values():
            assert_no_skill_identity(item, location=location)
    elif isinstance(value, list):
        for item in value:
            assert_no_skill_identity(item, location=location)


def validate_graph(graph: dict[str, Any]) -> dict[str, Any]:
    protocol_value = validate_protocol_graph(graph)
    if not str(protocol_value.get("graph_id") or "").strip():
        raise ValueError("graph_id is required")
    if int(protocol_value.get("version") or 0) < 1:
        raise ValueError("graph version must be positive")
    if str(protocol_value.get("research_semantics") or "") != "product_neutral":
        raise ValueError("research graph must declare product_neutral semantics")
    actual_hash = graph_content_hash(protocol_value)
    declared_hash = str(protocol_value.get("content_hash") or "")
    if declared_hash and declared_hash != actual_hash:
        raise ValueError("graph content_hash mismatch")
    value = deepcopy(protocol_value)
    value["content_hash"] = actual_hash
    return value


def merge_bounded_evidence_refs(
    existing_refs: list[str],
    omitted_count: int,
    incoming_refs: Any,
) -> tuple[list[str], int]:
    """Keep a fixed-size recent evidence window for Agent context."""
    refs = list(existing_refs)
    omitted = int(omitted_count)
    if not isinstance(incoming_refs, list):
        return refs, omitted
    for reference in incoming_refs:
        if (
            not isinstance(reference, str)
            or not reference
            or len(reference.encode()) > MAX_EVIDENCE_REF_BYTES
        ):
            omitted += 1
            continue
        if reference in refs:
            continue
        refs.append(reference)
        if len(refs) > MAX_CONTEXT_EVIDENCE_REFS:
            refs.pop(0)
            omitted += 1
    return refs, omitted


def serialize_bounded_trace_evidence(
    evidence: dict[str, Any],
) -> str:
    """Serialize one persisted trace with the audit-storage budget."""
    serialized = orjson.dumps(
        evidence,
        option=orjson.OPT_SORT_KEYS,
    )
    size = len(serialized)
    if size > MAX_TRACE_EVIDENCE_BYTES:
        raise ValueError(
            "transition evidence exceeds "
            f"{MAX_TRACE_EVIDENCE_BYTES} bytes: {size}"
        )
    return serialized.decode()


def serialize_agent_transition_evidence(
    evidence: dict[str, Any],
) -> str:
    """Serialize only the Agent-authored delta under the context budget.

    Node-local capability resolution is produced by deterministic code and
    has its own structural/storage bound.  Counting it here would make the
    same semantic proposal pass or fail according to descriptor length.
    """
    agent_delta = deepcopy(evidence)
    agent_delta.pop("target_capability_resolution", None)
    serialized = orjson.dumps(
        agent_delta,
        option=orjson.OPT_SORT_KEYS,
    )
    size = len(serialized)
    if size > MAX_AGENT_TRANSITION_BYTES:
        raise ValueError(
            "agent transition evidence exceeds "
            f"{MAX_AGENT_TRANSITION_BYTES} bytes: {size}"
        )
    return serialized.decode()


def serialize_capability_resolution_submission(value: Any) -> str:
    """Bound the deterministic attachment before any database access."""
    if not isinstance(value, dict):
        raise ValueError("capability resolution submission must be an object")
    serialized = orjson.dumps(value, option=orjson.OPT_SORT_KEYS)
    size = len(serialized)
    if size > MAX_CAPABILITY_RESOLUTION_SUBMISSION_BYTES:
        raise ValueError(
            "capability resolution submission exceeds "
            f"{MAX_CAPABILITY_RESOLUTION_SUBMISSION_BYTES} bytes: {size}"
        )
    return serialized.decode()
