"""Provider-verified packet calibration is an activation-time contract."""

from __future__ import annotations

from dataclasses import replace

import pytest

from server.services.research_graph.packet_calibration import (
    VerifiedPacketCalibration,
    clear_packet_calibration_receipt_verifiers,
    register_packet_calibration_receipt_verifier,
    verify_packet_calibration_receipt,
)
from server.services.research_graph.packet_calibration_binding import (
    bind_packet_calibration,
)
from server.services.research_graph.packet_budget import graph_packet_budget
from server.services.research_graph.shadow_tokens import token_failures
from cli_anything.factortester_research.core.successor_graph import (
    build_successor_graph,
)


def _identity(graph: dict) -> dict[str, str]:
    return {
        "graph_hash": graph["content_hash"],
        "packet_schema_hash": "1" * 64,
        "serializer_hash": "2" * 64,
        "provider_id": "provider-a",
        "model_id": "model-a",
        "tokenizer_id": "tokenizer-a",
        "tokenizer_revision": "revision-a",
        "runtime_id": "runtime-a",
        "capability_compatibility_hash": "3" * 64,
    }


def _verified(graph: dict) -> VerifiedPacketCalibration:
    policy = graph_packet_budget(graph)
    coverage = policy["coverage"]
    case_count = (
        len(coverage["required_anchor_refs"])
        * len(coverage["required_packet_kinds"])
        * len(coverage["required_scenarios"])
    )
    return VerifiedPacketCalibration(
        receipt_ref="provider-receipt:packet-calibration-1",
        receipt_hash="4" * 64,
        identity=_identity(graph),
        covered_anchor_refs=coverage["required_anchor_refs"],
        covered_packet_kinds=coverage["required_packet_kinds"],
        covered_scenarios=coverage["required_scenarios"],
        sample_count=case_count,
        maximum_serialized_bytes=6000,
        agent_context_byte_ceiling=7000,
        maximum_runtime_input_tokens=1800,
        runtime_input_token_ceiling=2100,
        e2e_latency_p50_ms=80.0,
        e2e_latency_p95_ms=120.0,
        e2e_latency_p99_ms=180.0,
        truncated_rate=0.0,
        rejected_rate=0.0,
        failed_rate=0.0,
    )


class _Verifier:
    def __init__(self, result: VerifiedPacketCalibration) -> None:
        self.result = result

    def verify(self, receipt: str, *, expected_identity: dict) -> (
        VerifiedPacketCalibration
    ):
        assert receipt == "opaque-provider-receipt"
        return self.result


def test_verified_calibration_covers_real_packet_matrix_and_identity() -> None:
    graph = build_successor_graph()
    verified = _verified(graph)

    result = verify_packet_calibration_receipt(
        receipt="opaque-provider-receipt",
        expected_identity=_identity(graph),
        policy=graph_packet_budget(graph),
        verifier=_Verifier(verified),
    )

    assert result["calibration_status"] == "provider_verified"
    assert result["receipt_ref"] == verified.receipt_ref
    assert result["receipt_hash"] == verified.receipt_hash
    assert result["summary"]["sample_count"] == verified.sample_count
    assert result["summary"]["agent_context_byte_ceiling"] == 7000
    assert "opaque-provider-receipt" not in repr(result)


def test_calibration_fails_closed_when_identity_does_not_match() -> None:
    graph = build_successor_graph()
    verified = _verified(graph)
    mismatched = replace(
        verified,
        identity={**verified.identity, "model_id": "different-model"},
    )

    with pytest.raises(ValueError, match="calibration identity mismatch"):
        verify_packet_calibration_receipt(
            receipt="opaque-provider-receipt",
            expected_identity=_identity(graph),
            policy=graph_packet_budget(graph),
            verifier=_Verifier(mismatched),
        )


def test_activation_token_gate_fails_closed_without_verified_calibration() -> None:
    metrics = {
        "routine_context_bytes": 100,
        "routine_context_ceiling_bytes": 16 * 1024,
        "routine_context_latency_ms": 1.0,
        "packet_budget_calibration_status": "missing_calibration_receipt",
        "provider_actual_token_comparison": True,
        "packet_calibration": {
            "calibration_status": "missing_calibration_receipt",
        },
        "full_graph_loaded_for_routine": False,
        "untriggered_conditionals_in_context": 0,
        "future_node_gaps_blocked": 0,
        "routine_subagent_count": 0,
        "shadow_graph_total_tokens": 80,
        "shadow_baseline_total_tokens": 100,
    }

    failures = token_failures(metrics)

    assert "packet_calibration_receipt" in failures


