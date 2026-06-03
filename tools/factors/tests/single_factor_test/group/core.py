"""Group test core implementation."""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple, cast

import numpy as np
import pandas as pd
from tqdm import tqdm

from Settings import factor_info_path
from tools.data.DataColumn import DataColumn
from tools.data.DataFreq import DataFreq
from tools.factors import Factor
from tools.factors.FactorTester import _align_ts_to_index, _extract_signal_index
from tools.factors.Parameters import FactorNextPeriodReturns
from tools.factors.tests.single_factor_test.group.result import GroupRunResult


_TARGET_REBUILD_MAX_ITERATIONS = 8
_EACH_PERIOD_TARGET_MAX_ITERATIONS = 16


def infer_periods_per_year(index_like) -> float:
    """Infer strategy periods/year from realised signal timestamps."""
    idx = pd.DatetimeIndex(_extract_signal_index(pd.Index(index_like)))
    idx = idx.dropna()
    if len(idx) < 2:
        return 252.0
    per_day = pd.Series(1, index=idx.normalize()).groupby(level=0).sum()
    median_per_day = float(per_day.median()) if not per_day.empty else 1.0
    if median_per_day > 1:
        return median_per_day * 252.0
    unique_days = pd.DatetimeIndex(per_day.index).sort_values()
    if len(unique_days) < 2:
        return 252.0
    business_days = np.busday_count(
        unique_days[0].date().isoformat(),
        (unique_days[-1] + pd.Timedelta(days=1)).date().isoformat(),
    )
    if business_days <= 0:
        return 252.0
    return max(1.0, len(unique_days) / business_days * 252.0)


def _build_each_period_targets_with_sell_fee(
    curr_mask: np.ndarray,
    prev_amounts: np.ndarray,
    wealth: np.ndarray,
    close_fees: np.ndarray,
) -> np.ndarray:
    """Solve equal-weight targets after paying sell fees without rebuilding targets repeatedly."""
    counts = curr_mask.sum(axis=1).astype(float)
    targets = np.zeros_like(prev_amounts, dtype=float)
    non_empty = counts > 0
    if not non_empty.any():
        return targets

    non_member_fee = (prev_amounts * (~curr_mask).astype(float) * close_fees).sum(axis=1)
    active = curr_mask & (prev_amounts > 0)
    target_each = np.zeros_like(wealth, dtype=float)

    for _ in range(_EACH_PERIOD_TARGET_MAX_ITERATIONS):
        active_fee_sum = (active.astype(float) * close_fees).sum(axis=1)
        active_fee_amount = (prev_amounts * active.astype(float) * close_fees).sum(axis=1)
        denom = np.maximum(counts - active_fee_sum, 1e-12)
        next_target_each = np.divide(
            wealth - non_member_fee - active_fee_amount,
            denom,
            out=np.zeros_like(wealth, dtype=float),
            where=non_empty,
        )
        next_target_each = np.maximum(0.0, next_target_each)
        next_active = curr_mask & (prev_amounts > next_target_each[:, np.newaxis])
        target_each = next_target_each
        if np.array_equal(next_active, active):
            break
        active = next_active

    targets[non_empty] = (
        curr_mask[non_empty].astype(float)
        * target_each[non_empty, np.newaxis]
    )
    return targets


def align_table_for_group(factor: Factor, raw_table: pd.DataFrame) -> pd.DataFrame:
    """Temporarily project a raw FE/RE table onto factor signal timestamps."""
    from tools.factors.FactorExpr import SignalAlign, signal_align

    if raw_table is None or (isinstance(raw_table, pd.DataFrame) and raw_table.empty):
        return pd.DataFrame() if isinstance(raw_table, pd.DataFrame) else raw_table

    def _find_signal_align(node: Any) -> Optional[SignalAlign]:
        if isinstance(node, SignalAlign):
            return node
        for child in getattr(node, "_operands", ()):
            found = _find_signal_align(child)
            if found is not None:
                return found
        return None

    signal_node = _find_signal_align(factor._expr)
    if signal_node is None:
        return raw_table

    return signal_align(
        raw_table,
        signal_node.signal_freq,
        basepoint=signal_node.basepoint,
        daily_basepoint=signal_node.daily_basepoint,
        end_session_skip=signal_node.end_session_skip,
        end_session_gap=signal_node.end_session_gap,
    )


def get_factor_table_for_group(tester: Any, factor: Factor) -> pd.DataFrame:
    """Get the factor exposure table for group testing.

    Data source priority:
      1. FactorRunResult.table — tester-scoped, no cross-tester pollution.
      2. factor.evaluate(tester.products) — compute fresh (last resort).
    """
    # 优先从 tester 隔离的 FactorRunResult 获取
    r = tester.results.get(factor) if hasattr(tester, 'results') else None
    if r is not None:
        if isinstance(r.table, pd.DataFrame) and not r.table.empty:
            return cast(pd.DataFrame, r.table)
        if isinstance(getattr(r, 'func_table', None), pd.DataFrame) and not cast(pd.DataFrame, r.func_table).empty:
            # func_table already includes $Rev negation via _func_expr = neg(source_expr)
            # → apply SignalAlign directly, skip factor.evaluate()
            return align_table_for_group(factor, r.func_table)

    # 最后兜底：重新计算
    return factor.evaluate(tester.products)


def _build_normalized_liquidity_capacity(
    products: list,
    signal_index: list,
    freq: DataFreq,
    start_date: Any,
    end_date: Any,
) -> np.ndarray | None:
    """Return (T, P) capacity shares from turnover, fallbacking to volume*price*multiplier.

    The simulator uses normalized wealth (initial capital = 1), so raw market
    notional is converted into per-period cross-sectional shares.  A 20%
    liquidity setting therefore means "this strategy may trade up to 20% of
    the current period's cross-sectional tradable notional, allocated by
    product liquidity".
    """
    if not products or not signal_index:
        return None
    signal_ts = pd.DatetimeIndex(pd.to_datetime(signal_index))
    T = len(signal_ts)
    P = len(products)
    raw = np.zeros((T, P), dtype=float)

    for pi, product in enumerate(products):
        try:
            dm = getattr(product, freq.name)
            cols = [DataColumn.TURNOVER.name, DataColumn.VOLUME.name, DataColumn.CLOSE_ADJUSTED.name]
            data = dm.get_and_adjust_cols(cols, copy=False, start_calc_point=start_date)
            if data.empty:
                continue
            idx = pd.DatetimeIndex(_extract_signal_index(data.index))
            frame = data.copy(deep=False)
            frame.index = idx
            if end_date is not None:
                _ed = _align_ts_to_index(end_date, frame.index)
                frame = frame[frame.index <= _ed]
            if frame.empty:
                continue
            if DataColumn.TURNOVER.name in frame.columns and frame[DataColumn.TURNOVER.name].notna().any():
                amount = pd.to_numeric(frame[DataColumn.TURNOVER.name], errors="coerce").fillna(0.0)
            elif DataColumn.VOLUME.name in frame.columns and DataColumn.CLOSE_ADJUSTED.name in frame.columns:
                multiplier = float(getattr(product, "point_value", None) or 1.0)
                amount = (
                    pd.to_numeric(frame[DataColumn.VOLUME.name], errors="coerce").fillna(0.0)
                    * pd.to_numeric(frame[DataColumn.CLOSE_ADJUSTED.name], errors="coerce").fillna(0.0)
                    * multiplier
                )
            else:
                continue
            amount = amount.sort_index()
            values = amount.to_numpy(dtype=float)
            times = pd.DatetimeIndex(amount.index)
            cum = np.concatenate([[0.0], np.cumsum(np.where(np.isfinite(values) & (values > 0), values, 0.0))])
            right = np.searchsorted(times, signal_ts, side="right")
            left = np.concatenate([[0], right[:-1]])
            raw[:, pi] = cum[right] - cum[left]
        except Exception:
            continue

    row_sum = raw.sum(axis=1)
    if not np.any(row_sum > 0):
        return None
    return np.divide(
        raw,
        row_sum[:, np.newaxis],
        out=np.zeros_like(raw, dtype=float),
        where=row_sum[:, np.newaxis] > 0,
    )


def build_target_amounts(
    curr_mask_all: np.ndarray,
    prev_end_amounts: np.ndarray,
    wealth_before_trade: np.ndarray,
    rebalance_mode: str,
    close_fee_vec: np.ndarray | None = None,
    close_fee_already_paid: bool = False,
) -> np.ndarray:
    """Build next-period target holdings for all groups with vectorized operations.

    Parameters
    ----------
    close_fee_vec : (P,) or (n_groups, P) array of per-product close fee rates.
        Accepts 1-D (P,) for backward compatibility and broadcasts to n_groups.
        When provided, the capital released from exits is reduced by the
        proportional close fee before being allocated to entering products.
    close_fee_already_paid : bool
        For each-period full rebalancing, treat ``wealth_before_trade`` as the
        post-sell-fee available wealth.  This is used by the simulator after it
        has computed the sell leg first.
    """
    curr_mask = np.asarray(curr_mask_all, dtype=bool)
    prev_amounts = np.asarray(prev_end_amounts, dtype=float)
    wealth = np.asarray(wealth_before_trade, dtype=float)
    close_fees = np.asarray(close_fee_vec, dtype=float) if close_fee_vec is not None else None
    if close_fees is not None and close_fees.ndim == 1:
        close_fees = close_fees[np.newaxis, :]  # (1, P) → broadcast to (n_groups, P)

    def _equal_alloc(mask: np.ndarray, capital: np.ndarray) -> np.ndarray:
        counts_local = mask.sum(axis=1).astype(float)
        out = np.zeros_like(prev_amounts, dtype=float)
        rows = counts_local > 0
        if rows.any():
            out[rows] = (
                mask[rows].astype(float)
                * (capital[rows] / counts_local[rows])[:, np.newaxis]
            )
        return out

    counts = curr_mask.sum(axis=1).astype(float)
    targets = np.zeros_like(prev_amounts, dtype=float)
    non_empty = counts > 0
    if not non_empty.any():
        return targets

    if rebalance_mode == "each_period":
        if close_fees is not None and not close_fee_already_paid:
            return _build_each_period_targets_with_sell_fee(
                curr_mask, prev_amounts, wealth, np.broadcast_to(close_fees, prev_amounts.shape)
            )
        return _equal_alloc(curr_mask, wealth)

    prev_mask = prev_amounts > 0
    staying = curr_mask & prev_mask
    exiting = prev_mask & (~curr_mask)
    entering = curr_mask & (~prev_mask)
    n_entering = entering.sum(axis=1).astype(float)
    # Gross released amount (before close fee)
    sell_amounts = (prev_amounts * exiting.astype(float)).sum(axis=1)

    # Subtract close fee from released capital — the actual cash available
    # after selling is sell_amounts * (1 - close_fee) per exiting product.
    if close_fees is not None:
        sell_fees = (prev_amounts * exiting.astype(float) * close_fees).sum(axis=1)
        released = np.maximum(0.0, sell_amounts - sell_fees)
    else:
        released = sell_amounts

    targets = prev_amounts * staying.astype(float)
    rows_with_released = (n_entering > 0) & (released > 0)
    if rows_with_released.any():
        targets[rows_with_released] += _equal_alloc(entering, released)[rows_with_released]

    fallback_rows = non_empty & (n_entering > 0) & (~rows_with_released)
    if rebalance_mode == "buy_and_hold":
        # If membership expands without any released capital, equal-weight once to fund entrants.
        if fallback_rows.any():
            targets[fallback_rows] = _equal_alloc(curr_mask, wealth)[fallback_rows]
    elif rebalance_mode == "recycle":
        # Keep staying holdings; only released exit capital can fund entrants.
        # If no capital was released, do not inject external cash into new members.
        initial_rows = fallback_rows & (~prev_mask.any(axis=1))
        if initial_rows.any():
            targets[initial_rows] = _equal_alloc(curr_mask, wealth)[initial_rows]
    else:
        raise ValueError(f"Unknown rebalance_mode: {rebalance_mode!r}")

    totals = targets.sum(axis=1)
    # Rescale to wealth only when we did NOT deduct close fees (backward
    # compat).  When close_fee_mat is provided, exiting capital is already
    # net of fees so targets.sum() < wealth is expected — do not rescale.
    rescale = (
        non_empty
        & (totals > 0)
        & (np.abs(totals - wealth) > 1e-12)
        & (close_fees is None)
    )
    if rescale.any():
        targets[rescale] *= (wealth[rescale] / totals[rescale])[:, np.newaxis]
    return targets


