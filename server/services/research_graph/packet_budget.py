"""Versioned packet budgets for one Active Graph contract."""

from __future__ import annotations

import hashlib
from math import ceil
import os
from typing import Any

import orjson


LEGACY_AGENT_PACKET_BYTES = 6000
DEFAULT_RUNTIME_AGENT_PACKET_BYTES = 6400
MAX_AGENT_PACKET_HARD_CEILING_BYTES = 16 * 1024
MIN_CALIBRATION_HEADROOM_BYTES = 512
MIN_CALIBRATION_HEADROOM_RATIO = 0.10
REQUIRED_ACTIVATION_MEASUREMENTS = (
    "provider_actual_token_comparison",
    "server_packet_latency",
)


def graph_packet_budget(graph: dict[str, Any]) -> dict[str, Any]:
    """Return a runtime Profile for v2 Graphs or a historical Graph budget."""
    policy = graph.get("agent_packet_budget")
    if policy is None:
        if int(graph.get("schema_version") or 0) >= 2:
            return runtime_packet_budget_profile(graph)
        legacy = {
            "policy_ref": "agent-packet-budget@legacy",
            "profile_ref": "agent-packet-budget@legacy",
            "budget_scope": "graph_legacy",
            "ceiling_bytes": LEGACY_AGENT_PACKET_BYTES,
            "calibration_status": "legacy_schema_exempt",
        }
        legacy["profile_hash"] = hashlib.sha256(orjson.dumps(
            legacy,
            option=orjson.OPT_SORT_KEYS,
        )).hexdigest()
        return legacy
    validated = validate_graph_packet_budget(policy)
    validated["budget_scope"] = "graph_legacy"
    validated["profile_ref"] = str(validated["policy_ref"])
    validated["profile_hash"] = hashlib.sha256(orjson.dumps(
        validated,
        option=orjson.OPT_SORT_KEYS,
    )).hexdigest()
    return validated


def runtime_packet_budget_profile(graph: dict[str, Any]) -> dict[str, Any]:
    raw_ceiling = os.environ.get(
        "GTHT_AGENT_PACKET_CEILING_BYTES",
        str(DEFAULT_RUNTIME_AGENT_PACKET_BYTES),
    )
    try:
        ceiling = int(raw_ceiling)
    except ValueError as exc:
        raise ValueError(
            "GTHT_AGENT_PACKET_CEILING_BYTES must be an integer"
        ) from exc
    if ceiling <= 0 or ceiling > MAX_AGENT_PACKET_HARD_CEILING_BYTES:
        raise ValueError(
            "runtime packet budget exceeds the protocol safety boundary"
        )
    profile = {
        "schema_version": 2,
        "profile_ref": "agent-packet-runtime@1",
        "policy_ref": "agent-packet-runtime@1",
        "budget_scope": "runtime_profile",
        "ceiling_bytes": ceiling,
        "protocol_hard_ceiling_bytes": (
            MAX_AGENT_PACKET_HARD_CEILING_BYTES
        ),
        "coverage": {
            "required_anchor_refs": [
                *(
                    f"node:{item['node_id']}"
                    for item in graph.get("nodes") or []
                ),
                *(
                    f"edge:{item['edge_id']}"
                    for item in graph.get("edges") or []
                ),
                *(
                    f"system_gate:{item['policy_kind']}"
                    for item in graph.get("system_transition_policies") or []
                ),
            ],
            "required_packet_kinds": ["context", "next"],
            "required_scenarios": ["typical", "max_legal"],
            "minimum_samples_per_case": 1,
        },
        "thresholds": {
            "minimum_byte_headroom_bytes": 512,
            "minimum_byte_headroom_ratio": 0.10,
            "minimum_token_headroom_ratio": 0.10,
            "maximum_e2e_latency_p95_ms": 5000.0,
            "maximum_truncated_rate": 0.0,
            "maximum_rejected_rate": 0.0,
            "maximum_failed_rate": 0.0,
        },
        "calibration_receipt_contract_ref": (
            "provider-verified-packet-calibration@1"
        ),
        "calibration_receipt_ref": "",
        "calibration_receipt_hash": "",
        "calibration_status": "uncalibrated",
    }
    profile["profile_hash"] = hashlib.sha256(orjson.dumps(
        profile,
        option=orjson.OPT_SORT_KEYS,
    )).hexdigest()
    return profile


