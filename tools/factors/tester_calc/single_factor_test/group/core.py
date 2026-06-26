"""Group test core implementation."""
from __future__ import annotations

import os
import threading
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple, cast

import numpy as np
import pandas as pd
from tqdm import tqdm

from settings import factor_info_path
from tools.data.types import DataColumn
from tools.data.types.currency import CurrencyConversionContext, normalize_currency, require_product_currency_vector
from tools.data.types import DataFreq
from tools.data.types import DataIndex
from tools.data.types.currency_units import minor_units_to_major, major_floor_to_minor_units, major_to_minor_units
from tools.factors import Factor
from tools.factors.Parameters import FactorNextPeriodReturns
from tools.factors.tester_calc.NextReturns import NextReturns
from tools.factors.tester_calc.single_factor_test.group.result import GroupRunResult
from tools.products import lookup_contract_product


# ── 进度回调注册机制 ──

_group_progress_lock = threading.Lock()
_group_progress_callback: Callable[[str, str, dict], None] | None = None

# 并行 batch 上下文：每个线程设置自己的 product_coverage_batch_index / product_coverage_batch_total，
# _emit_progress 自动将其注入 extra，让前端能区分不同 batch 的进度。
_batch_context = threading.local()


def register_group_progress(callback: Callable[[str, str, dict], None]) -> None:
    """注册结构化进度回调。回调签名为 callback(phase: str, message: str, extra: dict)。

    phase 取值：
    - factor_eval — 计算因子值
    - returns_eval — 计算收益率
    - membership  — 计算分组隶属度
    - remap       — 产品重新映射
    - trade_data  — 加载交易数据（returns + prices + specs）
      sub_step 可选值：
        - start          — 开始加载
        - load_returns   — 加载收益数据
        - load_prices    — 加载价格数据
        - merge_products — 合并品种数据
        - settlement     — 处理结算数据
        - spec_bundle    — 计算交易规格
        - fill_returns   — 填充缺失收益
        - build_configs  — 构建分组配置
        - ready          — 交易数据就绪
    - simulate    — 交易模拟中
      sub_step 可选值：
        - slicing       — 结果切片
    - product_coverage_batch — product coverage batch 级进度
    - flat_membership — 展平隶属度
    - serialize   — 结果序列化
    - info        — 一般信息
    """
    global _group_progress_callback
    with _group_progress_lock:
        _group_progress_callback = callback


def unregister_group_progress() -> None:
    global _group_progress_callback
    with _group_progress_lock:
        _group_progress_callback = None


def set_batch_context(product_coverage_batch_index: int, product_coverage_batch_total: int, product_coverage_batch_label: str = "") -> None:
    """设置当前线程的 batch 上下文，_emit_progress 会自动附加到 extra。"""
    _batch_context.product_coverage_batch_index = product_coverage_batch_index
    _batch_context.product_coverage_batch_total = product_coverage_batch_total
    _batch_context.product_coverage_batch_label = product_coverage_batch_label


def clear_batch_context() -> None:
    """清除当前线程的 batch 上下文。"""
    _batch_context.product_coverage_batch_index = -1
    _batch_context.product_coverage_batch_total = 0
    _batch_context.product_coverage_batch_label = ""


def _emit_progress(phase: str, message: str, **extra) -> None:
    cb = None
    with _group_progress_lock:
        cb = _group_progress_callback
    bi = getattr(_batch_context, 'product_coverage_batch_index', -1)
    bt = getattr(_batch_context, 'product_coverage_batch_total', 0)
    if cb is not None:
        try:
            # 自动注入 batch 上下文
            if bi >= 0:
                extra.setdefault('product_coverage_batch_index', bi)
                extra.setdefault('product_coverage_batch_total', bt)
                bl = getattr(_batch_context, 'product_coverage_batch_label', '')
                if bl:
                    extra.setdefault('product_coverage_batch_label', bl)
            cb(phase, message, extra)
        except Exception as exc:
            from tools.testers.backtest.engines.cancellation import BacktestCancelled
            if isinstance(exc, BacktestCancelled):
                raise


_TARGET_REBUILD_MAX_ITERATIONS = 8
_EACH_PERIOD_TARGET_MAX_ITERATIONS = 16


def _end_of_trading_day_mask_for_column(index: pd.Index, values: np.ndarray) -> np.ndarray:
    """Return a mask for the last finite bar of each trading day for one column."""
    di = DataIndex(index)
    raw_index = di.raw
    if isinstance(raw_index, pd.MultiIndex):
        day_level = next(
            (
                i
                for i, name in enumerate(raw_index.names)
                if name and (
                    str(name).upper().endswith("DAY1")
                    or str(name).upper() in {"TRADING_DAY", "TRADE_DAY"}
                    or str(name).upper().endswith("_TRADING_DAY")
                )
            ),
            None,
        )
        if day_level is not None:
            day_values = pd.DatetimeIndex(raw_index.get_level_values(day_level))
        else:
            day_values = pd.DatetimeIndex(di.finest_index).normalize()
    else:
        day_values = pd.DatetimeIndex(di.finest_index).normalize()

    values_arr = np.asarray(values, dtype=float)
    finite = np.isfinite(values_arr)
    mask = np.zeros(len(values_arr), dtype=bool)
    if not finite.any():
        return mask

    finite_positions = np.flatnonzero(finite)
    finite_days = day_values[finite_positions]
    if len(finite_positions) == 1:
        mask[finite_positions[0]] = True
        return mask

    day_arr = finite_days.to_numpy()
    day_change = np.flatnonzero(day_arr[1:] != day_arr[:-1]) + 1
    boundaries = np.concatenate([day_change, np.array([len(finite_positions)], dtype=int)])
    for end in boundaries:
        mask[finite_positions[end - 1]] = True
    return mask


@dataclass(slots=True)
class GroupSharedInputs:
    start_date: Any
    end_date: Any
    price_col: DataColumn
    source_freq: DataFreq
    effective_return_freq: DataFreq
    table_src: pd.DataFrame
    returns_src: pd.DataFrame
    price_src: pd.DataFrame
    signal_valid_cols: list
    table_np: np.ndarray
    signal_returns_np: np.ndarray
    present_np: np.ndarray
    signal_update_mask: np.ndarray
    settlement_bar_mask: np.ndarray
    index_list: list
    T: int
    P: int
    multi_session_active: bool
    multi_session_missing_products: list[str]
    multi_session_missing_count: int


@dataclass(slots=True)
class GroupTradeSpecBundle:
    valid_cols: list
    open_ratio_mat: np.ndarray           # (T, P)
    open_fixed_mat: np.ndarray           # (T, P)
    close_ratio_mat: np.ndarray          # (T, P) — 平昨 (close_yesterday)
    close_fixed_mat: np.ndarray          # (T, P) — 平昨 (close_yesterday)
    closetoday_ratio_mat: np.ndarray    # (T, P)
    closetoday_fixed_mat: np.ndarray    # (T, P)
    use_closetoday_vec: np.ndarray       # (P,) — per-product bool: True=平今, False=平昨
    multiplier_mat: np.ndarray          # (T, P) — 别名 point_value, 数据源字段 multiplier
    min_tick_mat: np.ndarray             # (T, P)
    min_trade_quantity_mat: np.ndarray   # (T, P)
    long_margin_ratio_mat: np.ndarray    # (T, P)
    is_margin_traded_vec: np.ndarray     # (P,)
    variety_codes_lower: list[str]
    positions_by_variety_code_lower: dict[str, list[int]]
    rule_provenance: dict[str, dict[str, int]] | None = None