def build_multi_session_target_amounts(
    curr_mask_all: np.ndarray,
    prev_end_amounts: np.ndarray,
    wealth_before_trade: np.ndarray,
    has_bar: np.ndarray,
    close_fee_vec: np.ndarray,
) -> np.ndarray:
    """Build multi-session target holdings for all groups in one matrix pass.

    close_fee_vec accepts (P,) for backward compat and broadcasts to n_groups.
    """
    curr_mask = np.asarray(curr_mask_all, dtype=bool)
    prev_amounts = np.asarray(prev_end_amounts, dtype=float)
    wealth = np.asarray(wealth_before_trade, dtype=float)
    has_bar_vec = np.asarray(has_bar, dtype=bool)
    close_fees = np.asarray(close_fee_vec, dtype=float)
    if close_fees.ndim == 1:
        close_fees = close_fees[np.newaxis, :]  # (1, P) → broadcast

    def _equal_alloc(mask: np.ndarray, capital: np.ndarray) -> np.ndarray:
        counts_local = mask.sum(axis=1).astype(float)
        out = np.zeros_like(prev_amounts, dtype=float)
        rows = counts_local > 0
        if rows.any():
            out[rows] = mask[rows].astype(float) * (capital[rows] / counts_local[rows])[:, np.newaxis]
        return out

    non_empty = curr_mask.any(axis=1)
    targets = np.zeros_like(prev_amounts, dtype=float)
    if not non_empty.any():
        return targets

    prev_mask = prev_amounts > 0
    staying = curr_mask & prev_mask
    exiting = prev_mask & (~curr_mask)
    entering = curr_mask & (~prev_mask)
    exiting_with_bar = exiting & has_bar_vec[np.newaxis, :]
    exiting_without_bar = exiting & (~has_bar_vec[np.newaxis, :])
    entering_with_bar = entering & has_bar_vec[np.newaxis, :]

    sell_amounts = prev_amounts * exiting_with_bar
    recycled = np.maximum(
        0.0,
        sell_amounts.sum(axis=1) - (sell_amounts * close_fees).sum(axis=1),
    )
    entering_counts = entering_with_bar.sum(axis=1).astype(float)

    targets = prev_amounts * (staying | exiting_without_bar)
    funded = non_empty & (entering_counts > 0) & (recycled > 0)
    if funded.any():
        targets[funded] += _equal_alloc(entering_with_bar, recycled)[funded]

    initial_funding = non_empty & (~prev_mask.any(axis=1)) & (entering_counts > 0)
    if initial_funding.any():
        targets[initial_funding] = _equal_alloc(entering_with_bar, wealth)[initial_funding]

    # multi-session 已扣 close fee，不 rescale 回 wealth（targets.sum < wealth 是正确的）
    return targets


def apply_liquidity_execution(
    prev_end_amounts: np.ndarray,
    ideal_target_amounts: np.ndarray,
    wealth_before_trade: np.ndarray,
    capacity_amounts: np.ndarray,
    open_fee_mat: np.ndarray,
    close_fee_mat: np.ndarray,
) -> np.ndarray:
    """Convert ideal targets to executable targets under per-product notional caps.

    Capacity is expressed in the same normalized notional unit as wealth
    (initial wealth = 1).  Sells are capped first; remaining cash funds buys
    by executable capacity weights, so unfilled cash stays idle.
    """
    prev = np.asarray(prev_end_amounts, dtype=float)
    ideal = np.asarray(ideal_target_amounts, dtype=float)
    wealth = np.asarray(wealth_before_trade, dtype=float)
    caps = np.asarray(capacity_amounts, dtype=float)
    if caps.ndim == 1:
        caps = caps[np.newaxis, :]
    caps = np.where(np.isfinite(caps) & (caps >= 0), caps, np.inf)

    delta = ideal - prev
    desired_sell = np.clip(-delta, 0.0, None)
    desired_buy = np.clip(delta, 0.0, None)

    sell_exec = np.minimum(desired_sell, caps)
    after_sell = prev - sell_exec
    sell_fee = (sell_exec * close_fee_mat).sum(axis=1)
    cash_before = np.maximum(0.0, wealth - prev.sum(axis=1))
    cash_after_sell = np.maximum(0.0, cash_before + sell_exec.sum(axis=1) - sell_fee)

    buy_capacity = np.minimum(desired_buy, caps)
    buy_capacity = np.where(np.isfinite(buy_capacity) & (buy_capacity > 0), buy_capacity, 0.0)
    buy_capacity_sum = buy_capacity.sum(axis=1)
    buy_budget = np.minimum(cash_after_sell, buy_capacity_sum)

    buy_exec = np.zeros_like(prev, dtype=float)
    rows = buy_capacity_sum > 0
    if rows.any():
        buy_exec[rows] = buy_capacity[rows] * (buy_budget[rows] / buy_capacity_sum[rows])[:, np.newaxis]

    # Do not allow open fees to push total wealth negative.  If fees are large,
    # scale the buy leg down once more using the effective cash requirement.
    buy_cash_need = (buy_exec * (1.0 + open_fee_mat)).sum(axis=1)
    over = buy_cash_need > np.maximum(cash_after_sell, 0.0) + 1e-12
    if over.any():
        scale = np.divide(
            cash_after_sell[over],
            buy_cash_need[over],
            out=np.zeros_like(cash_after_sell[over]),
            where=buy_cash_need[over] > 0,
        )
        buy_exec[over] *= scale[:, np.newaxis]

    return after_sell + buy_exec


