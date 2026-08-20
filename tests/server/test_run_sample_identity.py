"""RunSpec-v2 execution-scope identity tests."""

from __future__ import annotations

import pytest

from server.services.research_graph.trial_plan.sample_identity import (
    derive_sample_identity,
)


def _run_spec_v2(
    analyses: list[str],
    *,
    ic_range: tuple[str, str] = ("2024-01-02", "2024-12-31"),
    backtest_range: tuple[str, str] = ("2024-01-02", "2024-12-31"),
) -> dict:
    return {
        "run_spec_version": 3,
        "analyses": analyses,
        "configuration": {
            "analyses": {
                "ic": {
                    "settings": {
                        "start_date": ic_range[0],
                        "end_date": ic_range[1],
                    },
                    "paths": ["CNFutures/日盘/AP.CZC"],
                },
                "backtest": {
                    "local_settings": {
                        "start_date": backtest_range[0],
                        "end_date": backtest_range[1],
                    },
                    "product_selections": {
                        "day": {
                            "selected_paths": [
                                "CNFutures/日盘/AP.CZC",
                            ],
                        },
                    },
                },
            },
            "ui": {
                "local_settings": {
                    "start_date": "2026-01-01",
                    "end_date": "2026-01-31",
                },
            },
        },
    }


@pytest.mark.parametrize("analysis", ["ic", "backtest"])
def test_v2_uses_only_selected_analysis(analysis: str) -> None:
    identity = derive_sample_identity(_run_spec_v2([analysis]))

    assert identity["sample_start"] == "2024-01-02"
    assert identity["sample_end"] == "2024-12-31"


def test_v2_same_scope_has_one_identity_across_selected_analyses() -> None:
    spec = _run_spec_v2(["ic", "backtest"])
    identity = derive_sample_identity(spec)
    ic_identity = derive_sample_identity({**spec, "analyses": ["ic"]})
    backtest_identity = derive_sample_identity({
        **spec,
        "analyses": ["backtest"],
    })

    assert identity["sample_start"] == "2024-01-02"
    assert identity["sample_end"] == "2024-12-31"
    assert identity["sample_hash"] == ic_identity["sample_hash"]
    assert identity["sample_hash"] == backtest_identity["sample_hash"]


def test_v2_rejects_conflicting_selected_analysis_ranges() -> None:
    spec = _run_spec_v2(
        ["ic", "backtest"],
        backtest_range=("2025-01-02", "2025-12-31"),
    )

    with pytest.raises(ValueError, match="one unambiguous date range"):
        derive_sample_identity(spec)
