"""Canonical scientific outcome fingerprints for shadow validation."""

from __future__ import annotations

import orjson
import pytest

from server.services.research_graph.shadow_outcome import (
    canonical_json_hash,
    canonical_result_summary,
    canonical_terminal_assurance,
)


def _json(value: object) -> str:
    return orjson.dumps(value).decode()


def test_result_summary_ignores_identity_size_and_profiling_rows() -> None:
    first = {
        "run_id": "graph-run",
        "full_result_bytes": 1200,
        "metrics": {"sharpe": 1.25, "return": 0.18},
        "runtime_info_rows": [
            {
                "code": "backtest_flow_profile",
                "details": {"elapsed_ms": 10.0},
            },
            {
                "code": "market_data_out_of_range_products_removed",
                "details": {"product_names": ["FU.SHF@1"]},
            },
        ],
    }
    second = {
        **first,
        "run_id": "baseline-run",
        "full_result_bytes": 1500,
        "runtime_info_rows": [
            {
                "code": "backtest_result_assembly_profile",
                "details": {"elapsed_ms": 99.0},
            },
            first["runtime_info_rows"][1],
        ],
    }

    assert canonical_json_hash(
        canonical_result_summary(_json(first))
    ) == canonical_json_hash(canonical_result_summary(_json(second)))


@pytest.mark.parametrize(
    "changed",
    [
        {"metrics": {"sharpe": 0.5, "return": 0.18}},
        {
            "runtime_info_rows": [{
                "code": "market_data_out_of_range_products_removed",
                "details": {"product_names": ["RB.SHF@1"]},
            }],
        },
        {"accounting": {"margin_mode": "exchange"}},
    ],
)
def test_result_summary_retains_scientific_and_semantic_changes(
    changed: dict,
) -> None:
    base = {
        "metrics": {"sharpe": 1.25, "return": 0.18},
        "runtime_info_rows": [{
            "code": "market_data_out_of_range_products_removed",
            "details": {"product_names": ["FU.SHF@1"]},
        }],
        "accounting": {"margin_mode": "simple"},
    }

    assert canonical_result_summary(_json(base)) != (
        canonical_result_summary(_json({**base, **changed}))
    )


def test_terminal_assurance_ignores_only_raw_result_summary_hash() -> None:
    base = {
        "disposition": "trusted",
        "anomaly_codes": [],
        "artifact_manifest_hash": "a" * 64,
        "backend_revision": "revision-1",
        "checks_bitmap": 7,
        "policy_hash": "b" * 64,
        "run_spec_hash": "c" * 64,
        "result_summary_hash": "d" * 64,
    }
    same = {**base, "result_summary_hash": "e" * 64}

    assert canonical_terminal_assurance(_json(base)) == (
        canonical_terminal_assurance(_json(same))
    )
    assert canonical_terminal_assurance(_json(base)) != (
        canonical_terminal_assurance(_json({
            **same,
            "disposition": "quarantined",
        }))
    )


@pytest.mark.parametrize("value", ["not-json", "[]", "null", "1"])
def test_canonical_outcome_rejects_malformed_or_non_object_json(
    value: str,
) -> None:
    with pytest.raises(ValueError, match="JSON object"):
        canonical_result_summary(value)
