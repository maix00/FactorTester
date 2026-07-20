"""Local Research Cycle validation without duplicating server authority."""

from __future__ import annotations

from functools import lru_cache
import json
import importlib.util
from importlib.resources import as_file, files
from types import ModuleType
from typing import Any

from .evidence import assert_no_legacy_evidence_payload


_PACKAGE = "cli_anything.factortester_research"
_VALIDATOR = (
    "skills/research-obligation-cycle/scripts/_proposal_validation.py"
)
_FORBIDDEN_PACKET_FIELDS = {
    "artifacts",
    "capability_catalog",
    "contracts",
    "required_evidence",
    "skill_body",
    "stderr",
    "stdout",
    "trace_history",
}
_FORBIDDEN_SKILL_FIELDS = {
    "implementation_id",
    "loaded_skill_ids",
    "provider",
    "skill_name",
    "source_fingerprint",
    "source_path",
}
MAX_NEXT_BYTES = 6000


def validate_transition_evidence(
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """Validate Agent-authored proposals before any backend mutation."""
    if not isinstance(evidence, dict):
        raise ValueError("transition evidence must be an object")
    if "server_evidence" in evidence:
        raise ValueError("server_evidence is server-owned")
    assert_no_legacy_evidence_payload(evidence)
    _reject_fields(evidence, _FORBIDDEN_SKILL_FIELDS, "Skill identity")
    cycle = evidence.get("research_cycle")
    if cycle is None:
        return {"proposal_count": 0, "proposal_kinds": []}
    if not isinstance(cycle, dict):
        raise ValueError("research_cycle must be an object")
    events = cycle.get("events", [])
    if not isinstance(events, list):
        raise ValueError("research_cycle events must be an array")
    validator = _proposal_validator()
    kinds: list[str] = []
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("research_cycle event must be an object")
        event_type = event.get("event_type")
        if event_type != "adjudication_proposed":
            continue
        proposal = event.get("proposal")
        if not isinstance(proposal, dict):
            raise ValueError("adjudication proposal event requires proposal")
        discovery = any(
            isinstance(item, dict)
            and item.get("from_state") == "absent"
            and item.get("to_state") == "open"
            for item in proposal.get("obligation_delta") or []
        )
        if discovery:
            validator.validate_obligation_discovery(proposal)
            kinds.append("obligation_discovery")
        else:
            validator.validate_adjudication(proposal)
            kinds.append("adjudication")
    return {
        "proposal_count": len(kinds),
        "proposal_kinds": kinds,
    }


def validate_next_packet(packet: dict[str, Any]) -> dict[str, Any]:
    """Fail closed if a backend expands the routine Agent context."""
    if not isinstance(packet, dict):
        raise ValueError("FactorTester next packet must be an object")
    assert_no_legacy_evidence_payload(packet)
    _reject_fields(packet, _FORBIDDEN_PACKET_FIELDS, "routine packet field")
    if not isinstance(packet.get("graph"), str):
        raise ValueError("FactorTester next packet graph must be a reference")
    for edge in packet.get("candidate_edges") or []:
        if not isinstance(edge, dict):
            raise ValueError("candidate_edges must contain objects")
        for field in (
            "required_research_evidence",
            "required_transition_facts",
        ):
            value = edge.get(field)
            if not isinstance(value, list) or not all(
                isinstance(item, str) and item.strip() for item in value
            ):
                raise ValueError(
                    f"candidate edge {field} must be a text array"
                )
    size = len(json.dumps(
        packet,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode())
    if size > MAX_NEXT_BYTES:
        raise ValueError(
            f"FactorTester next packet exceeds {MAX_NEXT_BYTES} bytes"
        )
    return packet


@lru_cache(maxsize=1)
def _proposal_validator() -> ModuleType:
    resource = files(_PACKAGE).joinpath(_VALIDATOR)
    with as_file(resource) as path:
        spec = importlib.util.spec_from_file_location(
            "_factortester_research_proposal_validation",
            path,
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("Research Cycle validator cannot be loaded")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


def _reject_fields(
    value: Any,
    forbidden: set[str],
    label: str,
) -> None:
    if isinstance(value, dict):
        found = sorted(set(value) & forbidden)
        if found:
            raise ValueError(f"{label} is forbidden: {', '.join(found)}")
        for item in value.values():
            _reject_fields(item, forbidden, label)
    elif isinstance(value, list):
        for item in value:
            _reject_fields(item, forbidden, label)
