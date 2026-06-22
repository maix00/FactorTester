"""Result objects for group backtest runs."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd


@dataclass
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
    products_by_group: dict | None = None  # None → lazily built on first access
    _products_by_group_cache: dict | None = field(default=None, init=False, repr=False)
    valid_cols: list = field(default_factory=list)
    open_ratio_mat: np.ndarray = field(default_factory=lambda: np.empty(0))
    open_fixed_mat: np.ndarray | None = None
    close_ratio_mat: np.ndarray = field(default_factory=lambda: np.empty(0))     # 平昨
    close_fixed_mat: np.ndarray | None = None                                  # 平昨
    close_today_ratio_mat: np.ndarray = field(default_factory=lambda: np.empty(0))
    close_today_fixed_mat: np.ndarray | None = None
    use_closetoday_vec: np.ndarray | None = None                               # per-product bool
    index_list: list = field(default_factory=list)
    multi_session_active: bool = False
    rebalance_trigger: str = ""
    position_policy: str = ""
    report_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    group_names: Any = None  # {expanded_group_index: display_name}
    hold_amounts_np: np.ndarray | None = None  # (T, M, P) int64 minor units in base currency — 每期实际持仓金额
    target_amounts_before_floor_np: np.ndarray | None = None  # (T, M, P) int64 minor units in base currency
    prev_end_amounts_np: np.ndarray | None = None  # (T, M, P) int64 minor units in base currency
    position_quantities_np: np.ndarray | None = None  # (T, M, P) float — 每期合约手数/单位数
    margin_occupied_np: np.ndarray | None = None  # (T, M) int64 minor units in base currency
    pre_rebalance_total_equity_np: np.ndarray | None = None  # (T, M) int64 minor units in base currency
    post_rebalance_total_equity_np: np.ndarray | None = None  # (T, M) int64 minor units in base currency
    total_equity_np: np.ndarray | None = None  # (T, M) int64 minor units in base currency
    pre_rebalance_cash_np: np.ndarray | None = None  # (T, M) int64 minor units in base currency
    post_rebalance_cash_np: np.ndarray | None = None  # (T, M) int64 minor units in base currency
    post_settlement_cash_np: np.ndarray | None = None  # (T, M) float64 minor units — 盯市后现金（非结算bar为NaN）
    cash_np: np.ndarray | None = None  # (T, M) int64 minor units in base currency
    buy_fee_amount_np: np.ndarray | None = None  # (T, M) int64 minor units in base currency
    sell_fee_amount_np: np.ndarray | None = None  # (T, M) int64 minor units in base currency
    initial_capital: float | None = None
    price_np: np.ndarray | None = None
    point_value_mat: np.ndarray | None = None
    min_tick_mat: np.ndarray | None = None
    min_trade_quantity_mat: np.ndarray | None = None
    margin_ratio_mat: np.ndarray | None = None
    is_margin_traded_vec: np.ndarray | None = None
    base_currency: str = "CNY"
    product_currency_vec: np.ndarray | None = None
    currency_conversion_fee_rate: float = 0.0
    liquidity_capacity_np: np.ndarray | None = None  # (T, M, P) float — 每期每品种成交额限额(元) (refs #110)
    liquidity_modes: list | None = None  # [str] per-group
    liquidity_percents: list | None = None  # [float] per-group
    one_lot_margin_np: np.ndarray | None = None  # (T, M, P) float product currency — 一手保证金展示估算
    one_lot_fee_np: np.ndarray | None = None  # (T, M, P) float product currency — 一手手续费展示估算

    def get_products_by_group(self) -> dict:
        """Lazy builder: {group_idx: {idx_entry: [product_names]}}."""
        cached = self._products_by_group_cache
        if cached is not None:
            return cached
        if self.products_by_group is not None:
            self._products_by_group_cache = self.products_by_group
            return self.products_by_group

        membership = np.asarray(self.membership_np)
        valid = list(self.valid_cols)
        idx_list = list(self.index_list)
        if membership.size == 0 or not valid or not idx_list:
            return {}

        group_count = membership.shape[1] if membership.ndim >= 2 else 0
        result: dict = {}
        for g in range(group_count):
            group_dict = {}
            for t, idx_entry in enumerate(idx_list):
                mask_row = membership[t, g]
                if hasattr(mask_row, 'ndim') and mask_row.ndim > 0:
                    names = [valid[i] for i in np.where(mask_row)[0]]
                elif mask_row:
                    names = list(valid)
                else:
                    names = []
                group_dict[idx_entry] = names
            result[g] = group_dict
        self._products_by_group_cache = result
        return result

    def summary_for_group(self, group_index: int) -> dict[str, Any]:
        if self.report_df.empty or group_index not in self.report_df.index:
            return {}
        return self.report_df.loc[group_index].to_dict()


@dataclass(slots=True)
class MergedGroupRunResult:
    """One merged simulate result on a global flat-group axis.

    This owns the full execution output of a shared simulation and the mapping
    metadata needed to slice back into per-submission / per-factor results.
    """

    merged_result: GroupRunResult
    group_owner: list[dict[str, Any]]
    submission_slices: dict[str, list[int]]
    factor_slices: dict[str, list[int]]
    overlap_batches: list[list[str]]