def slice_group_run_result(
    group_result: GroupRunResult,
    group_indices: list[int],
) -> GroupRunResult:
    """Slice a flat-group result by selected group-axis columns.

    This keeps execution artifacts on the same trade-product axis while remapping
    the selected groups onto a fresh local axis [0, K).
    """
    if not group_indices:
        raise ValueError("group_indices must not be empty")

    old_to_new = {old_idx: new_idx for new_idx, old_idx in enumerate(group_indices)}
    old_group_names = dict(getattr(group_result, "group_names", None) or {})

    def _take_group_axis(value: Any) -> Any:
        if value is None:
            return None
        arr = np.asarray(value)
        if arr.ndim < 2:
            return value
        return np.take(arr, group_indices, axis=1)

    source_products = group_result.get_products_by_group()
    new_products_by_group = {
        new_idx: dict(source_products.get(old_idx, {}))
        for new_idx, old_idx in enumerate(group_indices)
    }

    report_df = group_result.report_df.reindex(group_indices).copy()
    report_df.index = pd.Index(range(len(group_indices)))

    new_group_names = {
        new_idx: old_group_names.get(old_idx, f"group_{new_idx}")
        for new_idx, old_idx in enumerate(group_indices)
    }

    new_group_count = len(group_indices)
    return GroupRunResult(
        fee_costs_np=np.take(group_result.fee_costs_np, group_indices, axis=1),
        trade_notional_ratio_np=np.take(group_result.trade_notional_ratio_np, group_indices, axis=1),
        gross_returns_np=np.take(group_result.gross_returns_np, group_indices, axis=1),
        product_gross_contrib_np=np.take(group_result.product_gross_contrib_np, group_indices, axis=1),
        product_fee_contrib_np=np.take(group_result.product_fee_contrib_np, group_indices, axis=1),
        returns_np=np.take(group_result.returns_np, group_indices, axis=1),
        period_returns_np=group_result.period_returns_np.copy(),
        membership_np=np.take(group_result.membership_np, group_indices, axis=1),
        products_by_group=new_products_by_group,
        valid_cols=list(group_result.valid_cols),
        open_ratio_mat=np.asarray(group_result.open_ratio_mat).copy(),
        open_fixed_mat=None if group_result.open_fixed_mat is None else np.asarray(group_result.open_fixed_mat).copy(),
        close_ratio_mat=np.asarray(group_result.close_ratio_mat).copy(),
        close_fixed_mat=None if group_result.close_fixed_mat is None else np.asarray(group_result.close_fixed_mat).copy(),
        close_today_ratio_mat=np.asarray(group_result.close_today_ratio_mat).copy(),
        close_today_fixed_mat=None if group_result.close_today_fixed_mat is None else np.asarray(group_result.close_today_fixed_mat).copy(),
        use_closetoday_vec=None if group_result.use_closetoday_vec is None else np.asarray(group_result.use_closetoday_vec).copy(),
        index_list=list(group_result.index_list),
        multi_session_active=bool(group_result.multi_session_active),
        rebalance_trigger=str(group_result.rebalance_trigger),
        position_policy=str(group_result.position_policy),
        report_df=report_df,
        group_names=new_group_names,
        hold_amounts_np=_take_group_axis(group_result.hold_amounts_np),
        target_amounts_before_floor_np=_take_group_axis(group_result.target_amounts_before_floor_np),
        position_quantities_np=_take_group_axis(group_result.position_quantities_np),
        prev_end_amounts_np=_take_group_axis(group_result.prev_end_amounts_np),
        margin_occupied_np=_take_group_axis(group_result.margin_occupied_np),
        pre_rebalance_total_equity_np=_take_group_axis(group_result.pre_rebalance_total_equity_np),
        post_rebalance_total_equity_np=_take_group_axis(group_result.post_rebalance_total_equity_np),
        total_equity_np=_take_group_axis(group_result.total_equity_np),
        pre_rebalance_cash_np=_take_group_axis(group_result.pre_rebalance_cash_np),
        post_rebalance_cash_np=_take_group_axis(group_result.post_rebalance_cash_np),
        post_settlement_cash_np=_take_group_axis(group_result.post_settlement_cash_np),
        cash_np=_take_group_axis(group_result.cash_np),
        buy_fee_amount_np=_take_group_axis(group_result.buy_fee_amount_np),
        sell_fee_amount_np=_take_group_axis(group_result.sell_fee_amount_np),
        initial_capital=group_result.initial_capital,
        price_np=None if group_result.price_np is None else np.asarray(group_result.price_np).copy(),
        point_value_mat=None if group_result.point_value_mat is None else np.asarray(group_result.point_value_mat).copy(),
        min_tick_mat=None if group_result.min_tick_mat is None else np.asarray(group_result.min_tick_mat).copy(),
        min_trade_quantity_mat=None if group_result.min_trade_quantity_mat is None else np.asarray(group_result.min_trade_quantity_mat).copy(),
        margin_ratio_mat=None if group_result.margin_ratio_mat is None else np.asarray(group_result.margin_ratio_mat).copy(),
        is_margin_traded_vec=None if group_result.is_margin_traded_vec is None else np.asarray(group_result.is_margin_traded_vec).copy(),
        base_currency=str(getattr(group_result, "base_currency", "CNY") or "CNY"),
        product_currency_vec=None if getattr(group_result, "product_currency_vec", None) is None else np.asarray(group_result.product_currency_vec).copy(),
        currency_conversion_fee_rate=float(getattr(group_result, "currency_conversion_fee_rate", 0.0) or 0.0),
        liquidity_capacity_np=_take_group_axis(group_result.liquidity_capacity_np),
        liquidity_modes=list(group_result.liquidity_modes) if group_result.liquidity_modes is not None else None,
        liquidity_percents=list(group_result.liquidity_percents) if group_result.liquidity_percents is not None else None,
        one_lot_margin_np=_take_group_axis(group_result.one_lot_margin_np),
        one_lot_fee_np=_take_group_axis(group_result.one_lot_fee_np),
    )


def materialize_group_outputs_from_result(
    group_result: GroupRunResult,
) -> tuple[dict[int, dict[Any, float]], pd.DataFrame, np.ndarray, list]:
    """Rebuild legacy single-run outputs from a flat-group result object."""
    group_returns_np = np.asarray(group_result.returns_np, dtype=float)
    index_list = list(group_result.index_list)
    group_count = group_returns_np.shape[1]
    returns_dict = {
        g: {
            idx_entry: float(value)
            for idx_entry, value in zip(index_list, group_returns_np[:, g])
        }
        for g in range(group_count)
    }
    bad = np.isnan(group_returns_np) | np.isinf(group_returns_np) | (group_returns_np <= -1.0)
    returns_filled = np.where(bad, 0.0, group_returns_np)
    capital = getattr(group_result, 'initial_capital', 1.0)
    if capital is None:
        capital = 1.0
    cumulative_returns_np = np.cumsum(returns_filled * float(capital), axis=0)
    return returns_dict, group_result.report_df.copy(), cumulative_returns_np, index_list


def infer_periods_per_year(index_like) -> float:
    """Infer strategy periods/year from realised signal timestamps."""
    idx = DataIndex(pd.Index(index_like)).signal_index
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

    non_member_fee = np.nansum(prev_amounts * (~curr_mask).astype(float) * close_fees, axis=1)
    active = curr_mask & (prev_amounts > 0)
    target_each = np.zeros_like(wealth, dtype=float)

    for _ in range(_EACH_PERIOD_TARGET_MAX_ITERATIONS):
        active_fee_sum = np.nansum(active.astype(float) * close_fees, axis=1)
        active_fee_amount = np.nansum(prev_amounts * active.astype(float) * close_fees, axis=1)
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


