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
    product_fee_contrib_np: np.ndarray
    returns_np: np.ndarray
    period_returns_np: np.ndarray
    membership_np: np.ndarray
    products_by_group: dict
    valid_cols: list
    open_fee_vec: np.ndarray
    close_fee_vec: np.ndarray        # 始终=平昨
    close_today_fee_vec: np.ndarray  # 始终=平今
    close_yesterday_fee_vec: np.ndarray  # 始终=平昨（同 close_fee_vec），用于前端分列展示
    index_list: list
    multi_session_active: bool
    rebalance_mode: str
    report_df: pd.DataFrame

    def summary_for_group(self, group_index: int) -> dict[str, Any]:
        if self.report_df.empty or group_index not in self.report_df.index:
            return {}
        return self.report_df.loc[group_index].to_dict()
