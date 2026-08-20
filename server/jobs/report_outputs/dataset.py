"""One lazily derived dataset shared by all requested Job outputs."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import Any

from .analytics_tables import drawdown_episode_rows, period_return_rows
from .execution_tables import (
    cash_rows, exposure_rows, fill_rows, order_rows, position_rows, turnover_rows,
)
from .series import extract_series, metrics_rows, return_series
from .tables import fee_rows, margin_rows, ratio_rows


@dataclass
class ReportDataset:
    result: dict[str, Any]
    source: dict[str, Any]

    @cached_property
    def normalized_source(self) -> dict[str, Any]:
        """Expose retained ``group_execution`` fields like live-run fields.

        Live report generation receives the group-execution payload directly,
        while post-run generation loads it under its artifact name.  Builders
        must see the same source shape in both paths.
        """
        retained = self.source.get("group_execution")
        if not isinstance(retained, dict):
            return self.source
        return {**retained, **self.source}

    @cached_property
    def series(self):
        return extract_series(self.result, self.normalized_source)

    @cached_property
    def returns(self):
        return return_series(self.series)

    @cached_property
    def metrics(self):
        return metrics_rows(self.series)

    @cached_property
    def fees(self):
        return fee_rows(self.normalized_source)

    @cached_property
    def margins(self):
        return margin_rows(self.normalized_source)

    @cached_property
    def ratios(self):
        return ratio_rows(
            self.result, self.normalized_source, self.series,
            fee_rows_value=self.fees, margin_rows_value=self.margins,
        )

    @cached_property
    def orders(self):
        return order_rows(self.normalized_source)

    @cached_property
    def fills(self):
        return fill_rows(self.normalized_source)

    @cached_property
    def cash(self):
        return cash_rows(self.normalized_source)

    @cached_property
    def positions(self):
        return position_rows(self.normalized_source)

    @cached_property
    def exposures(self):
        return exposure_rows(self.normalized_source)

    @cached_property
    def turnover(self):
        return turnover_rows(self.normalized_source)

    @cached_property
    def drawdowns(self):
        return drawdown_episode_rows(self.series)

    @cached_property
    def period_returns(self):
        return period_return_rows(self.series)