def _prepare_group_shared_inputs(
    tester: Any,
    factor: Factor,
    *,
    returns_col: FactorNextPeriodReturns,
    start_dt: Optional[Any] = None,  # DataTime
    end_dt: Optional[Any] = None,    # DataTime
    calendar_index: Optional[pd.Index],
) -> GroupSharedInputs:
    start_date = start_dt.ts if start_dt is not None and start_dt.is_set else tester.start_date
    end_date = end_dt.ts if end_dt is not None and end_dt.is_set else tester.end_date

    r = tester._get_result(factor) if hasattr(tester, '_get_result') else None
    if r is None or r.table.empty or r.returns.empty:
        ensure_group_factor_inputs(
            tester,
            factor,
            returns_col=returns_col,
        )
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
    table_src.index = DataIndex(table_src.index).signal_index
    returns_src.index = DataIndex(returns_src.index).signal_index
    di = DataIndex(table_src.index)
    mask = di.slice_by_datatime(start_dt, end_dt)
    table_src = cast(pd.DataFrame, table_src[mask])
    di_r = DataIndex(returns_src.index)
    mask_r = di_r.slice_by_datatime(start_dt, end_dt)
    returns_src = cast(pd.DataFrame, returns_src[mask_r])

    signal_index = table_src.index.intersection(returns_src.index)
    if len(signal_index) == 0:
        def _idx_span(idx: pd.Index) -> str:
            if len(idx) == 0:
                return "empty"
            return f"{idx[0]} -> {idx[-1]} ({len(idx)} rows)"

        raise ValueError(
            f"{factor.alias}: 因子表和收益表没有共同时间索引；"
            f"factor={_idx_span(table_src.index)}, returns={_idx_span(returns_src.index)}"
        )
    table_src = table_src.loc[signal_index]
    returns_src = returns_src.loc[signal_index]
    raw_signal_count = int(len(signal_index))

    if calendar_index is not None and len(calendar_index) > 0:
        common_index = pd.Index(calendar_index)
        signal_update_mask = common_index.isin(signal_index)
        table_src = table_src.reindex(common_index)
        returns_src = returns_src.reindex(common_index)
    else:
        common_index = signal_index
        signal_update_mask = np.ones(len(common_index), dtype=bool)
    signal_update_count = int(np.count_nonzero(signal_update_mask))
    calendar_count = int(len(common_index))
    _emit_progress(
        "signal_sequence",
        (
            f"{factor.alias} 信号序列：原始 {raw_signal_count} 点，"
            f"公共时钟 {calendar_count} 点，实际更新 {signal_update_count} 点"
        ),
        completed=signal_update_count,
        total=max(calendar_count, 1),
        raw_signal_count=raw_signal_count,
        calendar_count=calendar_count,
        signal_update_count=signal_update_count,
        calendar_expansion_ratio=(
            float(calendar_count) / float(max(raw_signal_count, 1))
        ),
        first_signal=str(signal_index[0]) if raw_signal_count else "",
        last_signal=str(signal_index[-1]) if raw_signal_count else "",
    )

    all_cols = list(table_src.columns)
    ret_cols = list(returns_src.columns)
    signal_valid_cols = list(set((valid := table_src.isna().all(axis=0))[~valid].index).intersection(set(ret_cols)))
    if not signal_valid_cols:
        raise ValueError(
            f"{factor.alias}: 因子表和收益表没有共同品种列；"
            f"factor_cols={len(all_cols)}, returns_cols={len(ret_cols)}"
        )

    table_np = table_src[signal_valid_cols].to_numpy(dtype=float)
    signal_returns_np = returns_src[signal_valid_cols].to_numpy(dtype=float)

    def _trade_price_column(col: FactorNextPeriodReturns) -> DataColumn:
        dc = DataColumn(col.value)
        if dc == DataColumn.OPEN_ADJUSTED:
            return DataColumn.OPEN
        if dc == DataColumn.CLOSE_ADJUSTED:
            return DataColumn.CLOSE
        return dc

    from tools.factors.expr import ColumnRef
    price_col = _trade_price_column(returns_col)
    source_freq = cast(
        DataFreq,
        factor._source_freq
        if getattr(factor, "_source_freq", None) is not None
        else (factor.freq if getattr(factor, "freq", None) is not None else DataFreq.MIN1),
    )
    effective_return_freq = cast(
        DataFreq,
        r.return_freq
        if r is not None and getattr(r, "return_freq", None) is not None
        else (factor.freq if getattr(factor, "freq", None) is not None else source_freq),
    )
    raw_prices = ColumnRef(price_col).evaluate(
        products=signal_valid_cols,
        freq=source_freq,
        start_calc_point=start_dt,
    )
    price_src = align_table_for_group(factor, raw_prices)
    settlement_bar_mask_df = pd.DataFrame(
        np.column_stack(
            [
                _end_of_trading_day_mask_for_column(
                    price_src.index,
                    price_src.iloc[:, col_idx].to_numpy(dtype=float),
                )
                for col_idx in range(price_src.shape[1])
            ]
        ) if price_src.shape[1] > 0 else np.zeros((len(price_src.index), 0), dtype=bool),
        index=price_src.index,
        columns=signal_valid_cols,
    )
    price_src.index = DataIndex(price_src.index).signal_index
    di_p = DataIndex(price_src.index)
    mask_p = di_p.slice_by_datatime(start_dt, end_dt)
    price_src = cast(pd.DataFrame, price_src[mask_p])
    price_src = price_src.reindex(index=common_index, columns=signal_valid_cols)
    settlement_bar_mask_df = cast(pd.DataFrame, settlement_bar_mask_df[mask_p])
    settlement_bar_mask_df = settlement_bar_mask_df.reindex(index=common_index, columns=signal_valid_cols, fill_value=False)
    if price_src.isna().all(axis=None):
        raise ValueError(f"{factor.alias}: 无法取得分组回测交易价格列 {price_col.name}")

    present_src: Optional[pd.DataFrame] = None
    if r is not None and hasattr(r, "data_present_mask"):
        try:
            _pm = getattr(r, "data_present_mask")
            if isinstance(_pm, pd.DataFrame) and not _pm.empty:
                present_src = _pm.copy(deep=False)
        except Exception:
            present_src = None
    if present_src is None:
        raise ValueError(f"{factor.alias}: data_present_mask 不可用，无法进行分组测试。")

    _all_nan = np.all(np.isnan(table_np), axis=1)
    _valid_signal_rows = signal_update_mask & (~_all_nan)
    if not _valid_signal_rows.any():
        raise ValueError(f"{factor.alias}: 因子值序列全部为 NaN，无法进行分组测试。")

    # When a calendar_index is provided, keep the full alignment index to ensure
    # all factors in the same batch share the same T dimension.  Factors with
    # missing signals naturally carry forward their last membership via the
    # nan-handling in _build_group_membership_from_shared (forward-fill).
    if calendar_index is not None and len(calendar_index) > 0:
        # no trim — keep full common_index (= calendar_index)
        trim_start = 0
        trim_end = len(_all_nan)
    else:
        valid_positions = np.flatnonzero(_valid_signal_rows)
        _first_valid = int(valid_positions[0])
        _last_valid = int(valid_positions[-1])
        trim_start = _first_valid
        trim_end = _last_valid + 1
        if trim_start > 0 or trim_end < len(_all_nan):
            signal_update_mask = signal_update_mask[trim_start:trim_end]
            table_np = table_np[trim_start:trim_end]
            signal_returns_np = signal_returns_np[trim_start:trim_end]
            table_src = table_src.iloc[trim_start:trim_end]
            returns_src = returns_src.iloc[trim_start:trim_end]
            price_src = price_src.iloc[trim_start:trim_end]
            print(f"[INFO] {factor.alias}: 截断首尾全 NaN 行 {trim_start} 行首 + {len(_all_nan) - trim_end} 行尾")

    _all_nan_mid = np.all(np.isnan(table_np), axis=1)
    _all_nan_mid = _all_nan_mid & signal_update_mask
    if _all_nan_mid.any():
        bad_indices = [str(table_src.index[i]) for i in np.where(_all_nan_mid)[0]]
        raise ValueError(
            f"{factor.alias}: 因子值序列在以下 {len(bad_indices)} 个时点全部品种为 NaN，"
            f"非首尾全空行，可能是数据异常：{bad_indices[:5]}{'...' if len(bad_indices) > 5 else ''}"
        )

    present_df = cast(pd.DataFrame, present_src)
    present_df.index = DataIndex(present_df.index).signal_index
    di_pr = DataIndex(present_df.index)
    mask_pr = di_pr.slice_by_datatime(start_dt, end_dt)
    present_df = cast(pd.DataFrame, present_df[mask_pr])
    present_df = present_df.reindex(index=common_index, columns=signal_valid_cols, fill_value=False)
    if trim_start > 0 or trim_end < len(_all_nan):
        present_df = present_df.iloc[trim_start:trim_end]
        settlement_bar_mask_df = settlement_bar_mask_df.iloc[trim_start:trim_end]
    present_np = present_df.to_numpy(dtype=bool)
    settlement_bar_mask = settlement_bar_mask_df.to_numpy(dtype=bool)

    index_list = list(table_src.index)
    T = len(index_list)
    P = len(signal_valid_cols)

    col_has_any_present = np.asarray(present_np.any(axis=0), dtype=bool)
    first_present = np.argmax(present_np, axis=0)
    row_idx = np.arange(T, dtype=int)[:, np.newaxis]
    head_missing = (row_idx < first_present[np.newaxis, :]) & col_has_any_present[np.newaxis, :]
    present_filled = np.where(head_missing, True, present_np)
    present_filled[:, ~col_has_any_present] = True
    mixed_mask = signal_update_mask & np.any(~present_filled, axis=1) & (~np.all(~present_filled, axis=1))
    multi_session_active = bool(mixed_mask.any())
    missing_names: list[str] = []
    if multi_session_active:
        after_head_missing = (~present_np) & (~head_missing)
        missing_cols = np.where(np.any(after_head_missing, axis=0))[0]
        missing_names = [str(signal_valid_cols[i]) for i in missing_cols]
        _emit_progress(
            "membership",
            (
                f"{factor.alias}: 检测到 {int(mixed_mask.sum())}/{T} 期存在部分品种无原始数据，"
                "已启用多时段品种处理"
            ),
            completed=0,
            total=max(T, 1),
            module="market_calendar",
            multi_session_active=True,
            multi_session_entries=[{
                "factor_alias": str(factor.alias),
                "missing_product_count": len(missing_names),
                "missing_products": missing_names[:20],
                "mixed_slice_count": int(mixed_mask.sum()),
                "slice_count": int(T),
            }],
        )
        print(
            f"[INFO] {factor.alias}: 检测到 {int(mixed_mask.sum())}/{T} 期存在部分品种无原始数据 "
            f"（{len(missing_names)} 个品种存在缺失：{', '.join(missing_names[:5])}"
            f"{'...' if len(missing_names) > 5 else ''}），"
            f"自动启用多时段品种策略。"
        )

    return GroupSharedInputs(
        start_date=start_date,
        end_date=end_date,
        price_col=price_col,
        source_freq=source_freq,
        effective_return_freq=effective_return_freq,
        table_src=table_src,
        returns_src=returns_src,
        price_src=price_src,
        signal_valid_cols=signal_valid_cols,
        table_np=table_np,
        signal_returns_np=signal_returns_np,
        present_np=present_np,
        signal_update_mask=np.asarray(signal_update_mask, dtype=bool),
        settlement_bar_mask=np.asarray(settlement_bar_mask, dtype=bool),
        index_list=index_list,
        T=T,
        P=P,
        multi_session_active=multi_session_active,
        multi_session_missing_products=missing_names,
        multi_session_missing_count=len(missing_names),
    )


