"""Shared frozen IC configuration cases for focused contract tests."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from tools.testers.ic_test.configuration import (
    CompiledICRunConfiguration,
    freeze_ic_run_configuration,
    migrate_flat_ic_settings,
)


ROC = "factor:v2:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
SGCCS = "factor:v2:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
MOMENTUM_SET = "factor-set:v2:ccccccccccccccccccccccccccccccccccccccccccc"


def flat_settings(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "factor_selections": [
            {"factor_ref": ROC, "factor_alias": "ROC|N:20d|$F:1m"},
            {"factor_ref": SGCCS, "factor_alias": "SgCCS|N:20d|$F:5m"},
        ],
        "product_path_selections": [
            {"product_path_selection_id": "night"},
            {"product_path_selection_id": "day"},
        ],
        "forward_return_horizons": {"sampling": "scale_aware"},
        "ic_lags": [1, 0],
        "ic_correlation": "both",
        "return_price_basis": "next_open_to_open_adjusted",
        "ic_decay_lags": [5, 1],
        "rolling_window": 20,
        "quantile_portfolio_statistics": {"enabled": False},
    }
    values.update(overrides)
    return values


def migrate_and_freeze(
    settings: Mapping[str, Any],
    frequencies: Mapping[str, Any],
    *,
    factor_set_members: Mapping[str, Iterable[str]] | None = None,
    output_requests: Iterable[str] = (),
) -> CompiledICRunConfiguration:
    authoring = migrate_flat_ic_settings(
        settings,
        factor_frequencies=frequencies,
        factor_set_members=factor_set_members,
        output_requests=output_requests,
    )
    return freeze_ic_run_configuration(authoring, factor_frequencies=frequencies)


def frozen_configuration(**overrides: object) -> CompiledICRunConfiguration:
    return migrate_and_freeze(
        flat_settings(**overrides),
        {ROC: "1m", SGCCS: "5m"},
    )