def validate_graph_packet_budget(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("agent_packet_budget must be an object")
    schema_version = int(value.get("schema_version") or 0)
    if schema_version == 2:
        return _validate_v2_policy(value)
    if schema_version != 1:
        raise ValueError("agent_packet_budget schema_version must be 1 or 2")
    ceiling = _positive_int(value, "ceiling_bytes")
    observed = _positive_int(value, "observed_max_packet_bytes")
    sample_count = _positive_int(value, "sample_count")
    headroom = ceiling - observed
    required_headroom = max(
        MIN_CALIBRATION_HEADROOM_BYTES,
        ceil(observed * MIN_CALIBRATION_HEADROOM_RATIO),
    )
    if ceiling > MAX_AGENT_PACKET_HARD_CEILING_BYTES:
        raise ValueError("agent_packet_budget exceeds the protocol hard ceiling")
    if headroom < required_headroom:
        raise ValueError(
            "agent_packet_budget lacks calibrated semantic headroom"
        )
    anchors = value.get("sampled_anchor_refs")
    if (
        not isinstance(anchors, list)
        or len(anchors) != sample_count
        or not all(isinstance(item, str) and item for item in anchors)
        or len(set(anchors)) != len(anchors)
    ):
        raise ValueError(
            "agent_packet_budget sampled_anchor_refs must match sample_count"
        )
    measurements = value.get("activation_measurements")
    if (
        not isinstance(measurements, list)
        or set(measurements) != set(REQUIRED_ACTIVATION_MEASUREMENTS)
    ):
        raise ValueError(
            "agent_packet_budget requires token and latency activation evidence"
        )
    return {
        "policy_ref": str(value.get("policy_ref") or "agent-packet-budget@1"),
        "schema_version": 1,
        "ceiling_bytes": ceiling,
        "observed_max_packet_bytes": observed,
        "sample_count": sample_count,
        "sampled_anchor_refs": list(anchors),
        "headroom_bytes": headroom,
        "activation_measurements": list(measurements),
        "calibration_status": "graph_version_calibrated",
    }


def _validate_v2_policy(value: dict[str, Any]) -> dict[str, Any]:
    hard_ceiling = _positive_int(value, "protocol_hard_ceiling_bytes")
    if hard_ceiling > MAX_AGENT_PACKET_HARD_CEILING_BYTES:
        raise ValueError("agent_packet_budget exceeds the protocol hard ceiling")
    coverage = value.get("coverage")
    if not isinstance(coverage, dict):
        raise ValueError("agent_packet_budget coverage must be an object")
    anchors = _unique_strings(
        coverage.get("required_anchor_refs"),
        field="coverage.required_anchor_refs",
    )
    packet_kinds = _unique_strings(
        coverage.get("required_packet_kinds"),
        field="coverage.required_packet_kinds",
    )
    scenarios = _unique_strings(
        coverage.get("required_scenarios"),
        field="coverage.required_scenarios",
    )
    if set(packet_kinds) != {"context", "next"}:
        raise ValueError("agent_packet_budget must calibrate context and next")
    if set(scenarios) != {"typical", "max_legal"}:
        raise ValueError(
            "agent_packet_budget must calibrate typical and max_legal"
        )
    minimum_samples = _positive_int(
        coverage,
        "minimum_samples_per_case",
    )
    thresholds = value.get("thresholds")
    if not isinstance(thresholds, dict):
        raise ValueError("agent_packet_budget thresholds must be an object")
    normalized_thresholds = {
        "minimum_byte_headroom_bytes": _positive_int(
            thresholds, "minimum_byte_headroom_bytes",
        ),
        "minimum_byte_headroom_ratio": _ratio(
            thresholds, "minimum_byte_headroom_ratio", allow_one=False,
        ),
        "minimum_token_headroom_ratio": _ratio(
            thresholds, "minimum_token_headroom_ratio", allow_one=False,
        ),
        "maximum_e2e_latency_p95_ms": _positive_number(
            thresholds, "maximum_e2e_latency_p95_ms",
        ),
        "maximum_truncated_rate": _ratio(
            thresholds, "maximum_truncated_rate",
        ),
        "maximum_rejected_rate": _ratio(
            thresholds, "maximum_rejected_rate",
        ),
        "maximum_failed_rate": _ratio(
            thresholds, "maximum_failed_rate",
        ),
    }
    contract_ref = str(
        value.get("calibration_receipt_contract_ref") or ""
    )
    if contract_ref != "provider-verified-packet-calibration@1":
        raise ValueError("unsupported packet calibration receipt contract")
    receipt_ref = str(value.get("calibration_receipt_ref") or "")
    receipt_hash = str(value.get("calibration_receipt_hash") or "")
    if bool(receipt_ref) != bool(receipt_hash):
        raise ValueError(
            "packet calibration receipt ref and hash must be paired"
        )
    return {
        "schema_version": 2,
        "policy_ref": str(value.get("policy_ref") or "agent-packet-budget@2"),
        "protocol_hard_ceiling_bytes": hard_ceiling,
        "ceiling_bytes": hard_ceiling,
        "coverage": {
            "required_anchor_refs": anchors,
            "required_packet_kinds": packet_kinds,
            "required_scenarios": scenarios,
            "minimum_samples_per_case": minimum_samples,
        },
        "thresholds": normalized_thresholds,
        "calibration_receipt_contract_ref": contract_ref,
        "calibration_receipt_ref": receipt_ref,
        "calibration_receipt_hash": receipt_hash,
        "calibration_status": (
            "receipt_declared_unverified"
            if receipt_ref else "missing_calibration_receipt"
        ),
    }


def _positive_int(value: dict[str, Any], field: str) -> int:
    raw = value.get(field)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
        raise ValueError(f"agent_packet_budget {field} must be positive")
    return raw


def _positive_number(value: dict[str, Any], field: str) -> float:
    raw = value.get(field)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or raw <= 0:
        raise ValueError(f"agent_packet_budget {field} must be positive")
    return float(raw)


def _ratio(
    value: dict[str, Any],
    field: str,
    *,
    allow_one: bool = True,
) -> float:
    raw = value.get(field)
    maximum = 1 if allow_one else 1.0
    if (
        isinstance(raw, bool)
        or not isinstance(raw, (int, float))
        or raw < 0
        or raw > maximum
        or (not allow_one and (raw == 0 or raw == 1))
    ):
        raise ValueError(f"agent_packet_budget {field} must be a ratio")
    return float(raw)


def _unique_strings(value: Any, *, field: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item for item in value)
        or len(set(value)) != len(value)
    ):
        raise ValueError(
            f"agent_packet_budget {field} must contain unique strings"
        )
    return list(value)