def _build_group_membership_from_shared(
    factor: Factor,
    shared: GroupSharedInputs,
    *,
    group_count: int,
) -> np.ndarray:
    """Build base-group membership for one group_count setting from shared inputs."""
    T = shared.T
    P = shared.P
    membership_np = np.zeros((T, group_count, P), dtype=bool)
    current_members = np.zeros((group_count, P), dtype=bool)

    table_np = shared.table_np
    signal_returns_np = shared.signal_returns_np
    present_np = shared.present_np
    signal_update_mask = shared.signal_update_mask
    multi_session_active = shared.multi_session_active
    index_list = shared.index_list
    signal_valid_cols = shared.signal_valid_cols

    _emit_progress("membership", "开始计算分组隶属度",
                   completed=0, total=T)
    _last_report = 0
    for t in tqdm(range(T), desc="Computing memberships: " + factor.alias):
        if t > 0 and not bool(signal_update_mask[t]):
            membership_np[t] = current_members
            continue

        row = table_np[t]
        ret_row = signal_returns_np[t]

        isnan_ret = np.isnan(ret_row)
        isnan_fac = np.isnan(row)
        isbad_ret = (ret_row <= -1.0) | np.isinf(ret_row)
        if isbad_ret.any():
            bad_products = [signal_valid_cols[i] for i in np.where(isbad_ret)[0]]
            bad_rets = [float(ret_row[i]) for i in np.where(isbad_ret)[0]]
            print(
                f"[WARN] t={t} ({index_list[t]}): 品种收益异常（≤-1 或 inf），将从分配中剔除: "
                + ", ".join(f"{p}={r:.4f}" for p, r in zip(bad_products, bad_rets))
            )

        if t == 0:
            carry_members = np.zeros((group_count, P), dtype=bool)
        elif multi_session_active:
            has_data_t = present_np[t]
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

        # 每 10% 发射一次进度
        pct = int(t / T * 10)
        if pct > _last_report or t == T - 1:
            _last_report = pct
            _emit_progress("membership", f"计算分组隶属度 {t+1}/{T}",
                           completed=t + 1, total=T)

    _emit_progress("membership", "分组隶属度计算完成",
                   completed=T, total=T)
    return membership_np


def _build_group_memberships_from_shared(
    factor: Factor,
    shared: GroupSharedInputs,
    *,
    group_counts: list[int],
) -> list[np.ndarray]:
    """Build several base-group memberships from the same shared inputs."""
    memberships = []
    total = len(group_counts)
    for i, group_count in enumerate(group_counts):
        _emit_progress("membership", f"构建分组隶属度 {i+1}/{total}，组数 {group_count}",
                       completed=i, total=total)
        memberships.append(
            _build_group_membership_from_shared(
                factor,
                shared,
                group_count=int(group_count),
            )
        )
    _emit_progress("membership", "全部分组隶属度构建完成",
                   completed=total, total=total)
    return memberships


def _build_product_remap_matrix(
    signal_products: list,
    signal_index: list,
) -> tuple[np.ndarray, list, dict[tuple[str, str], int]]:
    """Pre-build signal-product → trade-product term-structure mapping.

    Uses a full active mask so the resulting matrix works for all membership_np
    configurations that share the same (signal_products, signal_index).

    Returns
    -------
    signal_to_trade : (T, P_signal) int
        signal_to_trade[t, pi] = position in trade_products, or -1 if unresolved.
    trade_products : list
        Deduplicated trade product list (union of contracts across all products).
    trade_pos_by_key : dict
        (cls_name, product_name) → index in trade_products.
    """
    T = len(signal_index)
    P_signal = len(signal_products)
    signal_days = DataIndex(signal_index).to_trading_days()
    full_mask = np.ones(T, dtype=bool)

    trade_products: list = []
    trade_pos_by_key: dict[tuple[str, str], int] = {}
    signal_to_trade = np.full((T, P_signal), -1, dtype=int)

    for pi, product in enumerate(tqdm(
        signal_products,
        desc="Build product remap matrix",
        total=P_signal,
    )):
        signal_to_trade[:, pi] = _expand_single_trade_product(
            product, signal_days, full_mask,
            trade_products, trade_pos_by_key,
        )
    return signal_to_trade, trade_products, trade_pos_by_key


