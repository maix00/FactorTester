"""Vectorized quantile portfolio statistics for one IC core test."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import pandas as pd

from tools.factors.tester_calc.single_factor_test.quantile_portfolio import (
    compute_quantile_portfolio_statistics,
)


@dataclass(frozen=True, slots=True)
class ICQuantilePortfolioStatistics:
    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return dict(self.payload)


class ICQuantilePortfolioStatisticsAdapter:
    analysis_type = "quantile_portfolio_statistics"
    input_kinds = ("factor_values", "forward_returns", "eligibility")
    output_kind = "quantile_portfolio_statistics"

    def execute(
        self,
        inputs: tuple[Mapping[str, Any], ...],
        parameters: Mapping[str, Any],
    ) -> ICQuantilePortfolioStatistics:
        if len(inputs) != 1:
            raise ValueError("quantile portfolio statistics requires one core test")
        values = inputs[0]
        panels = {kind: values.get(kind) for kind in self.input_kinds}
        if not isinstance(panels["factor_values"], pd.DataFrame):
            raise ValueError("factor_values must be a pandas DataFrame")
        if not isinstance(panels["forward_returns"], pd.DataFrame):
            raise ValueError("forward_returns must be a pandas DataFrame")
        if not isinstance(panels["eligibility"], pd.DataFrame):
            raise ValueError("eligibility must be a pandas DataFrame")
        portfolio = parameters.get("portfolio")
        if not isinstance(portfolio, Mapping):
            raise ValueError("portfolio parameters must be an object")
        allowed = {
            key: portfolio[key]
            for key in (
                "group_count", "modes", "target_margin_utilization",
                "initial_capital", "include_return_series", "margin_rates",
                "open_fee_rates", "close_fee_rates",
            )
            if key in portfolio
        }
        result = compute_quantile_portfolio_statistics(
            panels["factor_values"],
            panels["forward_returns"],
            eligibility=panels["eligibility"],
            **allowed,
        )
        return ICQuantilePortfolioStatistics(result)


__all__ = [
    "ICQuantilePortfolioStatistics",
    "ICQuantilePortfolioStatisticsAdapter",
]
