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
    # 派生组（精选组）元信息
    n_base: int = 0
    n_derived: int = 0
    derived_info: Any = None  # [{base_group, name, id, product_names}, ...] | None
    group_names: Any = None  # {expanded_group_index: display_name}
    hold_amounts_np: np.ndarray | None = None  # (T, M, P) float — 每期实际持仓金额 (refs #100)
    position_quantities_np: np.ndarray | None = None  # (T, M, P) float — 每期合约手数/单位数
    margin_occupied_np: np.ndarray | None = None  # (T, M) float — 每期保证金占用
    total_equity_np: np.ndarray | None = None  # (T, M) float — 每期末总权益
    cash_np: np.ndarray | None = None  # (T, M) float — 每期末可用现金
    initial_capital: float | None = None
    price_np: np.ndarray | None = None
    open_fee_fixed_vec: np.ndarray | None = None
    close_fee_fixed_vec: np.ndarray | None = None
    close_today_fee_fixed_vec: np.ndarray | None = None
    point_value_vec: np.ndarray | None = None
    min_tick_vec: np.ndarray | None = None
    min_trade_quantity_vec: np.ndarray | None = None
    margin_ratio_vec: np.ndarray | None = None
    is_margin_traded_vec: np.ndarray | None = None

    def summary_for_group(self, group_index: int) -> dict[str, Any]:
        if self.report_df.empty or group_index not in self.report_df.index:
            return {}
        return self.report_df.loc[group_index].to_dict()