def _remap_membership_to_trade(
    membership_np: np.ndarray,
    signal_to_trade: np.ndarray,
    trade_count: int,
) -> np.ndarray:
    """Remap signal-dim membership to trade-dim using pre-built contract matrix.

    membership_np  : (T, M, P_signal) bool
    signal_to_trade: (T, P_signal) int, from _build_product_remap_matrix
    trade_count    : len(trade_products)

    Returns (T, M, trade_count) bool membership on trade-product axis.
    """
    T, M, P_signal = membership_np.shape
    trade_membership = np.zeros((T, M, trade_count), dtype=bool)

    active_t, active_g, active_pi = np.nonzero(membership_np)
    if active_t.size == 0:
        return trade_membership

    mapped_pos = signal_to_trade[active_t, active_pi]
    valid = mapped_pos >= 0
    if valid.any():
        trade_membership[
            active_t[valid],
            active_g[valid],
            mapped_pos[valid],
        ] = True

    return trade_membership


def _load_group_trade_returns(
    tester: Any,
    factor: Factor,
    *,
    trade_valid_cols: list,
    returns_col: FactorNextPeriodReturns,
    source_freq: DataFreq,
    effective_return_freq: DataFreq,
    start_dt: Optional[Any] = None,  # DataTime
    end_dt: Optional[Any] = None,    # DataTime
    index_list: list,
) -> np.ndarray:
    trade_returns_src = _evaluate_trade_returns_for_group(
        tester,
        factor,
        trade_valid_cols,
        returns_col,
        source_freq,
        effective_return_freq,
    )
    trade_returns_src.index = DataIndex(trade_returns_src.index).signal_index
    di = DataIndex(trade_returns_src.index)
    mask = di.slice_by_datatime(start_dt, end_dt)
    trade_returns_src = cast(pd.DataFrame, trade_returns_src[mask])
    trade_returns_src = trade_returns_src.reindex(index=index_list, columns=trade_valid_cols)
    return trade_returns_src[trade_valid_cols].to_numpy(dtype=float)


def _load_group_trade_prices(
    factor: Factor,
    *,
    trade_valid_cols: list,
    price_col: DataColumn,
    source_freq: DataFreq,
    start_dt: Optional[Any] = None,  # DataTime
    end_dt: Optional[Any] = None,    # DataTime
    index_list: list,
) -> np.ndarray:
    from tools.factors.expr import ColumnRef

    raw_trade_prices = ColumnRef(price_col).evaluate(
        products=trade_valid_cols,
        freq=source_freq,
        start_calc_point=start_dt,
    )
    trade_price_src = align_table_for_group(factor, raw_trade_prices)
    trade_price_src.index = DataIndex(trade_price_src.index).signal_index
    di = DataIndex(trade_price_src.index)
    mask = di.slice_by_datatime(start_dt, end_dt)
    trade_price_src = cast(pd.DataFrame, trade_price_src[mask])
    trade_price_src = trade_price_src.reindex(index=index_list, columns=trade_valid_cols)
    price_np = trade_price_src[trade_valid_cols].to_numpy(dtype=float)
    return price_np


