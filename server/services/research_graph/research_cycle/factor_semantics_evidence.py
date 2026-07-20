"""Source-free factor-semantics EvidenceEnvelope projection."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from server.services.research_graph.protocol import json_hash
from server.services.research_graph.research_cycle.evidence import (
    validate_agent_evidence_envelope,
)


def project_factor_semantics_evidence(
    *,
    configuration: dict[str, Any],
    checkpoint: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    manifests = configuration["payload"]["shared"].get(
        "factor_revision_manifests"
    )
    if not isinstance(manifests, list) or not manifests:
        raise ValueError("factor semantics requires revision manifests")
    refs = [_manifest_ref(item) for item in manifests]
    resolved = all(
        item["resolution_status"] == "resolved" for item in refs
    )
    facts = {
        "configuration_id": str(configuration["configuration_id"]),
        "configuration_revision": int(configuration["revision"]),
        "configuration_fingerprint": str(configuration["fingerprint"]),
        "factor_revision_refs": refs,
        "selected_factor_semantics_resolved": resolved,
    }
    value = {
        "schema_version": 2,
        "envelope_id": "factor-semantics:" + json_hash({
            "facts": facts,
            "contract_hash": checkpoint["contract_hash"],
            "methodology_hash": checkpoint["methodology_hash"],
        }),
        "evidence_kind": "factor_semantics",
        "source_refs": [
            "factor-revision:" + item["manifest_hash"] for item in refs
        ],
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
    return validate_agent_evidence_envelope(value), resolved


def _manifest_ref(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("factor revision manifest must be an object")
    required = {
        "factor_family_ref": str(value.get("factor_family_ref") or ""),
        "factor_alias_hash": _sha256(
            value.get("factor_alias_hash"),
            field="factor_alias_hash",
        ),
        "manifest_hash": _sha256(
            value.get("manifest_hash"),
            field="manifest_hash",
        ),
        "resolution_status": str(value.get("resolution_status") or ""),
    }
    if not required["factor_family_ref"]:
        raise ValueError("factor_family_ref is required")
    if required["resolution_status"] not in {
        "resolved",
        "family_contract_only",
    }:
        raise ValueError("invalid factor resolution_status")
    return deepcopy(required)


def _sha256(value: Any, *, field: str) -> str:
    text = str(value or "").removeprefix("sha256:")
    if len(text) != 64 or any(
        character not in "0123456789abcdef" for character in text
    ):
        raise ValueError(f"{field} must be sha256")
    return text
