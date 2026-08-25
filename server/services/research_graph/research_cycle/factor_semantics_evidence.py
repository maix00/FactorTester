"""Source-free factor-semantics EvidenceEnvelope projection."""

from __future__ import annotations

from typing import Any

from server.services.research_graph.protocol import json_hash
from server.services.research_graph.research_cycle.evidence import (
    validate_agent_evidence_envelope,
)


def project_factor_semantics_evidence(
    *,
    checkpoint: dict[str, Any],
    factor_subject_refs: list[str],
) -> tuple[dict[str, Any], bool]:
    subjects = sorted(set(factor_subject_refs))
    if not subjects:
        raise ValueError("factor semantics requires frozen factor subjects")
    facts = {
        "factor_revision_count": len(subjects),
        "factor_subject_refs": subjects,
        "factor_revision_set_hash": json_hash(subjects),
        "selected_factor_semantics_resolved": True,
    }
    value = {
        "schema_version": 2,
        "envelope_id": "factor-semantics:" + json_hash({
            "facts": facts,
            "contract_hash": checkpoint["contract_hash"],
            "methodology_hash": checkpoint["methodology_hash"],
        }),
        "evidence_kind": "factor_semantics",
        "source_refs": subjects,
        "identity_refs": {
            "contract_hash": checkpoint["contract_hash"],
            "methodology_hash": checkpoint["methodology_hash"],
        },
        "facts": facts,
        "metric_refs": [],
        "artifact_refs": [],
        "hypotheses_tested": 0,
        "stop_condition": None,
        "limitations": [
            "Revision identity does not establish causal timing or "
            "discharge semantic obligations."
        ],
        "conflicts": [],
    }
    return validate_agent_evidence_envelope(value), True