def _resolve_group_trade_specs(
    *,
    signal_valid_cols: list,
    valid_cols: list,
    fee: float,
    fee_modifications: list | None = None,
    use_closetoday: bool = False,
    index_list: pd.DatetimeIndex | list | None = None,
    market_rule_fallback: str = "latest_available",
) -> GroupTradeSpecBundle:
    term_structure_paths = list(dict.fromkeys(
        path
        for product in signal_valid_cols
        for getter in [getattr(product, "get_term_structure_path", None)]
        for path in [getter() if callable(getter) else None]
        if path
    ))
    contract_parent_cache: dict[str, str | None] = {}

    def _variety(col) -> str:
        nm = getattr(col, "name", str(col))
        marker = getattr(col, "is_term_contract", None)
        try:
            is_term_contract = bool(marker()) if callable(marker) else bool(marker)
        except Exception:
            is_term_contract = False
        if is_term_contract and term_structure_paths:
            if nm not in contract_parent_cache:
                contract_parent_cache[nm] = lookup_contract_product(nm, term_structure_paths)
            parent = contract_parent_cache[nm]
            if parent:
                return str(parent).split(".")[0].upper()
        return nm.split(".")[0].upper()

    variety_codes = [_variety(col) for col in valid_cols]
    variety_codes_lower = [code.lower() for code in variety_codes]
    variety_code_by_id = {id(col): code for col, code in zip(valid_cols, variety_codes)}
    positions_by_variety_code_lower: dict[str, list[int]] = {}
    for idx, code_lower in enumerate(variety_codes_lower):
        positions_by_variety_code_lower.setdefault(code_lower, []).append(idx)

    P = len(valid_cols)

    # ── Build modifications_by_variety from fee_modifications ──
    modifications_by_variety: dict[str, dict] = {}
    if fee_modifications:
        from tools.products.transactions.fees import (
            clean_modifications, sort_modifications, VALID_FEE_FIELDS,
        )
        cleaned = sort_modifications(clean_modifications(fee_modifications))
        for mod in cleaned:
            vc = mod.variety_code.upper()
            fields = modifications_by_variety.setdefault(vc, {})
            for fname, fval in mod.fields.items():
                if fname in VALID_FEE_FIELDS:
                    fields[fname] = float(fval)

    full_index = pd.DatetimeIndex(index_list) if index_list is not None else pd.DatetimeIndex([])

    # ── Time-varying specs via date-range query.
    # latest_available intentionally does not query a full historical panel:
    # until a dedicated historical provider is connected, the current product
    # object / latest local snapshot is the explicit as-of source and is
    # broadcast across the evaluation range.
    db_time_specs: dict[str, pd.DataFrame] = {}
    if market_rule_fallback == "strict_historical" and len(full_index) > 0:
        _spec_field_names = (
            "multiplier", "min_tick", "min_trade_quantity", "long_margin_ratio",
            "open_ratio", "open_fixed", "close_ratio", "close_fixed",
            "closetoday_ratio", "closetoday_fixed",
        )
        try:
            from sources.OpenCTP.fields import get_products_specs_over_date_range
            trading_days = pd.DatetimeIndex(full_index.normalize().unique()).sort_values()
            db_time_specs = get_products_specs_over_date_range(
                products=list(valid_cols),
                trading_days=trading_days,
                fields=list(_spec_field_names),
            )
        except Exception as exc:
            raise RuntimeError(
                f"历史市场规则查询失败，strict_historical 不允许回退: {exc}"
            ) from exc

    T = len(full_index) if len(full_index) else 1

    # ── Compute product-level defaults for fallback ──
    half_fee = float(fee) / 2.0

    # Static product attributes (not time-varying)
    use_closetoday_list: list[bool] = []
    is_margin_traded_list: list[bool] = []

    # Per-product defaults (used when DB has no data)
    prod_open_ratio: list[float] = []
    prod_open_fixed: list[float] = []
    prod_close_ratio: list[float] = []
    prod_close_fixed: list[float] = []
    prod_closetoday_ratio: list[float] = []
    prod_closetoday_fixed: list[float] = []
    prod_multiplier: list[float] = []
    prod_min_tick: list[float] = []
    prod_min_trade_qty: list[float] = []
    prod_long_margin_ratio: list[float] = []

    _MOD_FIELD_TO_PRODUCT_FIELD = {
        "open_ratio": "open_ratio",
        "close_ratio": "close_ratio",
        "closetoday_ratio": "closetoday_ratio",
        "open_fixed": "open_fixed",
        "close_fixed": "close_fixed",
        "closetoday_fixed": "closetoday_fixed",
    }

    for col in valid_cols:
        mod_overrides = modifications_by_variety.get(
            variety_code_by_id.get(id(col), ""), {}
        )

        def _pick_value(default: Any, field_name: str) -> Any:
            """优先取 fee_modifications 覆盖，其次取产品对象属性，最后用 default。"""
            mod_val = mod_overrides.get(field_name)
            if mod_val not in (None, ""):
                return mod_val
            # 通过映射表找到产品对象上实际的属性名
            product_field = _MOD_FIELD_TO_PRODUCT_FIELD.get(field_name, field_name)
            return getattr(col, product_field, default)

        prod_open_ratio.append(_coerce_float(_pick_value(half_fee, "open_ratio"), half_fee))
        prod_open_fixed.append(_coerce_float(_pick_value(0.0, "open_fixed"), 0.0))
        close_ratio_val = _coerce_float(_pick_value(half_fee, "close_ratio"), half_fee)
        prod_close_ratio.append(close_ratio_val)
        close_fixed_val = _coerce_float(_pick_value(0.0, "close_fixed"), 0.0)
        prod_close_fixed.append(close_fixed_val)
        prod_closetoday_ratio.append(_coerce_float(_pick_value(close_ratio_val, "closetoday_ratio"), close_ratio_val))
        prod_closetoday_fixed.append(_coerce_float(_pick_value(close_fixed_val, "closetoday_fixed"), close_fixed_val))

    for col in valid_cols:
        use_closetoday_list.append(bool(getattr(col, "use_closetoday", None) or use_closetoday))
        point_val = getattr(col, "point_value", None)
        if point_val is None or point_val == 1.0:
            prod_multiplier.append(float(getattr(col, "multiplier", 1.0) or 1.0))
        else:
            prod_multiplier.append(float(point_val))
        prod_min_tick.append(float(getattr(col, "min_tick", 0.0) or 0.0))
        prod_min_trade_qty.append(float(getattr(col, "min_trade_quantity", 1.0) or 1.0))
        prod_long_margin_ratio.append(float(getattr(col, "long_margin_ratio", 1.0) or 1.0))
        is_margin_traded_list.append(bool(getattr(col, "is_margin_traded", False)))

    # ── Build (T, P) matrices ──
    if market_rule_fallback not in {
        "latest_available", "strict_historical", "configured_default"
    }:
        raise ValueError(f"unsupported market_rule_fallback: {market_rule_fallback}")
    rule_provenance: dict[str, dict[str, int]] = {}

    def _build_mat(field: str, per_product_defaults: list[float], default_fallback: float = 0.0) -> np.ndarray:
        """Resolve historical rules under an explicit, observable fallback policy."""
        df = db_time_specs.get(field)
        if market_rule_fallback == "latest_available":
            mat = np.broadcast_to(
                np.asarray(per_product_defaults, dtype=float).reshape(1, P), (T, P)
            ).copy()
            rule_provenance[field] = {
                "effective_at": 0,
                "as_of_latest": int(mat.size),
                "configured_default": 0,
            }
            return mat
        if market_rule_fallback == "configured_default":
            mat = np.full((T, P), float(default_fallback), dtype=float)
            rule_provenance[field] = {
                "effective_at": 0,
                "as_of_latest": 0,
                "configured_default": int(mat.size),
            }
            return mat
        if df is not None and not df.empty:
            day_index = full_index.normalize() if len(full_index) else pd.DatetimeIndex([])
            mat = df.reindex(index=day_index).to_numpy(dtype=float)
            if mat.shape != (T, P):
                raise ValueError(
                    f"历史市场规则 {field} shape={mat.shape}，期望 {(T, P)}"
                )
        else:
            mat = np.full((T, P), np.nan, dtype=float)
        missing = ~np.isfinite(mat)
        missing_count = int(np.count_nonzero(missing))
        rule_provenance[field] = {
            "effective_at": int(mat.size - missing_count),
            "as_of_latest": 0,
            "configured_default": 0,
        }
        if not missing_count:
            return mat
        if market_rule_fallback == "strict_historical":
            row, column = np.argwhere(missing)[0]
            product_name = getattr(valid_cols[int(column)], "name", str(valid_cols[int(column)]))
            timestamp = full_index[int(row)] if len(full_index) else row
            raise ValueError(
                f"缺少历史市场规则 field={field}, product={product_name}, timestamp={timestamp}"
            )
        if market_rule_fallback == "latest_available":
            fallback_values = np.broadcast_to(
                np.asarray(per_product_defaults, dtype=float).reshape(1, P), (T, P)
            )
            mat = np.where(missing, fallback_values, mat)
            rule_provenance[field]["as_of_latest"] = missing_count
        else:
            mat = np.where(missing, float(default_fallback), mat)
            rule_provenance[field]["configured_default"] = missing_count
        return mat

    open_ratio_mat = _build_mat("open_ratio", prod_open_ratio, half_fee)
    open_fixed_mat = _build_mat("open_fixed", prod_open_fixed, 0.0)
    close_ratio_mat = _build_mat("close_ratio", prod_close_ratio, half_fee)
    close_fixed_mat = _build_mat("close_fixed", prod_close_fixed, 0.0)
    closetoday_ratio_mat = _build_mat("closetoday_ratio", prod_closetoday_ratio, half_fee)
    closetoday_fixed_mat = _build_mat("closetoday_fixed", prod_closetoday_fixed, 0.0)
    multiplier_mat = _build_mat("multiplier", prod_multiplier, 1.0)
    min_tick_mat = _build_mat("min_tick", prod_min_tick, 0.0)
    min_trade_quantity_mat = _build_mat("min_trade_quantity", prod_min_trade_qty, 1.0)
    long_margin_ratio_mat = _build_mat("long_margin_ratio", prod_long_margin_ratio, 1.0)

    return GroupTradeSpecBundle(
        valid_cols=list(valid_cols),
        open_ratio_mat=open_ratio_mat,
        open_fixed_mat=open_fixed_mat,
        close_ratio_mat=close_ratio_mat,
        close_fixed_mat=close_fixed_mat,
        closetoday_ratio_mat=closetoday_ratio_mat,
        closetoday_fixed_mat=closetoday_fixed_mat,
        use_closetoday_vec=np.asarray(use_closetoday_list, dtype=bool),
        multiplier_mat=multiplier_mat,
        min_tick_mat=min_tick_mat,
        min_trade_quantity_mat=min_trade_quantity_mat,
        long_margin_ratio_mat=long_margin_ratio_mat,
        is_margin_traded_vec=np.asarray(is_margin_traded_list, dtype=bool),
        variety_codes_lower=variety_codes_lower,
        positions_by_variety_code_lower=positions_by_variety_code_lower,
        rule_provenance=rule_provenance,
    )


