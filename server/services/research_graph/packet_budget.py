"""Versioned packet budgets for one Active Graph contract."""

from __future__ import annotations

from math import ceil
from typing import Any


LEGACY_AGENT_PACKET_BYTES = 6000
MAX_AGENT_PACKET_HARD_CEILING_BYTES = 16 * 1024
MIN_CALIBRATION_HEADROOM_BYTES = 512
MIN_CALIBRATION_HEADROOM_RATIO = 0.10
REQUIRED_ACTIVATION_MEASUREMENTS = (
    "provider_actual_token_comparison",
    "server_packet_latency",
)


def graph_packet_budget(graph: dict[str, Any]) -> dict[str, Any]:
    """Return a validated graph-local budget or the legacy fallback."""
    policy = graph.get("agent_packet_budget")
    if policy is None:
        return {
            "policy_ref": "agent-packet-budget@legacy",
            "ceiling_bytes": LEGACY_AGENT_PACKET_BYTES,
            "calibration_status": (
                "missing_graph_calibration"
                if int(graph.get("schema_version") or 0) >= 2
                else "legacy_schema_exempt"
            ),
        }
    return validate_graph_packet_budget(policy)


def validate_graph_packet_budget(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("agent_packet_budget must be an object")
    if int(value.get("schema_version") or 0) != 1:
        raise ValueError("agent_packet_budget schema_version must be 1")
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


def _positive_int(value: dict[str, Any], field: str) -> int:
    raw = value.get(field)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
        raise ValueError(f"agent_packet_budget {field} must be positive")
    return raw
