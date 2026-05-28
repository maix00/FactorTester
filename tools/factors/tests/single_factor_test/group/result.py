"""Result object for one group-test run."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(slots=True)
class GroupRunResult:
    """All artifacts produced by a single grouped backtest run."""

    fee_costs_np: np.ndarray
    trade_notional_ratio_np: np.ndarray
    gross_returns_np: np.ndarray
    product_gross_contrib_np: np.ndarray
    returns_np: np.ndarray
    products_by_group: dict
    valid_cols: list
    open_fee_vec: np.ndarray
    close_fee_vec: np.ndarray
    index_list: list
    multi_session_active: bool
    report_df: pd.DataFrame

    def summary_for_group(self, group_index: int) -> dict[str, Any]:
        if self.report_df.empty or group_index not in self.report_df.index:
            return {}
        return self.report_df.loc[group_index].to_dict()