def build_flat_membership_from_groups(
    groups: list,
    *,
    shared_inputs_by_triple: dict,
    signal_valid_cols_by_triple: dict,
    memberships_by_triple: dict,
) -> tuple[np.ndarray, list[dict]]:
    """Build a flat (T, M_total, P) membership from a list of _FactorGroupTestGroup.

    Strategy:
    1. Groups are already deduplicated by (tester_id, factor_alias, n_groups) —
       the caller has pre-computed membership for each unique triple.
    2. For each group:
       - If product_list is None: copy the membership row directly.
       - If product_list is set: copy only the columns matching those products
         (zero out others), i.e. intersection of base membership & product filter.

    Returns
    -------
    membership_np : (T, M_total, P) bool
        Concatenated membership across all groups.
    group_info : list[dict]
        Per-global-group-index metadata dict: {group_index, name, id, product_names, ...}.
    """
    from tools.products.product_utils import product_display_name

    if not groups:
        raise ValueError("groups must not be empty")

    # Determine P from the first group's shared inputs
    first_group = groups[0]
    first_triple = first_group.triple_key
    first_shared = shared_inputs_by_triple.get(first_triple)
    if first_shared is None:
        raise ValueError(
            f"Unknown triple {first_triple} in shared_inputs_by_triple"
        )
    first_valid_cols = signal_valid_cols_by_triple.get(first_triple)
    if first_valid_cols is None:
        first_valid_cols = first_shared.signal_valid_cols

    T = first_shared.T
    P = len(first_valid_cols)



    slices: list[np.ndarray] = []
    group_info: list[dict] = []

    def _apply_group_signal_window(group: Any, mask_1g: np.ndarray, shared: Any) -> np.ndarray:
        start_dt = getattr(group, "signal_start_dt", None)
        end_dt = getattr(group, "signal_end_dt", None)
        if start_dt is None and end_dt is None:
            return mask_1g
        index_list = getattr(shared, "index_list", None)
        if index_list is None:
            return mask_1g
        time_mask = DataIndex(pd.Index(index_list)).slice_by_datatime(start_dt, end_dt)
        time_mask = np.asarray(time_mask, dtype=bool)
        if time_mask.shape[0] != mask_1g.shape[0]:
            raise ValueError(
                f"group signal window mask length mismatch: mask={time_mask.shape[0]} "
                f"membership={mask_1g.shape[0]} group={getattr(group, 'name', '')}"
            )
        clipped = mask_1g.copy()
        clipped[~time_mask, :, :] = False
        return clipped

    for gi, group in enumerate(groups):
        triple = group.triple_key
        shared = shared_inputs_by_triple.get(triple)
        base_membership = memberships_by_triple.get(triple)
        if base_membership is None:
            raise ValueError(f"Missing base membership for triple {triple}")
        if shared is None:
            raise ValueError(f"Missing shared inputs for triple {triple}")
        valid_cols = signal_valid_cols_by_triple.get(triple) or []
        if not list(valid_cols):
            valid_cols = list(first_valid_cols)

        source_row = base_membership[:, group.group_index, :]  # (T, P)

        if group.product_list:
            # Screened group: intersect base membership with product filter
            display_names_map = {
                product_display_name(product)['name']: idx
                for idx, product in enumerate(valid_cols)
            }
            selected_idx = []
            for pname in group.product_list:
                pos = display_names_map.get(pname)
                if pos is None:
                    # Case-insensitive fallback
                    lower_map = {k.lower(): v for k, v in display_names_map.items()}
                    pos = lower_map.get(pname.lower())
                if pos is not None:
                    selected_idx.append(pos)

            mask_1g = np.zeros((T, 1, P), dtype=bool)
            if selected_idx:
                sel = np.asarray(selected_idx, dtype=int)
                mask_1g[:, 0, sel] = source_row[:, sel]
            mask_1g = _apply_group_signal_window(group, mask_1g, shared)
            slices.append(mask_1g)
            group_info.append({
                'group_index': group.group_index,
                'key': group.key,
                'name': group.name,
                'id': group._id,
                'product_names': group.product_list,
                'fee_mode': group.fee_mode,
                'fee_rate': group.fee_rate,
                'fee_modifications': group.fee_modifications,
                'use_close_today': group.use_close_today,
                'rebalance_trigger': group.rebalance_trigger,
                'position_policy': group.position_policy,
                'liquidity_mode': group.liquidity_mode,
                'liquidity_percent': group.liquidity_percent,
                'margin_mode': group.margin_mode,
                'signal_start_dt': group.signal_start_dt,
                'signal_end_dt': group.signal_end_dt,
            })
        else:
            # Identity group: copy the row directly
            mask_1g = source_row[:, np.newaxis, :].copy()  # (T, 1, P)
            mask_1g = _apply_group_signal_window(group, mask_1g, shared)
            slices.append(mask_1g)
            group_info.append({
                'group_index': group.group_index,
                'key': group.key,
                'name': group.name,
                'id': group._id,
                'product_names': None,
                'fee_mode': group.fee_mode,
                'fee_rate': group.fee_rate,
                'fee_modifications': group.fee_modifications,
                'use_close_today': group.use_close_today,
                'rebalance_trigger': group.rebalance_trigger,
                'position_policy': group.position_policy,
                'liquidity_mode': group.liquidity_mode,
                'liquidity_percent': group.liquidity_percent,
                'margin_mode': group.margin_mode,
                'signal_start_dt': group.signal_start_dt,
                'signal_end_dt': group.signal_end_dt,
            })
        _emit_progress("flat_membership", f"展开分组隶属度 {gi+1}/{len(groups)}",
                       completed=gi + 1, total=len(groups))

    membership_np = np.concatenate(slices, axis=1)  # (T, M_total, P)
    return membership_np, group_info



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



def ensure_group_factor_inputs(
    tester: Any,
    factor: Factor,
    *,
    returns_col: FactorNextPeriodReturns,
) -> None:
    """Compute factor exposures and forward returns needed by group testing.

    Group testing can run without a prior IC test. In that case this function
    fills the tester-scoped FactorRunResult with the same minimum inputs that
    the group pipeline expects: factor table and next-period returns.
    """
    if not hasattr(tester, "_get_result"):
        return

    r = tester._get_result(factor)
    needs_factor_eval = not isinstance(r.table, pd.DataFrame) or r.table.empty
    needs_returns_eval = not isinstance(r.returns, pd.DataFrame) or r.returns.empty
    if not needs_factor_eval and not needs_returns_eval:
        # 两个阶段都有缓存，用 completed=0 避免覆盖真实计算记录
        _emit_progress("factor_eval", "因子已有缓存，跳过", completed=0, total=0)
        _emit_progress("returns_eval", "收益率已有缓存，跳过", completed=0, total=0)
        return

    from tools.factors.FactorTester import _active_tester
    from tools.factors.eval_progress import count_nodes, setup as setup_progress, teardown as teardown_progress

    return_freq = cast(
        DataFreq,
        r.return_freq
        if getattr(r, "return_freq", None) is not None
        else (factor.freq if getattr(factor, "freq", None) is not None else DataFreq.MIN1),
    )
    returns_factor = None
    if needs_returns_eval:
        shift = 0 if returns_col.value.name.startswith("OPEN") else 1
        returns_factor = NextReturns().get_factor(
            SC=returns_col.value,
            RF=return_freq.value,
            S=shift,
            **{'$F': return_freq.value, '$Rev': '0'},
        )

    token = _active_tester.set(tester)
    try:
        if needs_factor_eval:
            factor_nodes = count_nodes(factor._expr)
            _emit_progress(
                "factor_eval",
                f"计算因子 {0}/{factor_nodes}",
                completed=0,
                total=factor_nodes,
            )
            setup_progress(
                factor_nodes,
                lambda completed, total: _emit_progress(
                    "factor_eval",
                    f"计算因子 {completed}/{total}",
                    completed=completed,
                    total=total,
                ),
            )
            try:
                factor.evaluate(tester.products)
            finally:
                teardown_progress()
        else:
            # 因子已有缓存，用 completed=0 避免覆盖真实计算记录
            _emit_progress("factor_eval", "因子已有缓存，跳过", completed=0, total=0)
        if needs_returns_eval and returns_factor is not None:
            source_freq = cast(
                DataFreq,
                factor._source_freq
                if getattr(factor, "_source_freq", None) is not None
                else (factor.freq if getattr(factor, "freq", None) is not None else DataFreq.MIN1),
            )
            returns_nodes = count_nodes(returns_factor._expr)
            _emit_progress(
                "returns_eval",
                f"计算收益 {0}/{returns_nodes}",
                completed=0,
                total=returns_nodes,
            )
            setup_progress(
                returns_nodes,
                lambda completed, total: _emit_progress(
                    "returns_eval",
                    f"计算收益 {completed}/{total}",
                    completed=completed,
                    total=total,
                ),
            )
            try:
                returns_table = returns_factor.evaluate(tester.products, freq=source_freq)
                r.returns = cast(pd.DataFrame, returns_table.copy(deep=False))
                r.return_freq = return_freq
            finally:
                teardown_progress()
        else:
            # 收益率已有缓存，用 completed=0 避免覆盖真实计算记录
            _emit_progress("returns_eval", "收益率已有缓存，跳过", completed=0, total=0)
    finally:
        _active_tester.reset(token)
        if returns_factor is not None:
            if hasattr(tester, "discard_result"):
                tester.discard_result(returns_factor)
            else:
                returns_factor.clear()