def simulate_groups(
    membership_np: np.ndarray,
    returns_np: np.ndarray,
    open_fee_mat: np.ndarray,
    close_fee_mat: np.ndarray,
    *,
    rebalance_mode: str = "buy_and_hold",
    close_today_fee_mat: np.ndarray | None = None,
    data_has_bar: np.ndarray | None = None,
    group_to_variant: np.ndarray | None = None,
    rebalance_modes: np.ndarray | list[str] | None = None,
    liquidity_capacity_np: np.ndarray | None = None,
    liquidity_modes: np.ndarray | list[str] | None = None,
    liquidity_percents: np.ndarray | list[float] | None = None,
) -> dict:
    """Matrix simulation of group returns over T periods for n_groups groups.

    This is the *single shared engine* for both full group tests and
    derived-group simulations.  The caller slices membership/returns down
    to the desired products before calling.

    Parameters
    ----------
    membership_np : (T, n_groups, P) bool
    returns_np : (T, P) float — per-product period returns (NaN/inf/-1 already filled)
    open_fee_mat : (M, P) float — per-variant per-product open fee rates (M >= n_groups)
    close_fee_mat : (M, P) float — per-variant per-product close fee rates
    close_today_fee_mat : (M, P) float | None — when set, overrides close_fee_mat for exiting
    data_has_bar : (T, P) bool | None — when set, enables multi-session strategy
    rebalance_mode : "each_period" | "buy_and_hold" | "recycle"
    group_to_variant : (n_groups, M) bool | None — maps original groups to fee variants.
        When None, M == n_groups and identity mapping is used (backward compatible).
        Each original group g maps to one or more variants; membership for variant
        v is membership[:, g, :] where group_to_variant[g, v] == True.
    rebalance_modes : (n_groups,) or (M,) string array | None
        Optional per-group/per-variant rebalance mode. When omitted, all rows use
        rebalance_mode.

    Returns
    -------
    dict with keys: net_returns_np, gross_returns_np, product_gross_contrib_np,
    product_fee_contrib_np, fee_costs_np, trade_notional_ratio_np, multi_session_triggered,
    target_amounts_np, prev_end_amounts_np

    target_amounts_np : (T, M, P) float — 每期调仓后目标持仓金额
    prev_end_amounts_np : (T, M, P) float — 每期结束时实际持仓金额（refs #100）
    """
    T, n_groups, P = membership_np.shape

    rebalance_modes_arr = None
    if rebalance_modes is not None:
        rebalance_modes_arr = np.asarray(rebalance_modes, dtype=object)
    liquidity_modes_arr = None
    if liquidity_modes is not None:
        liquidity_modes_arr = np.asarray(liquidity_modes, dtype=object)
    liquidity_percents_arr = None
    if liquidity_percents is not None:
        liquidity_percents_arr = np.asarray(liquidity_percents, dtype=float)

    # ── 建立 group→variant 映射，扩展 membership ──
    if group_to_variant is not None:
        g2v = np.asarray(group_to_variant, dtype=bool)
        if g2v.shape[0] != n_groups:
            raise ValueError(
                f"group_to_variant shape[0]={g2v.shape[0]} != n_groups={n_groups}"
            )
        M = g2v.shape[1]
        # Maps variant index → group index
        _variant_to_group = np.full(M, -1, dtype=int)
        for g in range(n_groups):
            vs = np.where(g2v[g])[0]
            _variant_to_group[vs] = g
        if (_variant_to_group < 0).any():
            raise ValueError("Every variant must map to exactly one group")
        # Expand membership: (T, n_groups, P) → (T, M, P)
        membership_np = membership_np[:, _variant_to_group, :]
        if rebalance_modes_arr is not None and rebalance_modes_arr.shape[0] == n_groups:
            rebalance_modes_arr = rebalance_modes_arr[_variant_to_group]
        if liquidity_modes_arr is not None and liquidity_modes_arr.shape[0] == n_groups:
            liquidity_modes_arr = liquidity_modes_arr[_variant_to_group]
        if liquidity_percents_arr is not None and liquidity_percents_arr.shape[0] == n_groups:
            liquidity_percents_arr = liquidity_percents_arr[_variant_to_group]
    else:
        M = n_groups
        _variant_to_group = np.arange(M, dtype=int)
    if rebalance_modes_arr is None:
        rebalance_modes_arr = np.full(M, rebalance_mode, dtype=object)
    elif rebalance_modes_arr.shape[0] != M:
        raise ValueError(
            f"rebalance_modes length={rebalance_modes_arr.shape[0]} != expanded groups={M}"
        )
    if liquidity_modes_arr is None:
        liquidity_modes_arr = np.full(M, "infinite", dtype=object)
    elif liquidity_modes_arr.shape[0] != M:
        raise ValueError(
            f"liquidity_modes length={liquidity_modes_arr.shape[0]} != expanded groups={M}"
        )
    if liquidity_percents_arr is None:
        liquidity_percents_arr = np.full(M, 100.0, dtype=float)
    elif liquidity_percents_arr.shape[0] != M:
        raise ValueError(
            f"liquidity_percents length={liquidity_percents_arr.shape[0]} != expanded groups={M}"
        )
    liquidity_capacity_arr = None
    if liquidity_capacity_np is not None:
        liquidity_capacity_arr = np.asarray(liquidity_capacity_np, dtype=float)
        if liquidity_capacity_arr.shape != (T, P):
            raise ValueError(
                f"liquidity_capacity_np shape={liquidity_capacity_arr.shape} != {(T, P)}"
            )
    effective_close_fee_mat = close_today_fee_mat  # None means use close_fee_mat
    multi_session_active = data_has_bar is not None
    multi_session_triggered = 0

    # Output arrays — sized by M (total variants)
    net_returns_np = np.zeros((T, M), dtype=float)
    gross_returns_np = np.zeros((T, M), dtype=float)
    product_gross_contrib_np = np.zeros((T, M, P), dtype=float)
    product_fee_contrib_np = np.zeros((T, M, P), dtype=float)
    fee_costs_np = np.zeros((T, M), dtype=float)
    trade_notional_ratio_np = np.zeros((T, M), dtype=float)

    member_counts = membership_np.sum(axis=2).astype(float)  # (M,) per t
    wealth = np.ones(M, dtype=float)
    prev_end_amounts = np.zeros((M, P), dtype=float)

    # 记录每期持仓金额 (refs #100)
    target_amounts_np = np.zeros((T, M, P), dtype=float)
    prev_end_amounts_np = np.zeros((T, M, P), dtype=float)

    for t in range(T):
        curr_mask_all = membership_np[t]           # (M, P)
        curr_count_all = member_counts[t]           # (M,)
        wealth_before_trade = wealth.copy()

        # Multi-session check
        has_bar_t = data_has_bar[t] if multi_session_active else np.ones(P, dtype=bool)
        is_mixed_t = multi_session_active and has_bar_t.any() and (~has_bar_t).any()

        target_amounts = np.zeros((M, P), dtype=float)
        empty_mask = curr_count_all == 0
        non_empty_mask = ~empty_mask

        if multi_session_active and not has_bar_t.any():
            target_amounts = prev_end_amounts.copy()
            product_gross_contrib, gross = compute_group_gross_returns(
                target_amounts, wealth_before_trade, returns_np[t],
            )
            wealth = wealth_before_trade * (1.0 + gross)
            gross_returns_np[t] = gross
            product_gross_contrib_np[t] = product_gross_contrib
            net_returns_np[t] = gross
            prev_end_amounts = target_amounts * (1.0 + returns_np[t][np.newaxis, :])
            target_amounts_np[t] = target_amounts
            prev_end_amounts_np[t] = prev_end_amounts
            continue

        # --- Empty groups ---
        if empty_mask.any():
            sell_empty = prev_end_amounts[empty_mask]
            empty_target = np.zeros_like(sell_empty)
            if multi_session_active:
                empty_target[:, ~has_bar_t] = sell_empty[:, ~has_bar_t]
            close_rates_empty = effective_close_fee_mat[empty_mask] if effective_close_fee_mat is not None else close_fee_mat[empty_mask]
            _, sell_fee_empty = compute_sell_fee(
                sell_empty, empty_target, close_rates_empty,
                close_today_fee_vec=None,
            )
            sell_fee_ratio_empty = np.divide(
                sell_fee_empty, wealth_before_trade[empty_mask],
                out=np.zeros_like(sell_fee_empty, dtype=float),
                where=wealth_before_trade[empty_mask] > 0,
            )
            empty_gross_contrib, gross_empty = compute_group_gross_returns(
                empty_target, wealth_before_trade[empty_mask], returns_np[t],
            )
            net_ret_empty = gross_empty - sell_fee_ratio_empty
            wealth[empty_mask] = wealth_before_trade[empty_mask] * (1.0 + net_ret_empty)
            gross_returns_np[t, empty_mask] = gross_empty
            product_gross_contrib_np[t, empty_mask] = empty_gross_contrib
            sell_fee_per = np.clip(sell_empty - empty_target, 0.0, None) * close_rates_empty
            empty_fee_contrib = np.where(
                wealth_before_trade[empty_mask, np.newaxis] > 0,
                sell_fee_per / wealth_before_trade[empty_mask, np.newaxis],
                0.0,
            )
            product_fee_contrib_np[t, empty_mask] = empty_fee_contrib
            fee_costs_np[t, empty_mask] = sell_fee_ratio_empty
            net_returns_np[t, empty_mask] = net_ret_empty
            prev_end_amounts[empty_mask] = empty_target * (1.0 + returns_np[t][np.newaxis, :])

        if not non_empty_mask.any():
            # 记录本期持仓金额（全空组，target_amounts 已在上方设为零）(refs #100)
            target_amounts_np[t] = target_amounts
            prev_end_amounts_np[t] = prev_end_amounts
            continue

        ne_idx = np.where(non_empty_mask)[0]

        # Per-group fee vectors for this step
        ne_open_fee = open_fee_mat[ne_idx]      # (k, P)
        ne_close_fee = close_fee_mat[ne_idx]     # (k, P)
        ne_close_today = effective_close_fee_mat[ne_idx] if effective_close_fee_mat is not None else None
        target_close_fee_mat = effective_close_fee_mat if effective_close_fee_mat is not None else close_fee_mat

        if is_mixed_t:
            multi_session_triggered += 1
        unique_modes = list(dict.fromkeys(str(m or rebalance_mode) for m in rebalance_modes_arr))
        liquidity_active_t = liquidity_capacity_arr is not None and np.any(liquidity_modes_arr == "percent")
        executable_capacity_t = None
        if liquidity_active_t:
            _liq_cap = cast(np.ndarray, liquidity_capacity_arr)  # type-narrow: guarded by liquidity_active_t
            base_capacity = np.where(
                np.isfinite(_liq_cap[t]) & (_liq_cap[t] > 0),
                _liq_cap[t],
                0.0,
            )
            percent_scale = np.clip(liquidity_percents_arr, 0.0, 100.0) / 100.0
            percent_rows = liquidity_modes_arr == "percent"
            executable_capacity_t = np.full((M, P), np.inf, dtype=float)
            executable_capacity_t[percent_rows] = base_capacity[np.newaxis, :] * percent_scale[percent_rows, np.newaxis]

        def _build_targets_for_wealth(
            wealth_for_target: np.ndarray,
            *,
            close_fee_already_paid: bool = False,
        ) -> np.ndarray:
            if is_mixed_t:
                return build_multi_session_target_amounts(
                    curr_mask_all, prev_end_amounts, wealth_for_target,
                    has_bar_t, target_close_fee_mat,
                )
            if len(unique_modes) == 1:
                return build_target_amounts(
                    curr_mask_all, prev_end_amounts, wealth_for_target,
                    unique_modes[0], close_fee_vec=target_close_fee_mat,
                    close_fee_already_paid=close_fee_already_paid,
                )
            next_targets = np.zeros_like(prev_end_amounts, dtype=float)
            for mode in unique_modes:
                mode_mask = rebalance_modes_arr == mode
                if not mode_mask.any():
                    continue
                next_targets[mode_mask] = build_target_amounts(
                    curr_mask_all[mode_mask],
                    prev_end_amounts[mode_mask],
                    wealth_for_target[mode_mask],
                    mode,
                    close_fee_vec=target_close_fee_mat[mode_mask],
                    close_fee_already_paid=close_fee_already_paid,
                )
            return next_targets

        target_amounts = _build_targets_for_wealth(wealth_before_trade)

        ne_target = target_amounts[ne_idx]
        ne_prev = prev_end_amounts[ne_idx]
        ne_wb = wealth_before_trade[ne_idx]
        ne_cc = curr_count_all[ne_idx]
        ne_ret = returns_np[t]

        # Step 1: sell first, pay sell fee, then rebuild target with remaining wealth.
        sell, sell_fee_candidate = _compute_sell_fee_per_group(
            ne_prev, ne_target, ne_close_fee,
            close_today_fee_mat=ne_close_today,
        )
        needs_rebuild = sell_fee_candidate > 0
        if not is_mixed_t:
            needs_rebuild &= rebalance_modes_arr[ne_idx] != "each_period"
        if np.any(needs_rebuild):
            for _ in range(_TARGET_REBUILD_MAX_ITERATIONS):
                wealth_after_sell_fee = wealth_before_trade.copy()
                wealth_after_sell_fee[ne_idx] = np.maximum(0.0, ne_wb - sell_fee_candidate)
                next_target_amounts = _build_targets_for_wealth(
                    wealth_after_sell_fee,
                    close_fee_already_paid=True,
                )
                next_ne_target = next_target_amounts[ne_idx]
                if np.allclose(next_ne_target, ne_target, rtol=1e-12, atol=1e-12):
                    target_amounts = next_target_amounts
                    ne_target = next_ne_target
                    break
                target_amounts = next_target_amounts
                ne_target = next_ne_target
                sell, sell_fee_candidate = _compute_sell_fee_per_group(
                    ne_prev, ne_target, ne_close_fee,
                    close_today_fee_mat=ne_close_today,
                )

        if executable_capacity_t is not None:
            target_amounts[ne_idx] = apply_liquidity_execution(
                prev_end_amounts[ne_idx],
                target_amounts[ne_idx],
                ne_wb,
                executable_capacity_t[ne_idx],
                ne_open_fee,
                ne_close_today if ne_close_today is not None else ne_close_fee,
            )
            ne_target = target_amounts[ne_idx]
            sell, sell_fee_candidate = _compute_sell_fee_per_group(
                ne_prev, ne_target, ne_close_fee,
                close_today_fee_mat=ne_close_today,
            )

        # Step 2: final sell fee (per-group fee vectors)
        sell_fee = sell_fee_candidate
        sell_fee_ratio = np.divide(
            sell_fee, ne_wb,
            out=np.zeros_like(sell_fee, dtype=float),
            where=ne_wb > 0,
        )

        # Step 3: buy costs (per-group fee vectors)
        buy, buy_fee, trade_notional_ratio = _compute_buy_costs_per_group(
            ne_target, ne_prev, ne_open_fee, ne_wb,
        )
        buy_fee_ratio = np.divide(
            buy_fee, ne_wb,
            out=np.zeros_like(buy_fee, dtype=float),
            where=ne_wb > 0,
        )

        # Per-product fee contrib
        product_close_mat = ne_close_today if ne_close_today is not None else ne_close_fee
        product_fee = buy * ne_open_fee + sell * product_close_mat
        product_fee_contrib = np.where(
            ne_wb[:, np.newaxis] > 0,
            product_fee / ne_wb[:, np.newaxis],
            0.0,
        )

        # Gross & net returns
        buy_open_fees = buy * ne_open_fee
        product_gross_contrib, gross = compute_group_gross_returns(
            ne_target, ne_wb, ne_ret, buy_open_fees=buy_open_fees,
        )
        net_ret = compute_group_net_returns(gross, sell_fee_ratio, buy_fee_ratio, ne_wb, ne_target)

        wealth[ne_idx] = ne_wb * (1.0 + net_ret)
        gross_returns_np[t, ne_idx] = gross
        product_gross_contrib_np[t, ne_idx] = product_gross_contrib
        product_fee_contrib_np[t, ne_idx] = product_fee_contrib
        fee_costs_np[t, ne_idx] = sell_fee_ratio + buy_fee_ratio
        trade_notional_ratio_np[t, ne_idx] = trade_notional_ratio
        net_returns_np[t, ne_idx] = net_ret

        # Update prev_end_amounts
        new_prev = (ne_target - buy_open_fees) * (1.0 + ne_ret[np.newaxis, :])
        new_prev[ne_cc == 0] = 0.0
        prev_end_amounts[ne_idx] = new_prev

        # 记录本期持仓金额 (refs #100)
        target_amounts_np[t] = target_amounts
        prev_end_amounts_np[t] = prev_end_amounts

    return {
        'net_returns_np': net_returns_np,
        'gross_returns_np': gross_returns_np,
        'product_gross_contrib_np': product_gross_contrib_np,
        'product_fee_contrib_np': product_fee_contrib_np,
        'fee_costs_np': fee_costs_np,
        'trade_notional_ratio_np': trade_notional_ratio_np,
        'multi_session_triggered': multi_session_triggered,
        'target_amounts_np': target_amounts_np,
        'prev_end_amounts_np': prev_end_amounts_np,
    }


