"""RunSpec-v2 execution-scope identity tests."""

from __future__ import annotations

import hashlib
import json

import pytest

from server.services.research_sample_identity import (
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


def test_frozen_product_selection_exposes_exact_membership() -> None:
    members = [
        "Product/Futures/CNFutures/_products/AP.CZC",
        "Product/Futures/CNFutures/_products/SI.GFE",
    ]
    selection = {
        "id": "product-group:metals",
        "paths": members,
        "resolution_sha256": hashlib.sha256(
            json.dumps(members, ensure_ascii=False, separators=(",", ":"))
            .encode()
        ).hexdigest(),
    }
    spec = {
        "run_spec_version": 3,
        "analyses": ["ic"],
        "configuration": {
            "shared": {"product_selections": {
                "product-group:metals": selection,
            }},
            "analyses": {
                "ic": {
                    "settings": {
                        "start_date": "2024-01-01",
                        "end_date": "2024-12-31",
                    },
                    "configuration_groups": [{
                        "product_scope_ref": "product-group:metals",
                    }],
                },
            },
        },
    }

    identity = derive_sample_identity(spec)

    assert identity["universe_members"] == members
    assert identity["universe_membership_assurance"] == "exact_frozen_product_scope"
    assert "partial_universe_overlap_not_detected" not in identity["limitations"]


def test_exact_members_are_order_and_duplicate_independent() -> None:
    first = "Product/Futures/CNFutures/_products/AP.CZC"
    second = "Product/Futures/CNFutures/_products/SI.GFE"
    spec = _run_spec_v2(["ic"])
    scope = spec["configuration"]["analyses"]["ic"]
    scope["paths"] = [first, second, first]

    reordered = _run_spec_v2(["ic"])
    reordered["configuration"]["analyses"]["ic"]["paths"] = [second, first]

    identity = derive_sample_identity(spec)
    reordered_identity = derive_sample_identity(reordered)

    assert identity["universe_members"] == [first, second]
    assert identity["universe_membership_assurance"] == "exact_frozen_product_scope"
    assert identity["sample_hash"] == reordered_identity["sample_hash"]
    assert identity["universe_members"] == reordered_identity["universe_members"]


def test_frozen_selection_with_mismatched_resolution_is_not_exact() -> None:
    identity = derive_sample_identity({
        "run_spec_version": 3,
        "analyses": ["ic"],
        "configuration": {
            "shared": {"product_selections": {
                "scope": {
                    "paths": ["Product/Futures/_products/AP.CZC"],
                    "resolution_sha256": "0" * 64,
                },
            }},
            "analyses": {"ic": {
                "settings": {
                    "start_date": "2024-01-01",
                    "end_date": "2024-12-31",
                },
                "products": ["Product/Futures"],
                "configuration_groups": [{"product_scope_ref": "scope"}],
            }},
        },
    })

    assert identity["universe_members"] == []
    assert identity["universe_membership_assurance"] == "not_proven"


def test_sample_identity_module_has_no_graph_dependency() -> None:
    from pathlib import Path

    for module in (
        "server/services/research_sample_identity.py",
        "server/services/research_sample_exposure.py",
    ):
        source = Path(module).read_text()
        assert "server.services.research_graph" not in source