def _is_roll_mapped_product(product: Any) -> bool:
    if getattr(product, "is_term_contract", None):
        try:
            if bool(product.is_term_contract()):
                return False
        except Exception:
            pass
    return callable(getattr(product, "get_contract_from_trading_day", None))


def _resolve_trade_product(product: Any, signal_time: Any) -> Any:
    if not _is_roll_mapped_product(product):
        return product
    try:
        contract = product.get_contract_from_trading_day(signal_time)
    except Exception:
        contract = None
    return contract if contract is not None else product


def _product_identity(product: Any) -> tuple[str, str]:
    cls_name = type(product).__name__
    name = str(getattr(product, "name", product))
    return cls_name, name


def _append_trade_product(
    trade_products: list,
    trade_pos_by_key: dict[tuple[str, str], int],
    product: Any,
) -> int:
    key = _product_identity(product)
    pos = trade_pos_by_key.get(key)
    if pos is None:
        pos = len(trade_products)
        trade_pos_by_key[key] = pos
        trade_products.append(product)
    return pos


def _coerce_float(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return float(default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _expand_single_trade_product(
    product: Any,
    signal_days: pd.DatetimeIndex,
    active_mask: np.ndarray,
    trade_products: list,
    trade_pos_by_key: dict[tuple[str, str], int],
) -> np.ndarray:
    mapped = np.full(len(signal_days), -1, dtype=int)
    if not bool(active_mask.any()):
        return mapped
    if not _is_roll_mapped_product(product):
        pos = _append_trade_product(trade_products, trade_pos_by_key, product)
        mapped[active_mask] = pos
        return mapped

    try:
        product._ensure_roller_info()
    except Exception:
        pass
    roller_info_obj = getattr(product, "roller_info", None)
    if not isinstance(roller_info_obj, pd.DataFrame):
        roller_df = None
    else:
        roller_df = cast(pd.DataFrame, roller_info_obj)
    if roller_df is not None and not roller_df.empty:
        start_days = DataIndex.normalized_days(roller_df["STARTDATE"])
        end_days = DataIndex.normalized_days(roller_df["ENDDATE"])

        roller_rows = roller_df.reset_index(drop=True)
        n_rows = len(roller_rows)
        for row_idx, row in enumerate(roller_rows.itertuples(index=False)):
            left = int(signal_days.searchsorted(start_days[row_idx], side="left"))
            if row_idx == n_rows - 1:
                # Last contract extends to the end of signal_days
                right = len(signal_days)
            else:
                right = int(signal_days.searchsorted(end_days[row_idx], side="right"))
            if left >= right:
                continue
            interval_active = active_mask[left:right]
            if not bool(interval_active.any()):
                continue
            contract_id = str(getattr(row, "CONTRACT_UID", None) or getattr(row, "CONTRACT", None) or "")
            trade_product = product.contract_class(contract_id) if contract_id else product
            pos = _append_trade_product(trade_products, trade_pos_by_key, trade_product)
            mapped_slice = mapped[left:right]
            mapped_slice[interval_active] = pos
            mapped[left:right] = mapped_slice

    return mapped


def _evaluate_trade_returns_for_group(
    tester: Any,
    factor: Factor,
    products: list,
    returns_col: FactorNextPeriodReturns,
    source_freq: DataFreq,
    return_freq: DataFreq,
) -> pd.DataFrame:
    if not products:
        return pd.DataFrame()
    shift = 0 if returns_col.value.name.startswith("OPEN") else 1
    returns_factor = NextReturns().get_factor(
        SC=returns_col.value,
        RF=return_freq.value,
        S=shift,
        **{'$F': return_freq.value, '$Rev': '0'},
    )
    try:
        table = returns_factor.evaluate(products, freq=source_freq)
        return cast(pd.DataFrame, table.copy(deep=False))
    finally:
        if hasattr(tester, "discard_result"):
            tester.discard_result(returns_factor)
        else:
            returns_factor.clear()


def _build_normalized_liquidity_capacity(
    products: list,
    signal_index: list,
    freq: DataFreq,
    start_dt: Optional[Any] = None,  # DataTime
    end_dt: Optional[Any] = None,    # DataTime
) -> np.ndarray | None:
    """Return (T, P) cross-sectional liquidity capacity shares (row sum = 1).

    These shares represent each product's proportion of the total tradable
    notional in each period. Event backtest runners convert them to absolute
    notional capacity by multiplying by current portfolio equity and the
    user-specified ``liquidity_percent``.

    A 20% liquidity setting therefore means "this strategy may trade up to 20%
    of the current period's cross-sectional tradable notional, allocated by
    product liquidity".
    """
    if not products or not signal_index:
        return None
    signal_ts = pd.DatetimeIndex(pd.to_datetime(signal_index))
    T = len(signal_ts)
    P = len(products)
    raw = np.zeros((T, P), dtype=float)

    _emit_progress("liquidity", f"开始计算流动性容量，时间点 {T} 个，品种 {P} 个", completed=0, total=P)
    for pi, product in enumerate(tqdm(products, desc="Build liquidity capacity", total=P)):
        try:
            dm = getattr(product, freq.name)
            cols = [DataColumn.TURNOVER.name, DataColumn.VOLUME.name, DataColumn.CLOSE_ADJUSTED.name]
            data = dm.get_and_adjust_cols(cols, copy=False, start_calc_point=start_dt)
            if data.empty:
                continue
            idx = DataIndex(data.index).signal_index
            frame = data.copy(deep=False)
            frame.index = idx
            mask = DataIndex(frame.index).slice_by_datatime(start_dt, end_dt)
            frame = cast(pd.DataFrame, frame[mask])
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
            pass
        finally:
            # 每 10 个产品或末个产品发射一次
            if pi % max(1, P // 10) == 0 or pi == P - 1:
                _emit_progress("liquidity", f"计算流动性容量 {pi+1}/{P}",
                               completed=pi + 1, total=P)

    row_sum = np.nansum(raw, axis=1)
    if not np.any(row_sum > 0):
        return None
    capacity = np.divide(
        raw,
        row_sum[:, np.newaxis],
        out=np.zeros_like(raw, dtype=float),
        where=row_sum[:, np.newaxis] > 0,
    )
    _emit_progress("liquidity", "流动性容量计算完成", completed=P, total=P)
    return capacity