def compute_group_gross_returns(
    target_amounts: np.ndarray,
    wealth_before_trade: np.ndarray,
    product_returns: np.ndarray,
    buy_open_fees: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Return per-product gross contributions and per-group gross returns.

    When buy_open_fees is provided (buy_amount * open_fee), only net
    invested capital (target - buy_open_fees) earns the return; existing
    holdings incur no entry fee.
    """
    invested = np.asarray(target_amounts, dtype=float)
    if buy_open_fees is not None:
        invested = invested - np.asarray(buy_open_fees, dtype=float)
    product_contrib = (
        invested / wealth_before_trade[:, np.newaxis]
        * product_returns[np.newaxis, :]
    )
    return product_contrib, product_contrib.sum(axis=1)


def compute_group_net_returns(
    gross_returns: np.ndarray,
    sell_fee_ratio: np.ndarray,
    buy_fee_ratio: np.ndarray,
    wealth_before_trade: np.ndarray,
    target_amounts: np.ndarray,
) -> np.ndarray:
    """Apply sell + buy fees to gross returns.

    财富演化：
      available  = wealth - sell_fee                        (卖出后可用现金)
      invested   = target - buy_fee                         (实际投入)
      wealth_end = available - target + invested * (1+ret)  (现金归零 + 资产终值)
                 = wealth - sell_fee - buy_fee + invested * ret

      gross = invested / wealth * ret

      net = wealth_end / wealth - 1
          = -sell_fee_ratio - buy_fee_ratio + gross + invested/wealth - 1

      全仓时 invested ≈ wealth - sell_fee - buy_fee，即 invested/wealth ≈ 1 - sell_fee_ratio - buy_fee_ratio：
      net = -sell_fee_ratio - buy_fee_ratio + gross + (1 - sell_fee_ratio - buy_fee_ratio) - 1
          = gross - 2*sell_fee_ratio - 2*buy_fee_ratio  ← 这不对，说明近似有问题

      正确推导（不假设 invested/wealth）：
      net = (wealth - sell_fee - buy_fee + invested * ret) / wealth - 1
          = -sell_fee_ratio - buy_fee_ratio + invested/wealth * ret + invested/wealth - 1

      关键：invested/wealth * ret = gross（gross 的定义），所以：
      net = gross - sell_fee_ratio - buy_fee_ratio + (invested/wealth - 1)

      全仓：invested/wealth → 1，所以 net ≈ gross - sell_fee_ratio - buy_fee_ratio。
      非全仓：invested/wealth - 1 项不可忽略。为精确性，保留完整公式。

    gross_returns 已用 invested = target - buy_fee 计算。
    """
    return gross_returns - sell_fee_ratio - buy_fee_ratio


def compute_sell_fee(
    prev_end_amounts: np.ndarray,
    target_amounts: np.ndarray,
    close_fee_vec: np.ndarray,
    close_today_fee_vec: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Return per-group sell amounts and sell fee.

    Only charges close fee on the *exiting* portion of each position
    (prev > target), not on staying or entering positions.

    sell:     本期卖出的名义金额（每品种）
    sell_fee: 卖出费用总额（每group标量）

    close_fee_vec accepts (P,) or (n_groups, P). 1-D is broadcast to n_groups.
    """
    prev = np.asarray(prev_end_amounts, dtype=float)
    target = np.asarray(target_amounts, dtype=float)
    sell = np.clip(prev - target, 0.0, None)
    effective = np.asarray(
        close_today_fee_vec if close_today_fee_vec is not None else close_fee_vec,
        dtype=float,
    )
    if effective.ndim == 1:
        effective = effective[np.newaxis, :]  # (1, P) → broadcast
    sell_fee = (sell * effective).sum(axis=1)
    return sell, sell_fee


def _compute_sell_fee_per_group(
    prev_end_amounts: np.ndarray,
    target_amounts: np.ndarray,
    close_fee_mat: np.ndarray,
    close_today_fee_mat: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Per-group version of compute_sell_fee with (k, P) fee matrix instead of (P,) vector."""
    prev = np.asarray(prev_end_amounts, dtype=float)
    target = np.asarray(target_amounts, dtype=float)
    sell = np.clip(prev - target, 0.0, None)
    effective = np.asarray(close_today_fee_mat if close_today_fee_mat is not None else close_fee_mat, dtype=float)
    sell_fee = (sell * effective).sum(axis=1)
    return sell, sell_fee


def compute_buy_costs(
    target_amounts: np.ndarray,
    prev_end_amounts: np.ndarray,
    open_fee_vec: np.ndarray,
    wealth_before_trade: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return per-group buy amounts, buy fees, and trade notional ratio.

    buy:       本期买入的名义金额（每品种）
    buy_fee:   买入费用总额（每group标量）
    notional:  买卖总额 / 期初财富（衡量换手）

    open_fee_vec accepts (P,) or (n_groups, P). 1-D is broadcast to n_groups.
    """
    buy = np.clip(target_amounts - np.asarray(prev_end_amounts), 0.0, None)
    sell = np.clip(np.asarray(prev_end_amounts) - target_amounts, 0.0, None)
    open_fees = np.asarray(open_fee_vec, dtype=float)
    if open_fees.ndim == 1:
        open_fees = open_fees[np.newaxis, :]  # (1, P) → broadcast
    buy_fee = (buy * open_fees).sum(axis=1)
    trade_notional_ratio = np.divide(
        (buy + sell).sum(axis=1),
        wealth_before_trade,
        out=np.zeros_like(buy_fee, dtype=float),
        where=wealth_before_trade > 0,
    )
    return buy, buy_fee, trade_notional_ratio


def _compute_buy_costs_per_group(
    target_amounts: np.ndarray,
    prev_end_amounts: np.ndarray,
    open_fee_mat: np.ndarray,
    wealth_before_trade: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per-group version of compute_buy_costs with (k, P) fee matrix instead of (P,) vector."""
    buy = np.clip(target_amounts - np.asarray(prev_end_amounts), 0.0, None)
    sell = np.clip(np.asarray(prev_end_amounts) - target_amounts, 0.0, None)
    buy_fee = (buy * open_fee_mat).sum(axis=1)
    trade_notional_ratio = np.divide(
        (buy + sell).sum(axis=1),
        wealth_before_trade,
        out=np.zeros_like(buy_fee, dtype=float),
        where=wealth_before_trade > 0,
    )
    return buy, buy_fee, trade_notional_ratio


def simulate_derived_group(
    group_index: int,
    selected_idx: list[int],
    group_result: GroupRunResult,
    open_fee_vec: np.ndarray,
    close_fee_vec: np.ndarray,
    rebalance_mode: str = "buy_and_hold",
    use_closetoday: bool = False,
    close_today_fee_vec: np.ndarray | None = None,
) -> dict:
    """逐期模拟精选组（base group 的品种子集），返回 net/gross/fee/cumulative 序列。

    精选组的 wealth 演化路径独立于 base group：期初 wealth 初始为 1，
    每期根据子集 mask 重新计算 target_amounts、fee、net returns。

    底层复用 simulate_groups 引擎，构造 (T, 1, P) 的 membership matrix 后统一计算。

    参数：
        open_fee_vec、close_fee_vec、close_today_fee_vec 由外部调用方构建传入，
        **不得**从 group_result 的属性中获取（group_result 的 fee 数据属于
        上一次 base group 运行时的上下文，可能与当前请求的费率配置不一致）。
    """
    membership_np = getattr(group_result, 'membership_np', None)
    period_returns_np = getattr(group_result, 'period_returns_np', None)

    if membership_np is None or period_returns_np is None:
        raise ValueError('GroupRunResult 缺少 membership_np 或 period_returns_np')

    sel = np.asarray(selected_idx, dtype=int)
    P = len(sel)

    # 裁剪到子集品种，构造 (T, 1, P) membership
    mask_1g = membership_np[:, group_index, :][:, sel].reshape(
        membership_np.shape[0], 1, P
    )  # (T, 1, P)
    returns = period_returns_np[:, sel]  # (T, P)
    open_fv = open_fee_vec[sel] if open_fee_vec is not None else np.zeros(P)
    # 根据 use_closetoday 选择平今或平昨
    if use_closetoday and close_today_fee_vec is not None:
        close_fv = close_today_fee_vec[sel]
        # close_today_fee_vec passed as both close_fee_vec and close_today_fee_vec
        effective_close_today = close_fv
    else:
        close_fv = close_fee_vec[sel] if close_fee_vec is not None else np.zeros(P)
        effective_close_today = None

    sim_result = simulate_groups(
        membership_np=mask_1g,
        returns_np=returns,
        open_fee_mat=open_fv.reshape(1, P),
        close_fee_mat=close_fv.reshape(1, P),
        close_today_fee_mat=effective_close_today.reshape(1, P) if effective_close_today is not None else None,
        rebalance_mode=rebalance_mode,
    )

    # Flatten (T, 1) → (T,)
    net_returns_arr = sim_result['net_returns_np'][:, 0]
    gross_returns_arr = sim_result['gross_returns_np'][:, 0]
    fee_costs_arr = sim_result['fee_costs_np'][:, 0]
    notional_ratio_arr = sim_result['trade_notional_ratio_np'][:, 0]
    cumulative = np.cumprod(1.0 + net_returns_arr)

    return {
        'net_returns': net_returns_arr,
        'gross_returns': gross_returns_arr,
        'fee_costs': fee_costs_arr,
        'notional_ratios': notional_ratio_arr,
        'cumulative': cumulative,
    }


def simulate_derived_groups_batch(
    group_index: int,
    derivations: list[dict],
    group_result: GroupRunResult,
    open_fee_vec: np.ndarray,
    close_fee_vec: np.ndarray,
    rebalance_mode: str = "buy_and_hold",
    use_closetoday: bool = False,
    close_today_fee_vec: np.ndarray | None = None,
) -> list[dict]:
    """一次 simulate_groups 调用，批量计算同一基础组的多个派生组。

    所有派生组必须共享同一个 group_index（基础组索引）。
    每个派生组的品种子集可能不同；取所有 selected_idx 的并集作为
    P_all，构造 (T, N_derived, P_all) membership 后一次传入 simulate_groups。

    derivations: [{'selected_idx': [...], 'name': '...'}, ...]
    返回: [{'net_returns': ..., 'gross_returns': ..., ...}, ...] (顺序与 derivations 相同)
    """
    membership_np = getattr(group_result, 'membership_np', None)
    period_returns_np = getattr(group_result, 'period_returns_np', None)

    if membership_np is None or period_returns_np is None:
        raise ValueError('GroupRunResult 缺少 membership_np 或 period_returns_np')

    if not derivations:
        return []

    # 取所有派生组 selected_idx 的并集
    all_idx_sets = [set(np.asarray(d['selected_idx'], dtype=int)) for d in derivations]
    union_idx = sorted(set().union(*all_idx_sets))
    union_arr = np.array(union_idx, dtype=int)
    P_all = len(union_arr)

    # 映射：原索引 → 并集中的位置
    idx_to_pos = {idx: pos for pos, idx in enumerate(union_arr)}

    # 构造 (T, N_derived, P_all) membership
    base_membership = membership_np[:, group_index, :]  # (T, P_orig)
    T = base_membership.shape[0]
    N = len(derivations)
    mask_batch = np.zeros((T, N, P_all), dtype=bool)

    for di, d in enumerate(derivations):
        sel = np.asarray(d['selected_idx'], dtype=int)
        pos = [idx_to_pos[i] for i in sel]
        mask_batch[:, di, pos] = base_membership[:, sel]

    returns = period_returns_np[:, union_arr]  # (T, P_all)
    open_fv = open_fee_vec[union_arr] if open_fee_vec is not None else np.zeros(P_all)

    if use_closetoday and close_today_fee_vec is not None:
        close_fv = close_today_fee_vec[union_arr]
        effective_close_today = close_fv
    else:
        close_fv = close_fee_vec[union_arr] if close_fee_vec is not None else np.zeros(P_all)
        effective_close_today = None

    # 构造 per-derivation fee 矩阵 (N, P_all)
    # 每个 derivation 可能有独立的 fee_override
    open_fee_mat = np.tile(open_fv, (N, 1))
    close_fee_mat = np.tile(close_fv, (N, 1))
    ct_fee_mat = np.tile(effective_close_today, (N, 1)) if effective_close_today is not None else None

    for di, d in enumerate(derivations):
        feo = d.get('fee_override')
        if feo and isinstance(feo, dict):
            if feo.get('open') is not None:
                open_fee_mat[di, :] = float(feo['open'])
            if feo.get('close') is not None:
                close_fee_mat[di, :] = float(feo['close'])
            if ct_fee_mat is not None and feo.get('close_today') is not None:
                ct_fee_mat[di, :] = float(feo['close_today'])

    sim_result = simulate_groups(
        membership_np=mask_batch,
        returns_np=returns,
        open_fee_mat=open_fee_mat,
        close_fee_mat=close_fee_mat,
        close_today_fee_mat=ct_fee_mat,
        rebalance_mode=rebalance_mode,
    )

    # 拆回每个派生组的结果
    results = []
    for di in range(N):
        net_r = sim_result['net_returns_np'][:, di]
        results.append({
            'net_returns': net_r,
            'gross_returns': sim_result['gross_returns_np'][:, di],
            'fee_costs': sim_result['fee_costs_np'][:, di],
            'notional_ratios': sim_result['trade_notional_ratio_np'][:, di],
            'cumulative': np.cumprod(1.0 + net_r),
        })

    return results


def test_by_group_single_factor(
    tester: Any,
    factor: Factor,
    returns_col: FactorNextPeriodReturns,
    n_groups: int,
    n_groups_name: Dict[int, str],
    time_range: Optional[Tuple],
    plot_remark_str: Optional[str],
    plot_flag: bool,
    save_plot: bool,
    plot_show: bool,
    plot_n_group_list: Optional[List[int]],
    sift_volume_ratio: Optional[float] = None,
    fee: float = 0.0,
    fee_map: dict = {},
    use_closetoday: bool = False,
    rebalance_mode: str = "buy_and_hold",
    derived_groups: Optional[List[dict]] = None,
    group_fee_maps: Optional[dict[int, dict]] = None,
    group_variants: Optional[dict[int, list[dict]]] = None,
) -> Tuple[Any, Any, pd.DataFrame, np.ndarray, list]:
    """Single-factor group test core logic.

    group_fee_maps: dict[group_index, variety_fee_map]
        每个 group 独立的品种费率覆盖。variety_fee_map 结构与 fee_map 相同：
        {variety_code: {open: float, close: float, close_today: float, ...}}。
        只传被修改的单元格即可，未覆盖的品种/字段回退到全局 fee_map。

    group_variants: dict[group_index, list[dict]]
        混合费率变体。每个 key 对应一个 group，value 是 variant 列表。
        variant dict: {name: str, fee_map: dict | None}。
        fee_map 覆盖该 variant 下所有品种的费率（同名 key 替换），
        或 None 表示继承 group 的费率（即该 group 的 open_fee_mat[g]）。
        生成 N×M 映射矩阵，M = sum(len(variants)) for all groups，
        每个 variant 独立计算 wealth、return 等指标。

    rebalance_mode:
      - "each_period":   每期等权再平衡 — 所有组成员每期重新平分资金
      - "buy_and_hold":  组内持仓不动 — 只在产品进出组时才买卖（默认）
      - "recycle":       退出资金优先补新仓 — 留存仓位不动，退出资金先给新成员

    多时段品种自动检测：
      当 table_np 中出现某些时刻部分品种有信号、部分品种无信号（isnan_fac 混合）时，
      自动启用"多时段品种策略"，此时 rebalance_mode 参数被忽略：
      - 信号缺失品种不被踢出组，其持仓金额保持不变
      - 进出分组只在有信号的组内进行
      - 某组只有入没有出 → 该组当期冻结，不交易
    """
    start_date = pd.to_datetime(time_range[0]) if time_range is not None else tester.start_date
    end_date = pd.to_datetime(time_range[1]) if time_range is not None else tester.end_date

    r = tester._get_result(factor) if hasattr(tester, '_get_result') else None
    if r is None or r.returns.empty:
        raise ValueError(f"{factor.alias}: returns 未计算，请先运行 IC 测试")
    raw_returns = r.returns
    try:
        returns_for_group = align_table_for_group(factor, raw_returns)
    except Exception as e:
        raise ValueError(
            f"{factor.alias}: align_table_for_group 失败 — "
            f"returns shape={raw_returns.shape}, "
            f"index names={list(raw_returns.index.names) if hasattr(raw_returns.index, 'names') else 'N/A'}, "
            f"error: {e}"
        ) from e
    assert not returns_for_group.empty

    table_src: pd.DataFrame = cast(pd.DataFrame, get_factor_table_for_group(tester, factor))
    returns_src: pd.DataFrame = cast(pd.DataFrame, returns_for_group.copy(deep=False))
    table_src.index = _extract_signal_index(table_src.index)
    returns_src.index = _extract_signal_index(returns_src.index)
    if start_date is not None:
        _sd = _align_ts_to_index(start_date, table_src.index)
        table_src = cast(pd.DataFrame, table_src[table_src.index >= _sd])
        _sd = _align_ts_to_index(start_date, returns_src.index)
        returns_src = cast(pd.DataFrame, returns_src[returns_src.index >= _sd])
    if end_date is not None:
        _ed = _align_ts_to_index(end_date, table_src.index)
        table_src = cast(pd.DataFrame, table_src[table_src.index <= _ed])
        _ed = _align_ts_to_index(end_date, returns_src.index)
        returns_src = cast(pd.DataFrame, returns_src[returns_src.index <= _ed])

    common_index = table_src.index.intersection(returns_src.index)
    if len(common_index) == 0:
        def _idx_span(idx: pd.Index) -> str:
            if len(idx) == 0:
                return "empty"
            return f"{idx[0]} -> {idx[-1]} ({len(idx)} rows)"

        raise ValueError(
            f"{factor.alias}: 因子表和收益表没有共同时间索引；"
            f"factor={_idx_span(table_src.index)}, returns={_idx_span(returns_src.index)}"
        )
    table_src = table_src.loc[common_index]
    returns_src = returns_src.loc[common_index]

    all_cols = list(table_src.columns)
    ret_cols = list(returns_src.columns)
    valid_cols = list(set((valid := table_src.isna().all(axis=0))[~valid].index).intersection(set(ret_cols)))
    if not valid_cols:
        raise ValueError(
            f"{factor.alias}: 因子表和收益表没有共同品种列；"
            f"factor_cols={len(all_cols)}, returns_cols={len(ret_cols)}"
        )

    table_np = table_src[valid_cols].to_numpy(dtype=float)
    returns_np = returns_src[valid_cols].to_numpy(dtype=float)

    # ── data_present_mask（原始 bar 是否存在）──
    # 重要：不要用因子信号 NaN 来判断“是否有数据/是否可交易”：
    # - signal NaN 可能是用户刻意过滤 universe
    # - union 对齐也会引入插入行 NaN
    #
    # 使用 FactorRunResult.data_present_mask（由 Factor.evaluate 在预加载/对齐时生成）。
    # 必须可用，不可用时抛异常。
    present_src: Optional[pd.DataFrame] = None
    if r is not None and hasattr(r, "data_present_mask"):
        try:
            _pm = getattr(r, "data_present_mask")
            if isinstance(_pm, pd.DataFrame) and not _pm.empty:
                present_src = _pm.copy(deep=False)
        except Exception:
            present_src = None

    # ── 首尾全 NaN 行截断 ──
    # 数据首尾可能存在所有品种均为 NaN 的行（数据尚未开始或已结束），截断之
    _all_nan = np.all(np.isnan(table_np), axis=1)  # (T,) — 整行全 NaN
    _first_valid = int(np.argmin(_all_nan))  # 第一个非全NaN行（argmin找到第一个False=0）
    _last_valid = int(len(_all_nan) - 1 - np.argmin(_all_nan[::-1]))  # 最后一个非全NaN行

    if _all_nan.all():
        raise ValueError(f"{factor.alias}: 因子值序列全部为 NaN，无法进行分组测试。")

    trim_start: int = 0
    trim_end: int = len(_all_nan)
    # 截断首尾全 NaN 行
    if _first_valid > 0 or _last_valid < len(_all_nan) - 1:
        trim_start = _first_valid
        trim_end = _last_valid + 1
        table_np = table_np[trim_start:trim_end]
        returns_np = returns_np[trim_start:trim_end]
        table_src = table_src.iloc[trim_start:trim_end]
        returns_src = returns_src.iloc[trim_start:trim_end]
        print(f"[INFO] {factor.alias}: 截断首尾全 NaN 行 {trim_start} 行首 + {len(_all_nan) - trim_end} 行尾")

    # ── 中间全 NaN 行检测 ──
    # 截断后，中间不应再出现整行全 NaN
    _all_nan_mid = np.all(np.isnan(table_np), axis=1)
    if _all_nan_mid.any():
        bad_indices = [str(table_src.index[i]) for i in np.where(_all_nan_mid)[0]]
        raise ValueError(
            f"{factor.alias}: 因子值序列在以下 {len(bad_indices)} 个时点全部品种为 NaN，"
            f"非首尾全空行，可能是数据异常：{bad_indices[:5]}{'...' if len(bad_indices) > 5 else ''}"
        )

    index_list = list(table_src.index)
    T = len(index_list)

    n_names = {i: n_groups_name.get(i, "group_" + str(i)) for i in range(n_groups)}

    P = len(valid_cols)
    membership_np = np.zeros((T, n_groups, P), dtype=bool)
    current_members = np.zeros((n_groups, P), dtype=bool)

    # ── 多时段品种检测（基于 data_present_mask，而不是 signal NaN） ──
    if present_src is not None:
        # 对齐索引层级（与 table_src/returns_src 同样抽取 signal index）
        present_src.index = _extract_signal_index(present_src.index)
        # 与 table/returns 同样的起止截断
        if start_date is not None:
            _sd = _align_ts_to_index(start_date, present_src.index)
            present_src = cast(pd.DataFrame, present_src[present_src.index >= _sd])
        if end_date is not None:
            _ed = _align_ts_to_index(end_date, present_src.index)
            present_src = cast(pd.DataFrame, present_src[present_src.index <= _ed])
        # 与 table/returns 取共同索引与列
        present_src = present_src.loc[common_index, valid_cols]
        # 跟随首尾截断（与 table_np/returns_np 一致）
        if _first_valid > 0 or _last_valid < len(_all_nan) - 1:
            present_src = present_src.iloc[trim_start:trim_end]
        present_np = present_src.to_numpy(dtype=bool)
    else:
        raise ValueError(f"{factor.alias}: data_present_mask 不可用，无法进行分组测试。")

    # 排除“首部未上市/未有数据”的影响：对每列，把第一个 True 之前的 False 视为 True
    # （这些 False 不应触发多时段策略）
    col_has_any_present = np.asarray(present_np.any(axis=0), dtype=bool)
    # 对于从头到尾都没有数据的列（col_has_any_present=False），视为"始终不存在"，
    # 强制设 True 以避免触发多时段策略（这些品种直接跳过，不在 valid_cols 中参与交易）
    first_present = np.argmax(present_np, axis=0)  # 全 False 列会得到 0，但会被 col_has_any_present 屏蔽
    row_idx = np.arange(T, dtype=int)[:, np.newaxis]
    head_missing = (row_idx < first_present[np.newaxis, :]) & col_has_any_present[np.newaxis, :]
    present_filled = np.where(head_missing, True, present_np)
    # 全 False 列：视为始终不存在，强制填 True（这些品种不会在 valid_cols 中参与交易）
    present_filled[:, ~col_has_any_present] = True

    _mixed_mask = np.any(~present_filled, axis=1) & (~np.all(~present_filled, axis=1))
    multi_session_active = bool(_mixed_mask.any())
    if multi_session_active:
        _after_head_missing = (~present_np) & (~head_missing)
        _missing_cols = np.where(np.any(_after_head_missing, axis=0))[0]
        _missing_names = [str(valid_cols[i]) for i in _missing_cols]
        print(
            f"[INFO] {factor.alias}: 检测到 {int(_mixed_mask.sum())}/{T} 期存在部分品种无原始数据 "
            f"（{len(_missing_names)} 个品种存在缺失：{', '.join(_missing_names[:5])}"
            f"{'...' if len(_missing_names) > 5 else ''}），"
            f"自动启用多时段品种策略，忽略 rebalance_mode='{rebalance_mode}'。"
        )

    for t in tqdm(range(T), desc="Testing by group for factor " + factor.alias):
        row = table_np[t]
        ret_row = returns_np[t]

        isnan_ret = np.isnan(ret_row)
        isnan_fac = np.isnan(row)
        isbad_ret = (ret_row <= -1.0) | np.isinf(ret_row)
        if isbad_ret.any():
            bad_products = [valid_cols[i] for i in np.where(isbad_ret)[0]]
            bad_rets = [float(ret_row[i]) for i in np.where(isbad_ret)[0]]
            print(
                f"[WARN] t={t} ({index_list[t]}): 品种收益异常（≤-1 或 inf），将从分配中剔除: "
                + ", ".join(f"{p}={r:.4f}" for p, r in zip(bad_products, bad_rets))
            )

        if t == 0:
            carry_members = np.zeros((n_groups, P), dtype=bool)
        elif multi_session_active:
            # 多时段策略：基于“无原始数据”的品种保护逻辑
            # - present=False：该品种本期无 bar → 保留在原组，不参与当期再分配
            # - present=True：该品种本期有数据 → 允许正常进出组（由 available_mask 决定是否加入）
            has_data_t = present_np[t]  # (P,)
            carry_members = current_members & (~has_data_t[np.newaxis, :]) & (~isbad_ret[np.newaxis, :])
        else:
            carry_members = current_members & isnan_ret[np.newaxis, :] & (~isbad_ret[np.newaxis, :])

        prev_count = current_members.sum(axis=1)
        carry_count = carry_members.sum(axis=1)
        active_mask = (carry_count < prev_count) | (prev_count == 0)
        active_groups = np.where(active_mask)[0]

        current_members = carry_members.copy()

        held_mask = carry_members.any(axis=0)
        available_mask = (~isnan_fac) & (~held_mask) & (~isbad_ret)
        available_idx = np.where(available_mask)[0]

        if len(available_idx) > 0 and len(active_groups) > 0:
            new_idx = available_idx[np.argsort(-row[available_idx])]
            bucket_idx = np.floor(
                np.linspace(0, len(active_groups), len(new_idx), endpoint=False)
            ).astype(int)
            current_members[np.ix_(active_groups, new_idx)] = (
                np.arange(len(active_groups))[:, np.newaxis] == bucket_idx[np.newaxis, :]
            )

        membership_np[t] = current_members

    bad_ret_mask = np.isnan(returns_np) | np.isinf(returns_np) | (returns_np <= -1.0)
    returns_filled = np.where(bad_ret_mask, 0.0, returns_np)

    liquidity_capacity_np: np.ndarray | None = None

    # ── 派生组（精选组）：拼入 membership_np 作为额外组，统一计算 ──
    derived_defs = derived_groups or []
    derived_info: list[dict] = []  # [{base_group, name, product_names, id, ...}]

    from tools.products.product_utils import product_display_name

    if derived_defs:
        display_names = [product_display_name(product)['name'] for product in valid_cols]
        derived_slices: list[np.ndarray] = []
        for dd in derived_defs:
            if not isinstance(dd, dict):
                continue
            base_group = int(dd.get('baseGroup', dd.get('base_group', 0)))
            if base_group < 0 or base_group >= n_groups:
                continue
            product_names = dd.get('productNames', dd.get('product_names', []))
            if not product_names:
                continue
            selected = {str(n) for n in product_names}
            sel_idx = [idx for idx, dn in enumerate(display_names) if dn in selected]
            if not sel_idx:
                continue
            sel = np.asarray(sel_idx, dtype=int)
            display_name = dd.get('key') or dd.get('shortAlias') or dd.get('name') or f'第{base_group + 1}组精选'

            # 从 base_group 的每期 membership 中切出选中品种 → (T, 1, P)
            # mask_1g 需要是 (T, 1, P) 形状（P=全部品种数），只有选中品种位置有值
            mask_1g = np.zeros((T, 1, P), dtype=bool)
            mask_1g[:, 0, sel] = membership_np[:, base_group, :][:, sel]
            derived_slices.append(mask_1g)
            derived_info.append({
                'base_group': base_group,
                'key': display_name,
                'name': display_name,
                'id': dd.get('id'),
                'product_names': [display_names[idx] for idx in sel_idx],
                'fee_mode': dd.get('fee_mode', dd.get('feeMode')),
                'fee_rate': dd.get('fee_rate', dd.get('feeRate')),
                'fee_map': dd.get('fee_map', dd.get('feeMap')),
                'use_close_today': dd.get('use_close_today', dd.get('useCloseToday')),
                'rebalance_mode': dd.get('rebalance_mode', dd.get('rebalanceMode')),
                'liquidity_mode': dd.get('liquidity_mode', dd.get('liquidityMode')),
                'liquidity_percent': dd.get('liquidity_percent', dd.get('liquidityPercent')),
            })

        if derived_slices:
            derived_membership = np.concatenate(derived_slices, axis=1)  # (T, n_derived, P)
            membership_np = np.concatenate([membership_np, derived_membership], axis=1)

    n_derived = len(derived_info)
    n_base = n_groups
    n_groups = membership_np.shape[1]  # 现在包含 base + derived

    # 扩展组名映射（派生组用 derived_info 中的 name）
    for d_idx, di in enumerate(derived_info):
        n_names[n_base + d_idx] = di['name']

    def _liquidity_mode_from_spec(spec: dict | None) -> str:
        if not isinstance(spec, dict):
            return "infinite"
        mode = str(spec.get("liquidity_mode") or spec.get("liquidityMode") or "infinite").strip()
        return mode if mode == "percent" else "infinite"

    def _liquidity_percent_from_spec(spec: dict | None) -> float:
        if not isinstance(spec, dict):
            return 100.0
        raw = spec.get("liquidity_percent", spec.get("liquidityPercent", 100.0))
        try:
            return min(100.0, max(0.0, float(raw)))
        except (TypeError, ValueError):
            return 100.0

    liquidity_modes_list = ["infinite"] * n_groups
    liquidity_percents_list = [100.0] * n_groups
    for d_idx, di in enumerate(derived_info):
        g = n_base + d_idx
        liquidity_modes_list[g] = _liquidity_mode_from_spec(di)
        liquidity_percents_list[g] = _liquidity_percent_from_spec(di)

    def _variety(col) -> str:
        nm = getattr(col, "name", str(col))
        return nm.split(".")[0].upper()

    half_fee = float(fee) / 2.0
    open_fee_vec = np.array([
        float((fee_map.get(_variety(c), {}) or {}).get("open", half_fee))
        for c in valid_cols
    ], dtype=float)
    close_fee_vec = np.array([
        float((fee_map.get(_variety(c), {}) or {}).get("close", half_fee))
        for c in valid_cols
    ], dtype=float)
    close_today_fee_vec = np.array([
        float((fee_map.get(_variety(c), {}) or {}).get("close_today", close_fee_vec[i]))
        for i, c in enumerate(valid_cols)
    ], dtype=float)
    close_yesterday_fee_vec = np.array([
        float((fee_map.get(_variety(c), {}) or {}).get("close_yesterday", close_fee_vec[i]))
        for i, c in enumerate(valid_cols)
    ], dtype=float)

    # ── 构造 per-group fee 矩阵 (n_groups, P) ──
    # group_fee_maps: {group_index: {variety_code: {open, close, close_today, ...}}}
    # 每个 group 的独立品种费率覆盖，只传被修改的单元格。
    group_maps = group_fee_maps or {}

    def _resolve_group_fee(g: int, fee_type: str, fallback_vec: np.ndarray) -> np.ndarray:
        """Resolve per-product fee for group g.
        优先级：group_fee_maps[g] > derived_groups[d_i].fee_override > 全局 fallback_vec
        """
        row = fallback_vec.copy()
        # 1. group_fee_maps: per-product override for this group
        gmap = group_maps.get(g)
        if gmap and isinstance(gmap, dict):
            for i, col in enumerate(valid_cols):
                vname = _variety(col).lower()
                prod_fee = gmap.get(vname)
                if prod_fee and isinstance(prod_fee, dict) and fee_type in prod_fee and prod_fee[fee_type] is not None:
                    row[i] = float(prod_fee[fee_type])
        # 2. Derived groups: uniform fee_override covers all products
        if g >= n_base and derived_groups:
            d_i = g - n_base
            if d_i < len(derived_groups):
                dd = derived_groups[d_i]
                if isinstance(dd, dict):
                    fo = dd.get('fee_override') or {}
                    if fee_type in fo and fo[fee_type] is not None:
                        row[:] = float(fo[fee_type])
        return row

    open_fee_mat = np.tile(open_fee_vec, (n_groups, 1))       # (n_groups, P) — default
    close_fee_mat = np.tile(close_fee_vec, (n_groups, 1))
    close_today_fee_mat = np.tile(close_today_fee_vec, (n_groups, 1))

    for g in range(n_groups):
        open_fee_mat[g, :] = _resolve_group_fee(g, 'open', open_fee_vec)
        close_fee_mat[g, :] = _resolve_group_fee(g, 'close', close_fee_vec)
        close_today_fee_mat[g, :] = _resolve_group_fee(g, 'close_today', close_today_fee_vec)

    # close_fee_mat 始终=平昨，close_today_fee_mat 始终=平今
    effective_close_fee_mat = close_today_fee_mat if use_closetoday else None

    def _apply_fee_strategy(row_open: np.ndarray, row_close: np.ndarray, row_ct: np.ndarray, spec: dict | None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Apply one group/variant fee strategy to fee rows.

        fee_mode:
          - none: zero fees for this strategy
          - uniform: fee_rate is the round-trip percent value used by the UI; split half/half
          - per_product/custom: start from the global per-product fee table, then sparse override by fee_map
          - missing: inherit the already-resolved group row
        """
        if not isinstance(spec, dict):
            return row_open, row_close, row_ct
        mode = str(spec.get('fee_mode') or spec.get('feeMode') or '').strip()
        if mode == 'none':
            return np.zeros_like(row_open), np.zeros_like(row_close), np.zeros_like(row_ct)
        if mode == 'uniform':
            raw_rate = spec.get('fee_rate', spec.get('feeRate'))
            half = float(raw_rate or 0.0) / 100.0 / 2.0
            return (
                np.full_like(row_open, half),
                np.full_like(row_close, half),
                np.full_like(row_ct, half),
            )
        if mode in {'per_product', 'custom'}:
            row_open = open_fee_vec.copy()
            row_close = close_fee_vec.copy()
            row_ct = close_today_fee_vec.copy()
        vfm = spec.get('fee_map') or spec.get('feeMap') or {}
        if vfm and isinstance(vfm, dict):
            for ci, col in enumerate(valid_cols):
                vname = _variety(col).lower()
                pf = vfm.get(vname) or vfm.get(vname.upper())
                if pf and isinstance(pf, dict):
                    if 'open' in pf and pf['open'] is not None:
                        row_open[ci] = float(pf['open'])
                    if 'close' in pf and pf['close'] is not None:
                        row_close[ci] = float(pf['close'])
                    if 'close_today' in pf and pf['close_today'] is not None:
                        row_ct[ci] = float(pf['close_today'])
        return row_open, row_close, row_ct

    def _variant_uses_close_today(spec: dict | None) -> bool:
        if isinstance(spec, dict):
            value = spec.get('use_close_today', spec.get('useCloseToday'))
            if value is not None:
                return bool(value)
        return bool(use_closetoday)

    # ── 混合费率/派生变体：构建 group→variant 映射，扩展 fee 矩阵和元信息 ──
    _variants = dict(group_variants or {})
    if _variants:
        for d_i, di in enumerate(derived_info):
            derived_group_idx = n_base + d_i
            if derived_group_idx not in _variants:
                _variants[derived_group_idx] = [{
                    'name': di.get('name', f'第{di.get("base_group", 0) + 1}组精选'),
                    'fee_mode': di.get('fee_mode'),
                    'fee_rate': di.get('fee_rate'),
                    'fee_map': di.get('fee_map'),
                    'use_close_today': di.get('use_close_today'),
                    'rebalance_mode': di.get('rebalance_mode'),
                    'liquidity_mode': di.get('liquidity_mode'),
                    'liquidity_percent': di.get('liquidity_percent'),
                }]
    if _variants:
        M_total = sum(len(_variants.get(g, [])) for g in range(n_groups))
        if M_total <= 0:
            raise ValueError("group_variants must contain at least one variant")

        variant_to_group = np.full(M_total, -1, dtype=int)
        _new_names = {}
        _new_derived_info: list[dict] = []
        _new_open_mat = np.zeros((M_total, P), dtype=float)
        _new_close_mat = np.zeros((M_total, P), dtype=float)
        _new_ct_mat = np.zeros((M_total, P), dtype=float)
        _variant_use_close_today = np.zeros(M_total, dtype=bool)
        vi = 0
        base_variant_count = 0
        variant_rebalance_modes: list[str] = []
        variant_liquidity_modes: list[str] = []
        variant_liquidity_percents: list[float] = []
        for g in range(n_groups):
            var_list = _variants.get(g, []) or []
            for vd in var_list:
                variant_to_group[vi] = g
                variant_name = vd.get('name', f"{n_names.get(g, f'group_{g}')}_var{vi}") if isinstance(vd, dict) else str(vd)
                spec = vd if isinstance(vd, dict) else {'name': variant_name}
                row_open = open_fee_mat[g].copy()
                row_close = close_fee_mat[g].copy()
                row_ct = close_today_fee_mat[g].copy()
                row_open, row_close, row_ct = _apply_fee_strategy(row_open, row_close, row_ct, spec)
                _variant_use_close_today[vi] = _variant_uses_close_today(spec)
                _new_names[vi] = n_names.get(g, f"group_{g}")
                if variant_name:
                    _new_names[vi] = str(variant_name)
                variant_rebalance_modes.append(str(spec.get('rebalance_mode') or spec.get('rebalanceMode') or rebalance_mode))
                variant_liquidity_modes.append(_liquidity_mode_from_spec(spec))
                variant_liquidity_percents.append(_liquidity_percent_from_spec(spec))
                _new_open_mat[vi] = row_open
                _new_close_mat[vi] = row_close
                _new_ct_mat[vi] = row_ct
                if g < n_base:
                    base_variant_count += 1
                else:
                    d_i = g - n_base
                    di = dict(derived_info[d_i]) if d_i < len(derived_info) else {}
                    di['name'] = _new_names[vi]
                    di['source_group'] = g
                    di['source_base_group'] = di.get('base_group')
                    _new_derived_info.append(di)
                vi += 1

        n_names = _new_names
        membership_np = membership_np[:, variant_to_group, :]
        open_fee_mat = _new_open_mat
        close_fee_mat = _new_close_mat
        close_today_fee_mat = _new_ct_mat
        effective_close_fee_mat = np.where(
            _variant_use_close_today[:, np.newaxis],
            close_today_fee_mat,
            close_fee_mat,
        )
        n_base = base_variant_count
        derived_info = _new_derived_info
        n_derived = len(derived_info)
        n_groups = M_total  # 后续代码中的 n_groups 现在指 M
    else:
        variant_rebalance_modes = []
        variant_liquidity_modes = liquidity_modes_list
        variant_liquidity_percents = liquidity_percents_list

    if any(str(mode) == "percent" for mode in variant_liquidity_modes):
        source_freq = cast(DataFreq, factor._source_freq if getattr(factor, "_source_freq", None) is not None else DataFreq.MIN1)
        liquidity_capacity_np = _build_normalized_liquidity_capacity(
            valid_cols,
            index_list,
            source_freq,
            start_date,
            end_date,
        )

    products_dict = {
        g: {index_list[t]: [valid_cols[i]
                             for i in np.where(membership_np[t, g])[0]]
            for t in range(T)}
        for g in range(n_groups)
    }

    member_counts = membership_np.sum(axis=2).astype(float)

    group_gross_returns_np = np.zeros((T, n_groups), dtype=float)
    group_product_gross_contrib_np = np.zeros((T, n_groups, P), dtype=float)
    group_product_fee_contrib_np = np.zeros((T, n_groups, P), dtype=float)
    fee_costs_np = np.zeros((T, n_groups), dtype=float)
    trade_notional_ratio_np = np.zeros((T, n_groups), dtype=float)
    group_returns_np = np.zeros((T, n_groups), dtype=float)

    _VALID_MODES = frozenset({"each_period", "buy_and_hold", "recycle"})
    if rebalance_mode not in _VALID_MODES:
        raise ValueError(f"rebalance_mode must be one of {sorted(_VALID_MODES)}, got {rebalance_mode!r}")

    # ── 逐期矩阵化收益计算（统一引擎：base + derived 一次跑完）──
    data_has_bar = present_np if multi_session_active else None
    sim_result = simulate_groups(
        membership_np=membership_np,
        returns_np=returns_filled,
        open_fee_mat=open_fee_mat,
        close_fee_mat=close_fee_mat,
        close_today_fee_mat=effective_close_fee_mat,
        data_has_bar=data_has_bar,
        rebalance_mode=rebalance_mode,
        rebalance_modes=variant_rebalance_modes if variant_rebalance_modes else None,
        liquidity_capacity_np=liquidity_capacity_np,
        liquidity_modes=variant_liquidity_modes if variant_liquidity_modes else None,
        liquidity_percents=variant_liquidity_percents if variant_liquidity_percents else None,
    )
    group_returns_np = sim_result['net_returns_np']
    group_gross_returns_np = sim_result['gross_returns_np']
    group_product_gross_contrib_np = sim_result['product_gross_contrib_np']
    group_product_fee_contrib_np = sim_result['product_fee_contrib_np']
    fee_costs_np = sim_result['fee_costs_np']
    trade_notional_ratio_np = sim_result['trade_notional_ratio_np']
    multi_session_triggered_count = sim_result['multi_session_triggered']

    if multi_session_active:
        print(f"[WARN] {factor.alias}: 多时段品种策略在 {multi_session_triggered_count}/{T} 期中触发。")

    returns_dict = {g: {index_list[t]: float(group_returns_np[t, g]) for t in range(T)} for g in range(n_groups)}

    bad = np.isnan(group_returns_np) | np.isinf(group_returns_np) | (group_returns_np <= -1.0)
    cum_rets_filled = np.where(bad, 0.0, group_returns_np)
    cumulative_returns_np = np.cumprod(1 + cum_rets_filled, axis=0)

    avg_turnover = np.zeros(n_groups, dtype=float)
    if T > 1:
        transition_counts = (member_counts[1:] + member_counts[:-1]) / 2.0
        turnover_valid = transition_counts > 0
        changed = np.logical_xor(membership_np[1:], membership_np[:-1]).sum(axis=2) / 2.0
        turnover_ratio = np.divide(
            changed,
            transition_counts,
            out=np.zeros_like(changed, dtype=float),
            where=turnover_valid,
        )
        turnover_observations = turnover_valid.sum(axis=0)
        avg_turnover = np.divide(
            turnover_ratio.sum(axis=0),
            turnover_observations,
            out=np.zeros(n_groups, dtype=float),
            where=turnover_observations > 0,
        )

    signal_times = pd.DatetimeIndex(index_list)
    mask_report = np.ones(T, dtype=bool)
    if start_date is not None:
        mask_report &= (signal_times >= _align_ts_to_index(start_date, signal_times))
    if end_date is not None:
        mask_report &= (signal_times <= _align_ts_to_index(end_date, signal_times))

    report_groups = {}
    annual_periods = infer_periods_per_year(index_list)
    for idx in range(n_groups):
        r = group_returns_np[mask_report, idx]

        def _metrics(arr: np.ndarray) -> dict:
            s = pd.Series(arr).dropna()
            cum = (1 + s).cumprod()
            n = len(s)
            total_ret = (cum.iloc[-1] - 1) * 100 if n > 0 else 0
            annual_ret = (cum.iloc[-1] ** (annual_periods / n) - 1) * 100 if n > 1 else 0
            vol = s.std() * np.sqrt(annual_periods) * 100
            sharpe = (s.mean() * annual_periods) / (s.std() * np.sqrt(annual_periods)) if s.std() != 0 else 0
            dd = ((cum.cummax() - cum) / cum.cummax()).max() * 100 if n > 0 else 0
            calmar = annual_ret / dd if dd != 0 else 0
            win_rate = (s > 0).sum() / n * 100 if n > 0 else 0
            return dict(total_ret=total_ret, annual_ret=annual_ret, vol=vol,
                        sharpe=sharpe, dd=dd, calmar=calmar, win_rate=win_rate,
                        mean_ret=s.mean() * 100, skew=s.skew(), kurt=s.kurtosis())

        m = _metrics(r)
        report_groups[idx] = pd.Series({
            "Total Return": m["total_ret"],
            "Annual Return": m["annual_ret"],
            "Volatility": m["vol"],
            "Sharpe Ratio": m["sharpe"],
            "Max Drawdown": m["dd"],
            "Calmar Ratio": m["calmar"],
            "Win Rate": m["win_rate"],
            "Mean Return": m["mean_ret"],
            "Skewness": m["skew"],
            "Kurtosis": m["kurt"],
            "Avg Turnover": avg_turnover[idx],
        })

    report_df = pd.DataFrame(report_groups).T.sort_index()
    r = tester._get_result(factor) if hasattr(tester, "_get_result") else None
    group_result = GroupRunResult(
        fee_costs_np=fee_costs_np,
        trade_notional_ratio_np=trade_notional_ratio_np,
        gross_returns_np=group_gross_returns_np,
        product_gross_contrib_np=group_product_gross_contrib_np,
        product_fee_contrib_np=group_product_fee_contrib_np,
        returns_np=group_returns_np,
        period_returns_np=returns_filled,
        membership_np=membership_np,
        products_by_group=products_dict,
        valid_cols=valid_cols,
        open_fee_vec=open_fee_vec,
        close_fee_vec=close_fee_vec,
        close_today_fee_vec=close_today_fee_vec,
        close_yesterday_fee_vec=close_yesterday_fee_vec,
        index_list=index_list,
        multi_session_active=multi_session_active,
        rebalance_mode=rebalance_mode,
        report_df=report_df.copy(),
        n_base=n_base,
        n_derived=n_derived,
        derived_info=derived_info,
        group_names=n_names,
        hold_amounts_np=sim_result.get('prev_end_amounts_np'),
    )
    if r is not None:
        r.group_result = group_result
    tester.last_group_factor = factor
    if not plot_flag or (plot_flag and plot_show):
        with pd.option_context("display.max_rows", None, "display.max_columns", None):
            print("Group Performance Summary:\n", report_df)

    if plot_flag:
        import matplotlib.pyplot as plt
        plt.figure(figsize=(12, 6))
        _start_date = start_date if start_date is not None else tester.start_date
        _end_date = end_date if end_date is not None else tester.end_date
        plot_mask = np.ones(T, dtype=bool)
        if _start_date is not None:
            plot_mask &= (signal_times >= _align_ts_to_index(_start_date, signal_times))
        if _end_date is not None:
            plot_mask &= (signal_times <= _align_ts_to_index(_end_date, signal_times))
        plot_index = [index_list[t] for t in range(T) if plot_mask[t]]
        dates = plot_index
        for idx in range(n_groups):
            if plot_n_group_list is not None and idx not in plot_n_group_list:
                continue
            rets = group_returns_np[plot_mask, idx]
            cumulative_returns = np.cumprod(1 + np.where(np.isnan(rets), 0.0, rets)) * 10000
            plt.plot([str(d.date()) for d in plot_index], cumulative_returns, label=n_names[idx])
        plt.xlabel("日期")
        plt.ylabel("平均收益")
        plt.title(f"平均收益: {factor.alias}" + (f" - {plot_remark_str}" if plot_remark_str else ""))
        plt.rcParams["font.sans-serif"] = ["Kaiti SC"]
        plt.legend()
        n_ticks = 10
        if dates:
            tick_indices = np.linspace(0, len(dates) - 1, min(n_ticks, len(dates)), dtype=int)
            ticks = [str(dates[i].date()) for i in tick_indices]
            plt.xticks(ticks=ticks, rotation=45)
        plt.tight_layout()
        if save_plot:
            factor_stem = factor.alias.split("|")[0]
            figs_path = os.path.join(factor_info_path, factor_stem, "figs")
            if not os.path.exists(figs_path):
                os.makedirs(figs_path)
            plt.savefig(os.path.join(figs_path, f"{factor.alias}_{start_date}_{end_date}.png"))
        if plot_show:
            plt.show()

    # NOTE: 不再将 returns_dict 写回 r.returns——returns_dict 是 {group_id: {ts: float}}
    # 的嵌套字典，会污染后续分组测试使用的 r.returns（IC测试的品种x时间矩阵）。
    return products_dict, returns_dict, report_df, cumulative_returns_np, index_list


def test_by_group(
    tester: Any,
    factors: Optional[Factor | List[Factor]] = None,
    returns_col: FactorNextPeriodReturns = FactorNextPeriodReturns.NEXT_OPEN_TO_OPEN_ADJUSTED,
    n_groups: int = 5,
    n_groups_name: Dict[int, str] = {},
    time_range: Optional[Tuple] = None,
    plot_remark_str: Optional[str] = None,
    plot_flag: bool = False,
    save_plot: bool = True,
    plot_show: bool = True,
    plot_n_group_list: Optional[List[int]] = None,
    sift_volume_ratio: Optional[float] = None,
    fee: float = 0.0,
    fee_map: dict = {},
    rebalance_mode: str = "buy_and_hold",
    **kwargs,
) -> Tuple[Any, Any, pd.DataFrame, np.ndarray, list]:
    """Run group test for one or more factors.

    rebalance_mode:
      - \"each_period\":   每期等权再平衡
      - \"buy_and_hold\":  组内持仓不动（默认）
      - \"recycle\":       退出资金优先补新仓
    """
    factors = [factors] if isinstance(factors, Factor) else (factors if factors is not None else tester.factors)
    assert isinstance(factors, list), f"factors must be a list, got {type(factors)}"

    if plot_flag and plot_n_group_list is not None:
        plot_n_group_list = [n_groups + n_group if n_group < 0 else n_group for n_group in plot_n_group_list] if plot_n_group_list else None

    products_out: Any = {}
    returns_out: Any = {}
    report_df: pd.DataFrame = pd.DataFrame()

    def _run(f: Factor) -> Tuple[Any, Any, pd.DataFrame, np.ndarray, list]:
        products, returns, report, cum_np, idx_list = test_by_group_single_factor(
            tester,
            f,
            returns_col=returns_col,
            n_groups=n_groups,
            n_groups_name=n_groups_name,
            time_range=time_range,
            plot_remark_str=plot_remark_str,
            plot_flag=plot_flag,
            save_plot=save_plot,
            plot_show=plot_show,
            plot_n_group_list=plot_n_group_list,
            sift_volume_ratio=sift_volume_ratio,
            fee=fee,
            fee_map=fee_map,
            use_closetoday=kwargs.pop('use_closetoday', False),
            rebalance_mode=rebalance_mode,
            derived_groups=kwargs.pop('derived_groups', None),
            group_fee_maps=kwargs.pop('group_fee_maps', None),
            group_variants=kwargs.pop('group_variants', None),
        )
        return products, returns, report, cum_np, idx_list

    cum_np_out: Optional[np.ndarray] = None
    idx_list_out: Optional[list] = None

    if len(factors) == 1:
        products_out, returns_out, report_df, cum_np_out, idx_list_out = _run(factors[0])
    else:
        max_workers = min(len(factors), 8)
        results: Dict[int, Any] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_idx = {executor.submit(_run, f): i for i, f in enumerate(factors)}
            for future in as_completed(future_to_idx):
                results[future_to_idx[future]] = future.result()
        last_idx = max(results.keys())
        products_out, returns_out, report_df, cum_np_out, idx_list_out = results[last_idx]

    assert cum_np_out is not None and idx_list_out is not None
    return products_out, returns_out, report_df, cum_np_out, idx_list_out