def test_calibration_rejects_incomplete_anchor_coverage() -> None:
    graph = build_successor_graph()
    verified = _verified(graph)
    incomplete = replace(
        verified,
        covered_anchor_refs=verified.covered_anchor_refs[:-1],
    )

    with pytest.raises(ValueError, match="anchor coverage is incomplete"):
        verify_packet_calibration_receipt(
            receipt="opaque-provider-receipt",
            expected_identity=_identity(graph),
            policy=graph_packet_budget(graph),
            verifier=_Verifier(incomplete),
        )


def test_calibration_rejects_latency_regression() -> None:
    graph = build_successor_graph()
    verified = _verified(graph)
    failed = replace(
        verified,
        e2e_latency_p95_ms=6000.0,
        e2e_latency_p99_ms=7000.0,
    )

    with pytest.raises(ValueError, match="latency threshold exceeded"):
        verify_packet_calibration_receipt(
            receipt="opaque-provider-receipt",
            expected_identity=_identity(graph),
            policy=graph_packet_budget(graph),
            verifier=_Verifier(failed),
        )


def test_calibration_rejects_context_ceiling_without_byte_headroom() -> None:
    graph = build_successor_graph()
    verified = replace(
        _verified(graph),
        agent_context_byte_ceiling=6100,
    )

    with pytest.raises(ValueError, match="byte headroom"):
        verify_packet_calibration_receipt(
            receipt="opaque-provider-receipt",
            expected_identity=_identity(graph),
            policy=graph_packet_budget(graph),
            verifier=_Verifier(verified),
        )


def test_calibration_rejects_truncation_rejection_or_failure() -> None:
    graph = build_successor_graph()
    verified = _verified(graph)
    failed = replace(verified, failed_rate=0.01)

    with pytest.raises(ValueError, match="failed_rate threshold exceeded"):
        verify_packet_calibration_receipt(
            receipt="opaque-provider-receipt",
            expected_identity=_identity(graph),
            policy=graph_packet_budget(graph),
            verifier=_Verifier(failed),
        )


def test_runtime_identity_and_capability_resolution_bind_the_receipt() -> None:
    graph = build_successor_graph()
    template = _verified(graph)

    class Verifier:
        identities: list[dict[str, str]] = []

        def verify(self, receipt: str, *, expected_identity: dict) -> (
            VerifiedPacketCalibration
        ):
            self.identities.append(expected_identity)
            return replace(template, identity=expected_identity)

    verifier = Verifier()
    clear_packet_calibration_receipt_verifiers()
    register_packet_calibration_receipt_verifier("provider-a", verifier)
    cohort = [{
        "provider_id": "provider-a",
        "model_id": "model-a",
        "runtime_id": "runtime-a",
    }]
    request = {
        "provider_id": "provider-a",
        "tokenizer_id": "tokenizer-a",
        "tokenizer_revision": "revision-a",
        "receipt": "opaque-provider-receipt",
    }
    try:
        for resolution_hash in ("5" * 64, "6" * 64):
            bind_packet_calibration(
                graph=graph,
                context={
                    "branch": {
                        "capability_resolution_hash": resolution_hash,
                    },
                },
                packet_budget=graph_packet_budget(graph),
                cohort=cohort,
                request=request,
            )
    finally:
        clear_packet_calibration_receipt_verifiers()

    assert verifier.identities[0]["graph_hash"] == graph["content_hash"]
    assert verifier.identities[0]["provider_id"] == "provider-a"
    assert verifier.identities[0]["model_id"] == "model-a"
    assert verifier.identities[0]["runtime_id"] == "runtime-a"
    assert verifier.identities[0]["tokenizer_id"] == "tokenizer-a"
    assert (
        verifier.identities[0]["capability_compatibility_hash"]
        != verifier.identities[1]["capability_compatibility_hash"]
    )
