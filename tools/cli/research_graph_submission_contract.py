"""Build and validate one fresh public ``research graphs node advance``."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from cli_anything.factortester_research.core.cycle import (
    validate_transition_evidence,
)
from cli_anything.factortester_research.core.submission_contract import (
    build_cycle_submission_contract,
    validate_against_cycle_submission_contract,
)
from tools.cli.release.research_reporting.graph_adapter import (
    enrich_graph_packet,
)


def validate_public_transition(
    *,
    node_packet: dict[str, Any],
    edge_packet: dict[str, Any],
    edge_id: str,
    evidence: dict[str, Any],
    target_capability_plan: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate against packets fetched immediately before the mutation."""
    packet = deepcopy(node_packet)
    edge = deepcopy(edge_packet.get("edge") or {})
    candidates = [
        deepcopy(item)
        for item in packet.get("candidate_edges") or []
        if isinstance(item, dict)
        and str(item.get("edge_id") or "") != edge_id
    ]
    candidates.append(edge)
    packet["candidate_edges"] = candidates
    report_contract = dict(packet.get("report_requirements") or {})
    candidate_reports = dict(
        report_contract.get("candidate_edges") or {}
    )
    candidate_reports[edge_id] = list(
        edge_packet.get("report_requirements") or []
    )
    report_contract["candidate_edges"] = candidate_reports
    packet["report_requirements"] = report_contract
    if target_capability_plan is not None:
        packet["target_capability_plan"] = target_capability_plan
    packet = enrich_graph_packet(packet)
    contract = build_cycle_submission_contract(
        packet,
        edge_id=edge_id,
        evidence=evidence,
    )
    validation = validate_transition_evidence(evidence)
    validation.update(
        validate_against_cycle_submission_contract(evidence, contract)
    )
    return contract, validation
