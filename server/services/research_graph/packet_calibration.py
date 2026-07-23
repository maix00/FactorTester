"""Provider-neutral verification of cold-path packet calibration receipts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


_IDENTITY_FIELDS = (
    "graph_hash",
    "packet_schema_hash",
    "serializer_hash",
    "provider_id",
    "model_id",
    "tokenizer_id",
    "tokenizer_revision",
    "runtime_id",
    "capability_compatibility_hash",
)


@dataclass(frozen=True)
class VerifiedPacketCalibration:
    """Bounded summary returned only by a trusted Provider adapter."""

    receipt_ref: str
    receipt_hash: str
    identity: dict[str, str]
    covered_anchor_refs: list[str]
    covered_packet_kinds: list[str]
    covered_scenarios: list[str]
    sample_count: int
    maximum_serialized_bytes: int
    agent_context_byte_ceiling: int
    maximum_runtime_input_tokens: int
    runtime_input_token_ceiling: int
    e2e_latency_p50_ms: float
    e2e_latency_p95_ms: float
    e2e_latency_p99_ms: float
    truncated_rate: float
    rejected_rate: float
    failed_rate: float


class PacketCalibrationReceiptVerifier(Protocol):
    """Trusted adapter for one opaque, Provider-issued calibration receipt."""

    def verify(
        self,
        receipt: str,
        *,
        expected_identity: dict[str, str],
    ) -> VerifiedPacketCalibration: ...


_VERIFIERS: dict[str, PacketCalibrationReceiptVerifier] = {}


def register_packet_calibration_receipt_verifier(
    provider_id: str,
    verifier: PacketCalibrationReceiptVerifier,
) -> None:
    _VERIFIERS[_required_text(provider_id, "provider_id")] = verifier


def clear_packet_calibration_receipt_verifiers() -> None:
    _VERIFIERS.clear()


def packet_calibration_receipt_verifier(
    provider_id: str,
) -> PacketCalibrationReceiptVerifier:
    provider = _required_text(provider_id, "provider_id")
    verifier = _VERIFIERS.get(provider)
    if verifier is None:
        raise ValueError(
            f"no trusted packet calibration verifier for provider {provider}"
        )
    return verifier


def verify_packet_calibration_receipt(
    *,
    receipt: str,
    expected_identity: dict[str, str],
    policy: dict[str, Any],
    verifier: PacketCalibrationReceiptVerifier,
) -> dict[str, Any]:
    """Return a bounded activation summary; never return the opaque receipt."""
    if not isinstance(receipt, str) or not receipt:
        raise ValueError("packet calibration receipt is required")
    identity = _validated_identity(expected_identity)
    result = verifier.verify(receipt, expected_identity=identity)
    if not isinstance(result, VerifiedPacketCalibration):
        raise ValueError(
            "packet calibration verifier returned an invalid result"
        )
    actual_identity = _validated_identity(result.identity)
    if actual_identity != identity:
        raise ValueError("packet calibration identity mismatch")
    receipt_ref = _required_text(result.receipt_ref, "receipt_ref")
    receipt_hash = _sha256(result.receipt_hash, "receipt_hash")
    declared_ref = str(policy.get("calibration_receipt_ref") or "")
    declared_hash = str(policy.get("calibration_receipt_hash") or "")
    if declared_ref and (
        declared_ref != receipt_ref or declared_hash != receipt_hash
    ):
        raise ValueError("packet calibration receipt binding mismatch")
    coverage = policy["coverage"]
    _require_exact_coverage(
        result.covered_anchor_refs,
        coverage["required_anchor_refs"],
        field="anchor",
    )
    _require_exact_coverage(
        result.covered_packet_kinds,
        coverage["required_packet_kinds"],
        field="packet kind",
    )
    _require_exact_coverage(
        result.covered_scenarios,
        coverage["required_scenarios"],
        field="scenario",
    )
    required_samples = (
        len(coverage["required_anchor_refs"])
        * len(coverage["required_packet_kinds"])
        * len(coverage["required_scenarios"])
        * int(coverage["minimum_samples_per_case"])
    )
    if result.sample_count < required_samples:
        raise ValueError("packet calibration sample coverage is incomplete")
    _validate_summary(result, policy)
    return {
        "calibration_status": "provider_verified",
        "receipt_ref": receipt_ref,
        "receipt_hash": receipt_hash,
        "identity": actual_identity,
        "coverage": {
            "anchor_refs": list(result.covered_anchor_refs),
            "packet_kinds": list(result.covered_packet_kinds),
            "scenarios": list(result.covered_scenarios),
        },
        "summary": {
            "sample_count": result.sample_count,
            "maximum_serialized_bytes": result.maximum_serialized_bytes,
            "agent_context_byte_ceiling": (
                result.agent_context_byte_ceiling
            ),
            "maximum_runtime_input_tokens": (
                result.maximum_runtime_input_tokens
            ),
            "runtime_input_token_ceiling": (
                result.runtime_input_token_ceiling
            ),
            "e2e_latency_p50_ms": result.e2e_latency_p50_ms,
            "e2e_latency_p95_ms": result.e2e_latency_p95_ms,
            "e2e_latency_p99_ms": result.e2e_latency_p99_ms,
            "truncated_rate": result.truncated_rate,
            "rejected_rate": result.rejected_rate,
            "failed_rate": result.failed_rate,
        },
    }


def _validated_identity(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != set(_IDENTITY_FIELDS):
        raise ValueError("packet calibration identity is incomplete")
    return {
        field: _required_text(value.get(field), field)
        for field in _IDENTITY_FIELDS
    }


def _require_exact_coverage(
    actual: Any,
    required: list[str],
    *,
    field: str,
) -> None:
    if (
        not isinstance(actual, list)
        or len(actual) != len(required)
        or set(actual) != set(required)
    ):
        raise ValueError(f"packet calibration {field} coverage is incomplete")


def _validate_summary(
    result: VerifiedPacketCalibration,
    policy: dict[str, Any],
) -> None:
    for field in (
        "sample_count",
        "maximum_serialized_bytes",
        "agent_context_byte_ceiling",
        "maximum_runtime_input_tokens",
        "runtime_input_token_ceiling",
    ):
        if isinstance(getattr(result, field), bool) or getattr(result, field) <= 0:
            raise ValueError(f"packet calibration {field} must be positive")
    if (
        result.agent_context_byte_ceiling
        > int(policy["protocol_hard_ceiling_bytes"])
    ):
        raise ValueError("packet calibration exceeds protocol hard ceiling")
    byte_headroom = (
        result.agent_context_byte_ceiling
        - result.maximum_serialized_bytes
    )
    required_byte_headroom = max(
        int(policy["thresholds"]["minimum_byte_headroom_bytes"]),
        int(
            result.maximum_serialized_bytes
            * float(
                policy["thresholds"]["minimum_byte_headroom_ratio"]
            )
        ),
    )
    if byte_headroom < required_byte_headroom:
        raise ValueError("packet calibration lacks byte headroom")
    token_headroom = (
        result.runtime_input_token_ceiling
        - result.maximum_runtime_input_tokens
    )
    required_headroom = (
        result.maximum_runtime_input_tokens
        * float(policy["thresholds"]["minimum_token_headroom_ratio"])
    )
    if token_headroom < required_headroom:
        raise ValueError("packet calibration lacks runtime token headroom")
    latencies = (
        result.e2e_latency_p50_ms,
        result.e2e_latency_p95_ms,
        result.e2e_latency_p99_ms,
    )
    if any(value < 0 for value in latencies) or not (
        latencies[0] <= latencies[1] <= latencies[2]
    ):
        raise ValueError("packet calibration latency percentiles are invalid")
    thresholds = policy["thresholds"]
    if (
        result.e2e_latency_p95_ms
        > float(thresholds["maximum_e2e_latency_p95_ms"])
    ):
        raise ValueError("packet calibration latency threshold exceeded")
    for field in ("truncated_rate", "rejected_rate", "failed_rate"):
        rate = getattr(result, field)
        if rate < 0 or rate > 1:
            raise ValueError(f"packet calibration {field} must be a rate")
        maximum = float(thresholds[f"maximum_{field}"])
        if rate > maximum:
            raise ValueError(f"packet calibration {field} threshold exceeded")


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"packet calibration {field} is required")
    return value


def _sha256(value: Any, field: str) -> str:
    text = _required_text(value, field)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise ValueError(f"packet calibration {field} must be sha256")
    return text
