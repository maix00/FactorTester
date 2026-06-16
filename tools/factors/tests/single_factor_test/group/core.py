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

from Settings import factor_info_path
from tools.data.types.DataColumn import DataColumn
from tools.data.types.DataCurrency import CurrencyConversionContext, normalize_currency, require_product_currency_vector
from tools.data.types.DataFreq import DataFreq
from tools.data.types.DataIndex import DataIndex
from tools.data.types.DataMoneyMinorUnits import minor_units_to_major, major_floor_to_minor_units, major_to_minor_units
from tools.factors import Factor
from tools.factors.Parameters import FactorNextPeriodReturns
from tools.factors.tests.NextReturns import NextReturns
from tools.factors.tests.single_factor_test.group.result import GroupRunResult
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
        except Exception:
            pass


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
        closetoday_ratio_mat=np.asarray(group_result.closetoday_ratio_mat).copy(),
        closetoday_fixed_mat=None if group_result.closetoday_fixed_mat is None else np.asarray(group_result.closetoday_fixed_mat).copy(),
        use_closetoday_vec=None if group_result.use_closetoday_vec is None else np.asarray(group_result.use_closetoday_vec).copy(),
        index_list=list(group_result.index_list),
        multi_session_active=bool(group_result.multi_session_active),
        rebalance_mode=str(group_result.rebalance_mode),
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
        multiplier_mat=None if group_result.multiplier_mat is None else np.asarray(group_result.multiplier_mat).copy(),
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

    if calendar_index is not None and len(calendar_index) > 0:
        common_index = pd.Index(calendar_index)
        signal_update_mask = common_index.isin(signal_index)
        table_src = table_src.reindex(common_index)
        returns_src = returns_src.reindex(common_index)
    else:
        common_index = signal_index
        signal_update_mask = np.ones(len(common_index), dtype=bool)

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
    if multi_session_active:
        after_head_missing = (~present_np) & (~head_missing)
        missing_cols = np.where(np.any(after_head_missing, axis=0))[0]
        missing_names = [str(signal_valid_cols[i]) for i in missing_cols]
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
    )


def _build_group_membership_from_shared(
    factor: Factor,
    shared: GroupSharedInputs,
    *,
    group_count: int,
    rebalance_mode: str,
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
    rebalance_mode: str,
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
                rebalance_mode=rebalance_mode,
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

    # ── Time-varying specs via date-range query (if index_list provided) ──
    db_time_specs: dict[str, pd.DataFrame] = {}
    if index_list is not None and len(index_list) > 0:
        _spec_field_names = (
            "multiplier", "min_tick", "min_trade_quantity", "long_margin_ratio",
            "open_ratio", "open_fixed", "close_ratio", "close_fixed",
            "closetoday_ratio", "closetoday_fixed",
        )
        try:
            from sources.OpenCTP.fields import get_products_specs_over_date_range
            db_time_specs = get_products_specs_over_date_range(
                products=list(valid_cols),
                trading_days=index_list,
                fields=list(_spec_field_names),
            )
        except Exception:
            db_time_specs = {}

    T = len(index_list) if index_list is not None else 1

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
    def _build_mat(field: str, per_product_defaults: list[float], default_fallback: float = 0.0) -> np.ndarray:
        """Build (T, P) matrix: prefer DB time-series, then per-product default as constant column, then scalar fallback."""
        df = db_time_specs.get(field)
        if df is not None and not df.empty:
            idx = pd.DatetimeIndex(index_list) if index_list is not None else pd.DatetimeIndex([])
            mat = df.reindex(index=idx).to_numpy(dtype=float)
            # Fill NaN with per-product defaults expanded to (T, P)
            defaults_arr = np.asarray(per_product_defaults, dtype=float).reshape(1, P)
            mask = np.isnan(mat)
            mat = np.where(mask, np.broadcast_to(defaults_arr, (T, P))[mask.any(axis=1, keepdims=True) * mask], mat)
            mat = np.nan_to_num(mat, nan=default_fallback)
            return mat
        else:
            return np.broadcast_to(np.asarray(per_product_defaults, dtype=float).reshape(1, P), (T, P)).copy()

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

    for gi, group in enumerate(groups):
        triple = group.triple_key
        base_membership = memberships_by_triple.get(triple)
        if base_membership is None:
            raise ValueError(f"Missing base membership for triple {triple}")
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
                'rebalance_mode': group.rebalance_mode,
                'liquidity_mode': group.liquidity_mode,
                'liquidity_percent': group.liquidity_percent,
                'margin_mode': group.margin_mode,
            })
        else:
            # Identity group: copy the row directly
            mask_1g = source_row[:, np.newaxis, :].copy()  # (T, 1, P)
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
                'rebalance_mode': group.rebalance_mode,
                'liquidity_mode': group.liquidity_mode,
                'liquidity_percent': group.liquidity_percent,
                'margin_mode': group.margin_mode,
            })
        _emit_progress("flat_membership", f"展开分组隶属度 {gi+1}/{len(groups)}",
                       completed=gi + 1, total=len(groups))

    membership_np = np.concatenate(slices, axis=1)  # (T, M_total, P)
    return membership_np, group_info


def _simulate_group_from_preloaded(
    factor: Factor,
    *,
    membership_np: np.ndarray,
    returns_filled: np.ndarray,
    price_np: np.ndarray,
    settlement_price_np: np.ndarray | None = None,
    settlement_bar_mask: np.ndarray | None = None,
    valid_cols: list,
    index_list: list,
    n_names: dict[int, str],
    group_configs: list[dict] | None = None,
    rebalance_mode: str,
    initial_capital: float,
    multi_session_active: bool,
    base_currency: str = "CNY",
    currency_conversion_fee_rate: float = 0.0,
    product_currency_vec: np.ndarray | list[str] | None = None,
    start_dt: Optional[Any] = None,  # DataTime
    end_dt: Optional[Any] = None,    # DataTime
    source_freq: DataFreq,
    spec_bundle: GroupTradeSpecBundle,
) -> tuple[Any, pd.DataFrame, np.ndarray, GroupRunResult]:
    liquidity_capacity_np: np.ndarray | None = None
    group_count = membership_np.shape[1]
    T_periods = len(index_list)
    P = len(valid_cols)
    base_currency = normalize_currency(base_currency)
    product_currency_vec = require_product_currency_vector(
        valid_cols,
        explicit=product_currency_vec,
        default=None,
    )

    # Unpack trade spec matrices from bundle
    open_ratio_mat = spec_bundle.open_ratio_mat
    close_ratio_mat = spec_bundle.close_ratio_mat
    closetoday_ratio_mat = spec_bundle.closetoday_ratio_mat
    open_fixed_mat = spec_bundle.open_fixed_mat
    close_fixed_mat = spec_bundle.close_fixed_mat
    closetoday_fixed_mat = spec_bundle.closetoday_fixed_mat
    use_closetoday_vec = spec_bundle.use_closetoday_vec
    is_margin_traded_vec = spec_bundle.is_margin_traded_vec
    positions_by_variety_code_lower = spec_bundle.positions_by_variety_code_lower

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

    _VALID_MODES = frozenset({"each_period", "buy_and_hold", "recycle"})

    liquidity_modes_list = ["infinite"] * group_count
    liquidity_percents_list = [100.0] * group_count
    margin_modes_list = ["margin"] * group_count
    rebalance_modes_list = [rebalance_mode] * group_count

    # Apply per-group configs (all groups treated uniformly)
    _group_configs = group_configs or []
    for g_idx, cfg in enumerate(_group_configs):
        if not isinstance(cfg, dict) or g_idx >= group_count:
            continue
        liquidity_modes_list[g_idx] = _liquidity_mode_from_spec(cfg)
        liquidity_percents_list[g_idx] = _liquidity_percent_from_spec(cfg)
        margin_modes_list[g_idx] = str(cfg.get('margin_mode') or cfg.get('marginMode') or "margin")
        drm = str(cfg.get('rebalance_mode') or cfg.get('rebalanceMode') or rebalance_mode)
        if drm in _VALID_MODES:
            rebalance_modes_list[g_idx] = drm

    # Fee matrices from spec_bundle are (T, P). Per-group fee overrides are applied
    # inside simulate_group_trading_book via group_configs.
    # Build effective close matrices using use_closetoday_vec — broadcast across time.
    use_closetoday_brd = use_closetoday_vec[np.newaxis, :]  # (1, P)
    effective_open_ratio_mat = open_ratio_mat  # (T, P)
    effective_open_fixed_mat = open_fixed_mat  # (T, P)
    effective_close_ratio_mat = np.where(use_closetoday_brd, closetoday_ratio_mat, close_ratio_mat)
    effective_close_fixed_mat = np.where(use_closetoday_brd, closetoday_fixed_mat, close_fixed_mat)

    group_liquidity_modes = liquidity_modes_list
    group_liquidity_percents = liquidity_percents_list
    group_margin_modes = margin_modes_list

    if any(str(mode) == "percent" for mode in group_liquidity_modes):
        liquidity_capacity_np = _build_normalized_liquidity_capacity(valid_cols, index_list, source_freq, start_dt, end_dt)

    # products_by_group built lazily by GroupRunResult.get_products_by_group()
    member_counts = membership_np.sum(axis=2).astype(float)
    if rebalance_mode not in _VALID_MODES:
        raise ValueError(f"rebalance_mode must be one of {sorted(_VALID_MODES)}, got {rebalance_mode!r}")
    trade_present_np = np.isfinite(price_np) & (price_np > 0)
    data_has_bar = trade_present_np if np.any(~trade_present_np) else None
    _emit_progress("simulate", "开始模拟", completed=0, total=1)
    sim_result = simulate_group_trading_book(
        membership_np=membership_np,
        returns_np=returns_filled,
        price_np=price_np,
        settlement_price_np=settlement_price_np,
        settlement_bar_mask=settlement_bar_mask,
        open_rate_mat=effective_open_ratio_mat,
        close_rate_mat=effective_close_ratio_mat,
        open_fixed_mat=effective_open_fixed_mat,
        close_fixed_mat=effective_close_fixed_mat,
        tradable_mask_np=data_has_bar,
        liquidity_capacity_np=liquidity_capacity_np,
        liquidity_modes=group_liquidity_modes if group_liquidity_modes else None,
        liquidity_percents=group_liquidity_percents if group_liquidity_percents else None,
        trade_specs=spec_bundle,
        group_configs=_group_configs,
        margin_modes=group_margin_modes,
        rebalance_modes=np.asarray(rebalance_modes_list, dtype=object),
        initial_capital=initial_capital,
        base_currency=base_currency,
        product_currency_vec=product_currency_vec,
        currency_conversion_fee_rate=currency_conversion_fee_rate,
        time_index=index_list,
    )
    _emit_progress("simulate", "模拟完成", completed=1, total=1)
    group_returns_np = sim_result['net_returns_np']
    group_gross_returns_np = sim_result['gross_returns_np']
    group_product_gross_contrib_np = sim_result['product_gross_contrib_np']
    group_product_fee_contrib_np = sim_result['product_fee_contrib_np']
    fee_costs_np = sim_result['fee_costs_np']
    trade_notional_ratio_np = sim_result['trade_notional_ratio_np']
    multi_session_triggered_count = sim_result['multi_session_triggered']
    if multi_session_active:
        print(f"[WARN] {factor.alias}: 多时段品种策略在 {multi_session_triggered_count}/{len(index_list)} 期中触发。")
    avg_turnover = np.zeros(group_count, dtype=float)
    if len(index_list) > 1:
        transition_counts = (member_counts[1:] + member_counts[:-1]) / 2.0
        turnover_valid = transition_counts > 0
        changed = np.logical_xor(membership_np[1:], membership_np[:-1]).sum(axis=2) / 2.0
        turnover_ratio = np.divide(changed, transition_counts, out=np.zeros_like(changed, dtype=float), where=turnover_valid)
        turnover_observations = turnover_valid.sum(axis=0)
        avg_turnover = np.divide(turnover_ratio.sum(axis=0), turnover_observations, out=np.zeros(group_count, dtype=float), where=turnover_observations > 0)
    signal_times = pd.DatetimeIndex(index_list)
    mask_report = np.ones(len(index_list), dtype=bool)
    mask_report &= DataIndex(signal_times).slice_by_datatime(start_dt, end_dt)
    report_groups = {}
    annual_periods = infer_periods_per_year(index_list)
    for idx in range(group_count):
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
            return dict(total_ret=total_ret, annual_ret=annual_ret, vol=vol, sharpe=sharpe, dd=dd, calmar=calmar, win_rate=win_rate, mean_ret=s.mean() * 100, skew=s.skew(), kurt=s.kurtosis())
        m = _metrics(r)
        report_groups[idx] = pd.Series({
            "Total Return": m["total_ret"], "Annual Return": m["annual_ret"], "Volatility": m["vol"],
            "Sharpe Ratio": m["sharpe"], "Max Drawdown": m["dd"], "Calmar Ratio": m["calmar"],
            "Win Rate": m["win_rate"], "Mean Return": m["mean_ret"], "Skewness": m["skew"],
            "Kurtosis": m["kurt"], "Avg Turnover": avg_turnover[idx],
        })
    report_df = pd.DataFrame(report_groups).T.sort_index()
    group_result = cast(Any, GroupRunResult)(
        fee_costs_np=fee_costs_np,
        trade_notional_ratio_np=trade_notional_ratio_np,
        gross_returns_np=group_gross_returns_np,
        product_gross_contrib_np=group_product_gross_contrib_np,
        product_fee_contrib_np=group_product_fee_contrib_np,
        returns_np=group_returns_np,
        period_returns_np=returns_filled,
        membership_np=membership_np,
        products_by_group=None,  # lazily built by get_products_by_group()
        valid_cols=valid_cols,
        open_ratio_mat=open_ratio_mat,
        close_ratio_mat=close_ratio_mat,
        closetoday_ratio_mat=closetoday_ratio_mat,
        index_list=index_list,
        multi_session_active=multi_session_active,
        rebalance_mode=rebalance_mode,
        report_df=report_df.copy(),
        group_names=n_names,
        hold_amounts_np=sim_result.get('target_amounts_np'),
        target_amounts_before_floor_np=sim_result.get('target_amounts_before_floor_np'),
        position_quantities_np=sim_result.get('position_quantities_np'),
        prev_end_amounts_np=sim_result.get('prev_end_amounts_np'),
        margin_occupied_np=sim_result.get('margin_occupied_np'),
        pre_rebalance_total_equity_np=sim_result.get('pre_rebalance_total_equity_np'),
        post_rebalance_total_equity_np=sim_result.get('post_rebalance_total_equity_np'),
        total_equity_np=sim_result.get('total_equity_np'),
        pre_rebalance_cash_np=sim_result.get('pre_rebalance_cash_np'),
        post_rebalance_cash_np=sim_result.get('post_rebalance_cash_np'),
        post_settlement_cash_np=sim_result.get('post_settlement_cash_np'),
        cash_np=sim_result.get('cash_np'),
        buy_fee_amount_np=sim_result.get('buy_fee_amount_np'),
        sell_fee_amount_np=sim_result.get('sell_fee_amount_np'),
        initial_capital=float(initial_capital),
        price_np=price_np,
        open_fixed_mat=open_fixed_mat,
        close_fixed_mat=close_fixed_mat,
        closetoday_fixed_mat=closetoday_fixed_mat,
        multiplier_mat=spec_bundle.multiplier_mat,
        min_tick_mat=spec_bundle.min_tick_mat,
        min_trade_quantity_mat=spec_bundle.min_trade_quantity_mat,
        margin_ratio_mat=spec_bundle.long_margin_ratio_mat,
        is_margin_traded_vec=is_margin_traded_vec,
        use_closetoday_vec=use_closetoday_vec,
        base_currency=base_currency,
        product_currency_vec=np.asarray(product_currency_vec, dtype=object),
        currency_conversion_fee_rate=float(currency_conversion_fee_rate or 0.0),
        liquidity_capacity_np=liquidity_capacity_np,
        liquidity_modes=list(group_liquidity_modes) if group_liquidity_modes is not None else None,
        liquidity_percents=list(group_liquidity_percents) if group_liquidity_percents is not None else None,
        one_lot_margin_np=sim_result.get('one_lot_margin_np'),
        one_lot_fee_np=sim_result.get('one_lot_fee_np'),
    )
    returns_dict, report_df_out, cumulative_returns_np, _ = materialize_group_outputs_from_result(group_result)
    return returns_dict, report_df_out, cumulative_returns_np, group_result



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
    notional in each period. They are converted to absolute notional capacity
    inside `simulate_group_trading_book` by multiplying by the current group
    equity and the user-specified ``liquidity_percent``.

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


def build_target_amounts(
    curr_mask_all: np.ndarray,
    prev_end_amounts: np.ndarray,
    wealth_before_trade: np.ndarray,
    rebalance_mode: str,
    close_fee_vec: np.ndarray | None = None,
    close_fee_already_paid: bool = False,
    margin_factor: np.ndarray | None = None,
) -> np.ndarray:
    """Build next-period target holdings for all groups with vectorized operations.

    Parameters
    ----------
    close_fee_vec : (P,) or (group_count, P) array of per-product close fee rates.
        Accepts 1-D (P,) for backward compatibility and broadcasts to group_count.
        When provided, the capital released from exits is reduced by the
        proportional close fee before being allocated to entering products.
    close_fee_already_paid : bool
        For each-period full rebalancing, treat ``wealth_before_trade`` as the
        post-sell-fee available wealth.  This is used by the simulator after it
        has computed the sell leg first.
    margin_factor : (M, P) or None
        Per-product capital multiplier (default 1.0). For margin-traded products
        this equals the margin ratio; for cash products it is 1.0.
        Used to compute the actual capital released on exits:
        - 保证金产品：卖出只释放保证金部分（sell * margin_ratio），
          因为大部分名义值是借来的钱，不能作为可用资金
        - 现金产品：卖出释放全额名义值（sell * 1.0）
    """
    curr_mask = np.asarray(curr_mask_all, dtype=bool)
    prev_amounts = np.asarray(prev_end_amounts, dtype=float)
    wealth = np.asarray(wealth_before_trade, dtype=float)
    close_fees = np.asarray(close_fee_vec, dtype=float) if close_fee_vec is not None else None
    if close_fees is not None and close_fees.ndim == 1:
        close_fees = close_fees[np.newaxis, :]  # (1, P) → broadcast to (group_count, P)
    mf = (
        np.asarray(margin_factor, dtype=float)
        if margin_factor is not None
        else np.ones_like(prev_amounts, dtype=float)
    )

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

    counts = np.nansum(curr_mask, axis=1).astype(float)
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
    n_entering = np.nansum(entering, axis=1).astype(float)
    # 卖出释放的资金 = 保证金解冻部分（保证金产品）或全额名义值（现金产品）。
    # 保证金产品：only margin_ratio * notional is freed（借款部分不能动用）
    # 现金产品：full notional is freed（margin_factor = 1.0）
    sell_amounts = np.nansum(prev_amounts * exiting.astype(float) * mf, axis=1)

    # Subtract close fee from released capital — the actual cash available
    # after selling is sell_amounts * (1 - close_fee) per exiting product.
    if close_fees is not None:
        sell_fees = np.nansum(prev_amounts * exiting.astype(float) * close_fees, axis=1)
        released = np.maximum(0.0, sell_amounts - sell_fees)
    else:
        released = sell_amounts

    # Staying positions keep their nominal amounts (targets are nominal)
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

    totals = np.nansum(targets, axis=1)
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

    close_fee_vec accepts (P,) for backward compat and broadcasts to group_count.
    """
    curr_mask = np.asarray(curr_mask_all, dtype=bool)
    prev_amounts = np.asarray(prev_end_amounts, dtype=float)
    wealth = np.asarray(wealth_before_trade, dtype=float)
    has_bar_vec = np.asarray(has_bar, dtype=bool)
    close_fees = np.asarray(close_fee_vec, dtype=float)
    if close_fees.ndim == 1:
        close_fees = close_fees[np.newaxis, :]  # (1, P) → broadcast

    def _equal_alloc(mask: np.ndarray, capital: np.ndarray) -> np.ndarray:
        counts_local = np.nansum(mask, axis=1).astype(float)
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
        np.nansum(sell_amounts, axis=1) - np.nansum(sell_amounts * close_fees, axis=1),
    )
    entering_counts = np.nansum(entering_with_bar, axis=1).astype(float)

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
    use_margin: np.ndarray | None = None,
    margin_ratios: np.ndarray | None = None,
) -> np.ndarray:
    """Convert ideal targets to executable targets under per-product notional caps.

    Capacity is expressed in the same normalized notional unit as wealth
    (initial wealth = 1).  Sells are capped first; remaining cash funds buys
    by executable capacity weights, so unfilled cash stays idle.

    When ``use_margin`` and ``margin_ratios`` are provided (both (M, P)
    arrays), the cash calculation accounts for margin-occupied capital:
    - cash_before = wealth - sum(prev * margin_factor)
    - buy cash needed = sum(buy * margin_factor) + sum(buy * open_fee)
    (保证金和手续费是分开独立的：保证金=名义值×保证金比例，手续费=名义值×费率+固定费用)
    where margin_factor = margin_ratio if use_margin else 1.0.
    """
    prev = np.asarray(prev_end_amounts, dtype=float)
    ideal = np.asarray(ideal_target_amounts, dtype=float)
    wealth = np.asarray(wealth_before_trade, dtype=float)
    caps = np.asarray(capacity_amounts, dtype=float)
    if caps.ndim == 1:
        caps = caps[np.newaxis, :]
    caps = np.where(np.isfinite(caps) & (caps >= 0), caps, np.inf)

    use_m = (
        np.asarray(use_margin, dtype=bool)
        if use_margin is not None
        else np.zeros_like(prev, dtype=bool)
    )
    mr = (
        np.asarray(margin_ratios, dtype=float)
        if margin_ratios is not None
        else np.ones_like(prev, dtype=float)
    )
    margin_factor = np.where(use_m, mr, 1.0)  # (M, P)

    delta = ideal - prev
    desired_sell = np.clip(-delta, 0.0, None)
    desired_buy = np.clip(delta, 0.0, None)

    sell_exec = np.minimum(desired_sell, caps)
    after_sell = prev - sell_exec
    sell_fee = np.nansum(sell_exec * close_fee_mat, axis=1)
    # cash_before: actual free cash accounting for margin-occupied positions
    prev_occupied = np.nansum(prev * margin_factor, axis=1)
    cash_before = np.maximum(0.0, wealth - prev_occupied)
    cash_after_sell = np.maximum(0.0, cash_before + np.nansum(sell_exec * margin_factor, axis=1) - sell_fee)

    buy_capacity = np.minimum(desired_buy, caps)
    buy_capacity = np.where(np.isfinite(buy_capacity) & (buy_capacity > 0), buy_capacity, 0.0)
    buy_capacity_sum = np.nansum(buy_capacity, axis=1)
    buy_budget = np.minimum(cash_after_sell, buy_capacity_sum)

    buy_exec = np.zeros_like(prev, dtype=float)
    rows = buy_capacity_sum > 0
    if rows.any():
        buy_exec[rows] = buy_capacity[rows] * (buy_budget[rows] / buy_capacity_sum[rows])[:, np.newaxis]

    # Do not allow open fees + margin to push cash negative.  The cash required
    # to buy one unit of notional is margin_factor (保证金占用) + open_fee (手续费).
    # 这两个是分开独立的：保证金=名义值×保证金比例，手续费=名义值×费率+固定费用
    buy_cash_need = (
        np.nansum(buy_exec * margin_factor, axis=1)
        + np.nansum(buy_exec * open_fee_mat, axis=1)
    )
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


def simulate_group_trading_book(
    membership_np: np.ndarray,
    returns_np: np.ndarray,
    price_np: np.ndarray,
    open_rate_mat: np.ndarray,
    close_rate_mat: np.ndarray,
    *,
    settlement_price_np: np.ndarray | None = None,
    open_fixed_mat: np.ndarray,
    close_fixed_mat: np.ndarray,
    tradable_mask_np: np.ndarray | None = None,
    liquidity_capacity_np: np.ndarray | None = None,
    liquidity_modes: np.ndarray | list[str] | None = None,
    liquidity_percents: np.ndarray | list[float] | None = None,
    trade_specs: GroupTradeSpecBundle,
    group_configs: list | None = None,
    margin_modes: np.ndarray | list[str],
    rebalance_modes: np.ndarray | list[str],
    initial_capital: float = 100000000.0,
    base_currency: str = "CNY",
    product_currency_vec: np.ndarray | list[str] | None = None,
    currency_conversion_fee_rate: float = 0.0,
    time_index: list | None = None,
    settlement_bar_mask: np.ndarray | None = None,
) -> dict:
    """Simulate grouped trading with quantities, fees, cash, margin, and per-period tradability."""
    T, M, P = membership_np.shape
    prices = np.asarray(price_np, dtype=float)
    if prices.shape != (T, P):
        raise ValueError(f"price_np shape={prices.shape} != {(T, P)}")
    tradable_mask_arr = None if tradable_mask_np is None else np.asarray(tradable_mask_np, dtype=bool)
    if tradable_mask_arr is not None and tradable_mask_arr.shape != (T, P):
        raise ValueError(f"tradable_mask_np shape={tradable_mask_arr.shape} != {(T, P)}")

    # Unpack trade_specs: all (T, P) mat fields + (P,) vec fields
    multiplier_mat_arr = np.asarray(trade_specs.multiplier_mat, dtype=float)
    if multiplier_mat_arr.shape != (T, P):
        raise ValueError(f"multiplier_mat shape={multiplier_mat_arr.shape} != {(T, P)}")
    multiplier_mat_arr = np.where(np.isfinite(multiplier_mat_arr) & (multiplier_mat_arr > 0), multiplier_mat_arr, 1.0)
    min_tick_mat_arr = np.asarray(trade_specs.min_tick_mat, dtype=float)
    if min_tick_mat_arr.shape != (T, P):
        raise ValueError(f"min_tick_mat shape={min_tick_mat_arr.shape} != {(T, P)}")
    min_trade_qty_mat_arr = np.asarray(trade_specs.min_trade_quantity_mat, dtype=float)
    if min_trade_qty_mat_arr.shape != (T, P):
        raise ValueError(f"min_trade_quantity_mat shape={min_trade_qty_mat_arr.shape} != {(T, P)}")
    min_trade_qty_mat_arr = np.where(np.isfinite(min_trade_qty_mat_arr) & (min_trade_qty_mat_arr > 0), min_trade_qty_mat_arr, 1.0)
    margin_flags = np.asarray(trade_specs.is_margin_traded_vec, dtype=bool).reshape(P)
    margin_modes_arr = np.asarray(margin_modes, dtype=object)
    rebalance_modes_arr = np.asarray(rebalance_modes, dtype=object)
    if margin_modes_arr.shape[0] != M:
        raise ValueError(f"margin_modes length={margin_modes_arr.shape[0]} != groups={M}")
    if rebalance_modes_arr.shape[0] != M:
        raise ValueError(f"rebalance_modes length={rebalance_modes_arr.shape[0]} != groups={M}")

    close_rate_mat_arr = np.asarray(close_rate_mat, dtype=float)
    if close_rate_mat_arr.shape != (T, P):
        raise ValueError(f"close_rate_mat shape={close_rate_mat_arr.shape} != {(T, P)}")
    close_fixed_mat_arr = np.asarray(close_fixed_mat, dtype=float)
    if close_fixed_mat_arr.shape != (T, P):
        raise ValueError(f"close_fixed_mat shape={close_fixed_mat_arr.shape} != {(T, P)}")
    open_rate_mat_arr = np.asarray(open_rate_mat, dtype=float)
    if open_rate_mat_arr.shape != (T, P):
        raise ValueError(f"open_rate_mat shape={open_rate_mat_arr.shape} != {(T, P)}")
    open_fixed_mat_arr = np.asarray(open_fixed_mat, dtype=float)
    if open_fixed_mat_arr.shape != (T, P):
        raise ValueError(f"open_fixed_mat shape={open_fixed_mat_arr.shape} != {(T, P)}")
    margin_ratios = np.asarray(trade_specs.long_margin_ratio_mat, dtype=float)
    if margin_ratios.shape != (T, P):
        raise ValueError(f"long_margin_ratio_mat shape={margin_ratios.shape} != {(T, P)}")
    margin_ratios = np.where(np.isfinite(margin_ratios) & (margin_ratios > 0), margin_ratios, 1.0)
    liquidity_modes_arr = np.asarray(liquidity_modes, dtype=object) if liquidity_modes is not None else np.full(M, "infinite", dtype=object)
    liquidity_percents_arr = np.asarray(liquidity_percents, dtype=float) if liquidity_percents is not None else np.full(M, 100.0, dtype=float)
    liquidity_capacity_arr = np.asarray(liquidity_capacity_np, dtype=float) if liquidity_capacity_np is not None else None
    if liquidity_capacity_arr is not None and liquidity_capacity_arr.shape != (T, P):
        raise ValueError(
            f"liquidity_capacity_np shape={liquidity_capacity_arr.shape} != {(T, P)}"
        )
    use_margin = (margin_modes_arr == "margin")[:, np.newaxis] & margin_flags[np.newaxis, :]
    hold_rows = np.isin(rebalance_modes_arr, ["buy_and_hold", "recycle"])
    recycle_rows = rebalance_modes_arr == "recycle"
    percent_rows = liquidity_modes_arr == "percent"
    has_percent_liquidity = liquidity_capacity_arr is not None and bool(percent_rows.any())
    percent_scale = np.clip(liquidity_percents_arr, 0.0, 100.0) / 100.0
    base_currency = normalize_currency(base_currency)
    product_currency_arr = require_product_currency_vector(
        list(range(P)),
        explicit=product_currency_vec,
        default=None,
    )
    currency_context = CurrencyConversionContext(
        base_currency=base_currency,
        conversion_fee_rate=currency_conversion_fee_rate,
    )
    currency_conversion_fee_rate = currency_context.conversion_fee_rate
    time_index = list(time_index) if time_index is not None else list(range(T))

    net_returns_np = np.zeros((T, M), dtype=float)
    gross_returns_np = np.zeros((T, M), dtype=float)
    product_gross_contrib_np = np.zeros((T, M, P), dtype=float)
    product_fee_contrib_np = np.zeros((T, M, P), dtype=float)
    fee_costs_np = np.zeros((T, M), dtype=float)
    trade_notional_ratio_np = np.zeros((T, M), dtype=float)
    target_amounts_np = np.zeros((T, M, P), dtype=np.int64)
    target_amounts_before_floor_np = np.zeros((T, M, P), dtype=np.int64)
    prev_end_amounts_np = np.zeros((T, M, P), dtype=np.int64)
    position_quantities_np = np.zeros((T, M, P), dtype=float)
    margin_occupied_np = np.zeros((T, M), dtype=np.int64)
    pre_rebalance_total_equity_np = np.zeros((T, M), dtype=np.int64)
    post_rebalance_total_equity_np = np.zeros((T, M), dtype=np.int64)
    total_equity_np = np.zeros((T, M), dtype=np.int64)
    pre_rebalance_cash_np = np.zeros((T, M), dtype=np.int64)
    post_rebalance_cash_np = np.zeros((T, M), dtype=np.int64)
    post_settlement_cash_np = np.full((T, M), np.nan, dtype=float)
    cash_np = np.zeros((T, M), dtype=np.int64)
    buy_fee_amount_np = np.zeros((T, M), dtype=np.int64)
    sell_fee_amount_np = np.zeros((T, M), dtype=np.int64)
    liquidity_capacity_amounts_np = np.zeros((T, M, P), dtype=float)
    one_lot_margin_np = np.zeros((T, M, P), dtype=float)
    one_lot_fee_np = np.zeros((T, M, P), dtype=float)

    if not np.isfinite(initial_capital) or initial_capital <= 0:
        raise ValueError(f"initial_capital must be positive, got {initial_capital!r}")

    def _floor_minor_units(value: Any) -> np.ndarray:
        return major_floor_to_minor_units(value)

    def _round_minor_units(value: Any) -> np.ndarray:
        return major_to_minor_units(value)

    def _from_minor_units(minor_units: Any) -> np.ndarray:
        return minor_units_to_major(minor_units)

    equity = np.full(M, float(_from_minor_units(_round_minor_units(initial_capital))), dtype=float)
    quantities = np.zeros((M, P), dtype=float)
    prev_post_rebalance_total = equity.copy()
    prev_post_rebalance_cash = equity.copy()

    def _round_price(raw_price: np.ndarray, min_ticks_t: np.ndarray) -> np.ndarray:
        px = np.asarray(raw_price, dtype=float)
        valid_tick = np.isfinite(min_ticks_t) & (min_ticks_t > 0)
        rounded = px.copy()
        rounded[valid_tick] = np.round(px[valid_tick] / min_ticks_t[valid_tick]) * min_ticks_t[valid_tick]
        # Fallback: round to 2 decimal places for products without min_tick
        no_tick = np.isfinite(px) & (~valid_tick)
        if no_tick.any():
            rounded[no_tick] = np.round(px[no_tick], 2)
        return np.where(np.isfinite(rounded) & (rounded > 0), rounded, np.nan)

    settlement_price_arr = None
    if settlement_price_np is not None:
        settlement_price_arr = np.asarray(settlement_price_np, dtype=float)
        if settlement_price_arr.shape != (T, P):
            raise ValueError(f"settlement_price_np shape={settlement_price_arr.shape} != {(T, P)}")
    if settlement_bar_mask is not None:
        settlement_bar_mask = np.asarray(settlement_bar_mask, dtype=bool)
        if settlement_bar_mask.ndim == 1:
            settlement_bar_mask = np.broadcast_to(settlement_bar_mask.reshape(T, 1), (T, P))
        elif settlement_bar_mask.shape != (T, P):
            raise ValueError(f"settlement_bar_mask shape={settlement_bar_mask.shape} != {(T, P)}")
    else:
        settlement_bar_mask = np.broadcast_to(
            DataIndex(pd.Index(time_index)).end_of_trading_day().reshape(T, 1),
            (T, P),
        )

    lot_books = [[deque() for _ in range(P)] for _ in range(M)]

    def _contract_value_base_from_price(price_row: np.ndarray, valuated_mask: np.ndarray, *, ts: Any, multipliers_t: np.ndarray) -> np.ndarray:
        contract_value = np.asarray(price_row, dtype=float) * multipliers_t
        contract_value = np.where(valuated_mask & np.isfinite(contract_value) & (contract_value > 0), contract_value, np.nan)
        contract_value_base = contract_value.copy()
        for p_idx in range(P):
            contract_value_base[p_idx] = float(
                currency_context.to_base(contract_value[p_idx], product_currency_arr[p_idx], ts)
            )
        return contract_value_base

    def _lot_push(row_idx: int, p_idx: int, qty: float, mark_base: float) -> None:
        if qty <= 0 or not np.isfinite(mark_base) or mark_base <= 0:
            return
        lot_books[row_idx][p_idx].append([float(qty), float(mark_base)])

    def _lot_realize_sell(row_idx: int, p_idx: int, sell_qty: float, sell_base: float) -> float:
        if sell_qty <= 0 or not np.isfinite(sell_base) or sell_base <= 0:
            return 0.0
        realized = 0.0
        remaining = float(sell_qty)
        book = lot_books[row_idx][p_idx]
        while remaining > 1e-12 and book:
            lot_qty, lot_base = book[0]
            take = min(float(lot_qty), remaining)
            realized += take * (sell_base - float(lot_base))
            lot_qty -= take
            remaining -= take
            if lot_qty <= 1e-12:
                book.popleft()
            else:
                book[0][0] = float(lot_qty)
        return realized

    def _lot_margin_occupied(row_idx: int, p_idx: int, *, mark_base: float | None = None) -> float:
        total = 0.0
        for lot_qty, lot_base in lot_books[row_idx][p_idx]:
            base = float(lot_base if mark_base is None else mark_base)
            if not np.isfinite(base) or base <= 0:
                continue
            ratio = float(margin_ratios_t[p_idx]) if use_margin[row_idx, p_idx] else 1.0
            total += float(lot_qty) * base * ratio
        return total

    def _mark_lots_to_price(row_idx: int, p_idx: int, price_base: float) -> float:
        if not np.isfinite(price_base) or price_base <= 0:
            return 0.0
        realized = 0.0
        book = lot_books[row_idx][p_idx]
        for lot in book:
            realized += float(lot[0]) * (price_base - float(lot[1]))
            lot[1] = float(price_base)
        return realized

    _emit_progress("simulate", f"开始交易账本模拟，时间点 {T} 个", completed=0, total=T)
    _last_sim_report = -1
    for t in tqdm(range(T), desc="Trading book simulation"):
        # 每 2% 发射一次进度（避免过于频繁的 SSE 推送）
        pct = int(t / max(T, 1) * 50)  # 0..50
        if pct > _last_sim_report or t == T - 1:
            _last_sim_report = pct
            _emit_progress("simulate", f"交易账本模拟 {t+1}/{T}", completed=t + 1, total=T)
        # Per-period trade specs (P,)
        multipliers_t = multiplier_mat_arr[t]
        min_ticks_t = min_tick_mat_arr[t]
        lot_sizes_t = min_trade_qty_mat_arr[t]
        margin_ratios_t = margin_ratios[t]
        open_rate_t = open_rate_mat_arr[t]
        close_rate_t = close_rate_mat_arr[t]
        open_fixed_t = open_fixed_mat_arr[t]
        close_fixed_t = close_fixed_mat_arr[t]

        # Default: post-rebalance cash starts as previous period's post-rebalance cash.
        # Will be updated if settlement or rebalance happens.
        post_rebalance_cash = prev_post_rebalance_cash.copy()

        # Apply per-group fee overrides: build (M, P) rate matrices for this period
        open_rate_by_group = np.tile(open_rate_t, (M, 1))          # (M, P)
        close_rate_by_group = np.tile(close_rate_t, (M, 1))
        open_fixed_by_group = np.tile(open_fixed_t, (M, 1))
        close_fixed_by_group = np.tile(close_fixed_t, (M, 1))
        group_cfgs = group_configs or []
        for g_idx, cfg in enumerate(group_cfgs):
            if g_idx >= M or not isinstance(cfg, dict):
                continue
            fee_ov = cfg.get("fee_override")
            if not isinstance(fee_ov, dict):
                continue
            if 'open' in fee_ov and fee_ov['open'] is not None:
                open_rate_by_group[g_idx, :] = float(fee_ov['open'])
            if 'close' in fee_ov and fee_ov['close'] is not None:
                close_ov = float(fee_ov['close'])
                close_rate_by_group[g_idx, :] = close_ov
            if 'close_today' in fee_ov and fee_ov['close_today'] is not None:
                close_rate_by_group[g_idx, :] = float(fee_ov['close_today'])

        price_t = _round_price(prices[t], min_ticks_t)
        valuated = np.isfinite(price_t) & (price_t > 0)
        executable = valuated if tradable_mask_arr is None else (valuated & tradable_mask_arr[t])
        executable_row = executable[np.newaxis, :]
        contract_value = price_t * multipliers_t
        contract_value = np.where(valuated & np.isfinite(contract_value) & (contract_value > 0), contract_value, np.nan)
        contract_value_base = contract_value.copy()
        for p_idx in range(P):
            contract_value_base[p_idx] = float(currency_context.to_base(contract_value[p_idx], product_currency_arr[p_idx], time_index[t]))
        contract_value_row = contract_value[np.newaxis, :]
        contract_value_base_row = contract_value_base[np.newaxis, :]
        lot_row = lot_sizes_t.copy()
        lot_row = np.where(np.isfinite(lot_row) & (lot_row > 0), lot_row, 1.0)
        contract_value_minor_units = _round_minor_units(contract_value_base)
        settlement_bar_row = settlement_bar_mask[t] if t < len(settlement_bar_mask) else np.zeros(P, dtype=bool)
        if settlement_price_arr is not None and bool(np.any(settlement_bar_row)):
            raw_settlement_price = np.asarray(settlement_price_arr[t], dtype=float)
            valid_settlement = settlement_bar_row & np.isfinite(raw_settlement_price) & (raw_settlement_price > 0)
            if bool(np.any(valid_settlement)):
                settlement_value_base = _contract_value_base_from_price(
                    raw_settlement_price,
                    valid_settlement,
                    ts=time_index[t],
                    multipliers_t=multipliers_t,
                )
                pre_rebalance_cash_before_settlement = (
                    _from_minor_units(
                        _round_minor_units(
                            equity
                            - np.nansum(
                                np.where(
                                    use_margin,
                                    quantities * contract_value_base_row * margin_ratios_t,
                                    quantities * contract_value_base_row,
                                ),
                                axis=1,
                            )
                        )
                    )
                    if t == 0
                    else _from_minor_units(
                        _round_minor_units(
                            prev_post_rebalance_cash
                            + (equity - prev_post_rebalance_total)
                        )
                    )
                )
                settlement_pnl = np.zeros(M, dtype=float)
                settlement_margin_delta = np.zeros(M, dtype=float)
                settlement_touched = np.zeros(M, dtype=bool)
                for row_idx in range(M):
                    for p_idx in range(P):
                        if not valid_settlement[p_idx] or not use_margin[row_idx, p_idx]:
                            continue
                        if quantities[row_idx, p_idx] <= 0:
                            continue
                        old_occupied = _lot_margin_occupied(row_idx, p_idx)
                        pnl_here = _mark_lots_to_price(row_idx, p_idx, float(settlement_value_base[p_idx]))
                        new_occupied = _lot_margin_occupied(row_idx, p_idx, mark_base=float(settlement_value_base[p_idx]))
                        settlement_pnl[row_idx] += pnl_here
                        settlement_margin_delta[row_idx] += new_occupied - old_occupied
                        settlement_touched[row_idx] = True
                if bool(np.any(settlement_touched)):
                    settlement_cash = pre_rebalance_cash_before_settlement + settlement_pnl - settlement_margin_delta
                    post_settlement_cash_np[t, settlement_touched] = _round_minor_units(settlement_cash[settlement_touched])
                    equity = _from_minor_units(_round_minor_units(equity + settlement_pnl))
                    post_rebalance_cash = settlement_cash.copy()
                    prev_post_rebalance_cash = settlement_cash
                    prev_post_rebalance_total = equity.copy()
        one_lot_margin_mat = np.where(
            use_margin,
            lot_row * contract_value_base * margin_ratios_t,
            lot_row * contract_value_base,
        )
        one_lot_margin_display_mat = one_lot_margin_mat
        one_lot_fee_display_mat = lot_row * contract_value * open_rate_by_group + lot_row * open_fixed_by_group
        prev_notional = np.where(executable_row, quantities * contract_value_base_row, 0.0)
        pre_rebalance_total = equity.copy()
        pre_rebalance_occupied = np.where(
            use_margin,
            prev_notional * margin_ratios_t,
            prev_notional,
        )
        # 如果本期未调仓 (membership_unchanged)，沿用上期调仓后现金
        # pre_rebalance_cash 继承自上期 post_rebalance_cash
        if t == 0:
            pre_rebalance_cash = _from_minor_units(
                _round_minor_units(equity - np.nansum(pre_rebalance_occupied, axis=1))
            )
        else:
            # 现金延续 = 上期调仓后现金 + 期间总资产变动
            # 持仓保证金在期间锁定不变，只有 equity 随市价波动
            pre_rebalance_cash = _from_minor_units(
                _round_minor_units(
                    post_rebalance_cash
                    + (equity - prev_post_rebalance_total)
                )
            )

        # When membership is unchanged AND we are not in "each_period" mode
        # (which requires per-period re-weighting), skip rebalancing entirely.
        # Positions stay the same, fees are zero, only mark-to-market (equity
        # update via gross_contrib) still runs below.
        #
        # This is especially important for forward-filled rows (when
        # calendar_index unifies T across factors) where membership_np[t] is
        # explicitly set to membership_np[t-1] by _build_group_membership_from_shared.
        membership_unchanged = (
            t > 0
            and not np.any(rebalance_modes_arr == "each_period")
            and bool(np.array_equal(membership_np[t], membership_np[t-1]))
        )
        if membership_unchanged:
            desired_quantities = quantities.copy()
            target_amounts_before_floor = desired_quantities * contract_value_row
            continuous_quantities = desired_quantities.copy()
            buy_qty = np.zeros((M, P), dtype=float)
            sell_qty = np.zeros((M, P), dtype=float)
            buy_notional = np.zeros((M, P), dtype=float)
            sell_notional = np.zeros((M, P), dtype=float)
            buy_fee = np.zeros((M, P), dtype=float)
            sell_fee = np.zeros((M, P), dtype=float)
            fee_amount = np.zeros((M, P), dtype=float)
            position_notional = desired_quantities * contract_value_row
            liquidity_capacity_amounts_np[t] = np.full((M, P), np.inf, dtype=float)
        else:
            # ── 可执行品种 ──
            executable_capacity_t = np.full((M, P), np.inf, dtype=float)
            if has_percent_liquidity:
                assert liquidity_capacity_arr is not None
                base_capacity = np.where(
                    np.isfinite(liquidity_capacity_arr[t]) & (liquidity_capacity_arr[t] > 0),
                    liquidity_capacity_arr[t],
                    0.0,
                )
                for p_idx in range(P):
                    base_capacity[p_idx] = float(currency_context.to_base(base_capacity[p_idx], product_currency_arr[p_idx], time_index[t]))
                base_capacity = np.where(executable, base_capacity, 0.0)
                executable_capacity_t[percent_rows] = (
                    base_capacity[np.newaxis, :] * equity[percent_rows, np.newaxis] * percent_scale[percent_rows, np.newaxis]
                )
            liquidity_capacity_amounts_np[t] = executable_capacity_t.copy()

            curr_mask_all = membership_np[t]
            prev_mask_all = quantities > 0

            # ── 函数A：卖出 ──
            def _sell_positions(
                quantities_in: np.ndarray,
                sell_mask: np.ndarray,
            ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
                result = quantities_in.copy()
                released_minor_units = np.zeros(M, dtype=np.int64)
                realized_minor_units = np.zeros(M, dtype=np.int64)
                for row_idx in range(M):
                    if not sell_mask[row_idx].any():
                        continue
                    for p_idx in range(P):
                        if not sell_mask[row_idx, p_idx]:
                            continue
                        if result[row_idx, p_idx] <= 0:
                            continue
                        if not executable[p_idx]:
                            continue
                        cv_minor_units = int(contract_value_minor_units[p_idx])
                        if cv_minor_units <= 0:
                            continue
                        qty = result[row_idx, p_idx]
                        lot = lot_row[p_idx]
                        max_lots = int(np.floor(qty / lot + 1e-12))
                        capacity = executable_capacity_t[row_idx, p_idx]
                        if np.isfinite(capacity):
                            capacity_minor_units = int(_floor_minor_units(capacity))
                            max_lots_by_cap = int(capacity_minor_units // max(1, int(round(lot * cv_minor_units))))
                            max_lots = min(max_lots, max_lots_by_cap)
                        if max_lots <= 0:
                            continue
                        sell_qty = float(max_lots) * lot
                        sell_notional_minor_units = int(round(sell_qty * cv_minor_units))
                        if use_margin[row_idx, p_idx]:
                            cash_released_minor_units = int(np.floor(sell_notional_minor_units * margin_ratios_t[p_idx] + 1e-9))
                        else:
                            cash_released_minor_units = sell_notional_minor_units
                        close_fee_here_minor_units = int(_round_minor_units(
                            (sell_notional_minor_units / 100.0) * close_rate_by_group[row_idx, p_idx]
                            + float(currency_context.to_base(sell_qty * close_fixed_by_group[row_idx, p_idx], product_currency_arr[p_idx], time_index[t], applies_fee=True))
                        ))
                        realized_here_minor_units = int(_round_minor_units(
                            _lot_realize_sell(row_idx, p_idx, sell_qty, float(contract_value_base[p_idx]))
                        ))
                        released_minor_units[row_idx] += cash_released_minor_units + realized_here_minor_units - close_fee_here_minor_units
                        realized_minor_units[row_idx] += realized_here_minor_units
                        result[row_idx, p_idx] -= sell_qty
                return result, released_minor_units, realized_minor_units

            # ── 函数B：等额现金分配买入 ──
            def _buy_cost_minor_units(row_idx: int, p_idx: int, lots: int) -> int:
                if lots <= 0:
                    return 0
                qty = float(lots) * lot_row[p_idx]
                notional_minor_units = int(_round_minor_units(qty * contract_value_base[p_idx]))
                if use_margin[row_idx, p_idx]:
                    margin_minor_units = int(_round_minor_units((notional_minor_units / 100.0) * margin_ratios_t[p_idx]))
                else:
                    margin_minor_units = notional_minor_units
                fee_minor_units = int(_round_minor_units(
                    (notional_minor_units / 100.0) * open_rate_by_group[row_idx, p_idx]
                    + float(currency_context.to_base(qty * open_fixed_by_group[row_idx, p_idx], product_currency_arr[p_idx], time_index[t], applies_fee=True))
                ))
                return max(0, margin_minor_units + fee_minor_units)

            def _max_lots_by_cash(row_idx: int, p_idx: int, cash_limit_minor_units: int) -> tuple[int, int]:
                if cash_limit_minor_units <= 0:
                    return 0, 0
                one_lot_cost = _buy_cost_minor_units(row_idx, p_idx, 1)
                if one_lot_cost <= 0 or one_lot_cost > cash_limit_minor_units:
                    return 0, one_lot_cost
                hi = max(1, cash_limit_minor_units // one_lot_cost + 2)
                while _buy_cost_minor_units(row_idx, p_idx, hi) <= cash_limit_minor_units:
                    hi *= 2
                lo = 1
                best_lots = 1
                best_cost = one_lot_cost
                while lo <= hi:
                    mid = (lo + hi) // 2
                    mid_cost = _buy_cost_minor_units(row_idx, p_idx, mid)
                    if mid_cost <= cash_limit_minor_units:
                        best_lots = mid
                        best_cost = mid_cost
                        lo = mid + 1
                    else:
                        hi = mid - 1
                return int(best_lots), int(best_cost)

            def _buy_equal_alloc(
                quantities_in: np.ndarray,
                buy_mask: np.ndarray,
                available_cash_minor_units: np.ndarray,
            ) -> np.ndarray:
                result = quantities_in.copy()
                cash_minor_units = np.asarray(available_cash_minor_units, dtype=np.int64).copy()

                MAX_ITERATIONS = 100
                for _iter in range(MAX_ITERATIONS):
                    changed_any = False
                    for row_idx in range(M):
                        if cash_minor_units[row_idx] <= 0:
                            continue

                        eligible_indices = []
                        for p_idx in range(P):
                            if not buy_mask[row_idx, p_idx]:
                                continue
                            if not executable[p_idx]:
                                continue
                            cv_minor_units = int(contract_value_minor_units[p_idx])
                            if cv_minor_units <= 0:
                                continue
                            if not np.isfinite(lot_row[p_idx]) or lot_row[p_idx] <= 0:
                                continue
                            one_lot_cost_minor_units = _buy_cost_minor_units(row_idx, p_idx, 1)
                            if one_lot_cost_minor_units <= 0:
                                continue
                            capacity = executable_capacity_t[row_idx, p_idx]
                            max_lots_by_cap = None
                            if np.isfinite(capacity):
                                capacity_minor_units = int(_floor_minor_units(capacity))
                                max_by_cap, _ = _max_lots_by_cash(row_idx, p_idx, capacity_minor_units)
                                if max_by_cap <= 0:
                                    continue
                                max_lots_by_cap = max_by_cap
                            eligible_indices.append((p_idx, one_lot_cost_minor_units, max_lots_by_cap))

                        if not eligible_indices:
                            continue

                        n_eligible = len(eligible_indices)
                        per_cash_minor_units = cash_minor_units[row_idx] // n_eligible

                        spent_minor_units = 0
                        for p_idx, _one_lot_cost_minor_units, max_lots_by_cap in eligible_indices:
                            max_lots_by_cash, spent_here_minor_units = _max_lots_by_cash(row_idx, p_idx, int(per_cash_minor_units))
                            max_lots = max_lots_by_cash
                            if max_lots_by_cap is not None:
                                max_lots = min(max_lots, max_lots_by_cap)
                                spent_here_minor_units = _buy_cost_minor_units(row_idx, p_idx, max_lots)
                            if max_lots <= 0:
                                continue

                            buy_qty_p = float(max_lots) * lot_row[p_idx]

                            result[row_idx, p_idx] += buy_qty_p
                            _lot_push(row_idx, p_idx, buy_qty_p, float(contract_value_base[p_idx]))
                            if np.isfinite(executable_capacity_t[row_idx, p_idx]):
                                executable_capacity_t[row_idx, p_idx] = max(
                                    0.0,
                                    executable_capacity_t[row_idx, p_idx] - (spent_here_minor_units / 100.0),
                                )
                            spent_minor_units += spent_here_minor_units
                            cash_minor_units[row_idx] -= spent_here_minor_units
                            changed_any = True

                        if spent_minor_units <= 0:
                            best_idx = -1
                            best_cost = None
                            best_qty = None
                            for p_idx, _one_lot_cost_minor_units, max_lots_by_cap in eligible_indices:
                                if max_lots_by_cap is not None and max_lots_by_cap <= 0:
                                    continue
                                extra_cost_minor_units = _buy_cost_minor_units(row_idx, p_idx, 1)
                                if extra_cost_minor_units <= 0 or extra_cost_minor_units > cash_minor_units[row_idx]:
                                    continue
                                current_qty = result[row_idx, p_idx]
                                if (
                                    best_qty is None
                                    or current_qty < best_qty - 1e-12
                                    or (abs(current_qty - best_qty) <= 1e-12 and (best_cost is None or extra_cost_minor_units < best_cost))
                                ):
                                    best_idx = p_idx
                                    best_cost = extra_cost_minor_units
                                    best_qty = current_qty
                            if best_idx >= 0 and best_cost is not None:
                                result[row_idx, best_idx] += lot_row[best_idx]
                                _lot_push(row_idx, best_idx, float(lot_row[best_idx]), float(contract_value_base[best_idx]))
                                if np.isfinite(executable_capacity_t[row_idx, best_idx]):
                                    executable_capacity_t[row_idx, best_idx] = max(
                                        0.0,
                                        executable_capacity_t[row_idx, best_idx] - (best_cost / 100.0),
                                    )
                                cash_minor_units[row_idx] -= best_cost
                                changed_any = True

                    if not changed_any:
                        break

                return result

            # ── 确定卖/买掩码 ──
            # each_period: 全部卖出 + 全部买入（完整重平衡）
            # buy_and_hold / recycle: 只卖 exiting + 只买 entering
            staying_mask = curr_mask_all & prev_mask_all
            exiting_mask = prev_mask_all & (~curr_mask_all)
            entering_mask = curr_mask_all & (~prev_mask_all)

            is_each_period = rebalance_modes_arr == "each_period"

            # 卖
            sell_mask = np.where(is_each_period[:, np.newaxis], prev_mask_all, exiting_mask)
            # 买
            buy_mask = np.where(is_each_period[:, np.newaxis], curr_mask_all, entering_mask)

            # 保存原始持仓
            quantities_old = quantities.copy()

            # 执行卖出
            quantities, cash_released_minor_units, sell_realized_minor_units = _sell_positions(quantities, sell_mask)
            if bool(np.any(sell_realized_minor_units)):
                equity = _from_minor_units(_round_minor_units(equity) + sell_realized_minor_units)

            # 可用现金
            # each_period：全卖了，所有资产都是现金 → available_cash = equity
            # buy_and_hold/recycle：staying 未卖，其保证金仍锁定 → available_cash = (equity - staying_occupied) + cash_released
            available_cash_minor_units = _floor_minor_units(equity)
            hold_like_rows = hold_rows | recycle_rows
            if hold_like_rows.any():
                available_cash_minor_units[hold_like_rows] = np.maximum(
                    0,
                    _floor_minor_units(pre_rebalance_cash[hold_like_rows]) + cash_released_minor_units[hold_like_rows],
                )

            # 执行买入
            quantities = _buy_equal_alloc(quantities, buy_mask, available_cash_minor_units)

            # recycle_rows with same_position_set: 冻结 entering
            # 跳过初始周期（prev_mask_all 全 False，entering == curr）
            if bool(recycle_rows.any()):
                current_positive = quantities > 0
                same_position_set = np.all(current_positive == curr_mask_all, axis=1)
                freeze_entering_rows = recycle_rows & same_position_set
                # 初始建仓时不冻结（entering 就是 curr，即首次买入）
                is_initial_period = ~np.any(prev_mask_all, axis=1)
                freeze_entering_rows[is_initial_period] = False
                if bool(freeze_entering_rows.any()):
                    quantities[freeze_entering_rows] = np.where(
                        entering_mask[freeze_entering_rows],
                        0.0,
                        quantities[freeze_entering_rows],
                    )

            # 不可执行品种恢复原持仓
            quantities[:, ~executable] = quantities_old[:, ~executable]

            desired_quantities = quantities
            target_amounts_before_floor = quantities * contract_value_base_row

            buy_qty = np.clip(desired_quantities - quantities_old, 0.0, None)
            sell_qty = np.clip(quantities_old - desired_quantities, 0.0, None)
            buy_notional_minor_units = _round_minor_units(buy_qty * contract_value_base_row)
            sell_notional_minor_units = _round_minor_units(sell_qty * contract_value_base_row)
            buy_notional = _from_minor_units(buy_notional_minor_units)
            sell_notional = _from_minor_units(sell_notional_minor_units)
            buy_fixed_base = np.zeros_like(buy_qty, dtype=float)
            sell_fixed_base = np.zeros_like(sell_qty, dtype=float)
            for p_idx in range(P):
                buy_fixed_base[:, p_idx] = currency_context.to_base(buy_qty[:, p_idx] * open_fixed_by_group[:, p_idx], product_currency_arr[p_idx], time_index[t], applies_fee=True)
                sell_fixed_base[:, p_idx] = currency_context.to_base(sell_qty[:, p_idx] * close_fixed_by_group[:, p_idx], product_currency_arr[p_idx], time_index[t], applies_fee=True)
            buy_fee_minor_units = _round_minor_units(buy_notional * open_rate_by_group + buy_fixed_base)
            sell_fee_minor_units = _round_minor_units(sell_notional * close_rate_by_group + sell_fixed_base)
            buy_fee = _from_minor_units(buy_fee_minor_units)
            sell_fee = _from_minor_units(sell_fee_minor_units)
            fee_amount = buy_fee + sell_fee
            position_notional = _from_minor_units(_round_minor_units(desired_quantities * contract_value_base_row))
        gross_contrib = np.where(
            equity[:, np.newaxis] > 0,
            position_notional / equity[:, np.newaxis] * returns_np[t][np.newaxis, :],
            0.0,
        )
        gross_contrib = np.nan_to_num(gross_contrib, nan=0.0, posinf=0.0, neginf=0.0)
        gross = np.nansum(gross_contrib, axis=1)
        fee_ratio = np.divide(
            np.nansum(fee_amount, axis=1),
            equity,
            out=np.zeros(M, dtype=float),
            where=equity > 0,
        )
        total_fee_amount = _from_minor_units(_round_minor_units(np.nansum(fee_amount, axis=1)))
        post_rebalance_total = _from_minor_units(_floor_minor_units(equity) - _round_minor_units(total_fee_amount))
        start_occupied = np.where(
            use_margin,
            position_notional * margin_ratios_t,
            position_notional,
        )
        post_rebalance_cash = _from_minor_units(
            _round_minor_units(post_rebalance_total - np.nansum(start_occupied, axis=1))
        )
        net = gross - fee_ratio
        end_equity = _from_minor_units(_round_minor_units(equity * (1.0 + net)))
        end_price = price_t * (1.0 + returns_np[t])
        end_contract_value_base = end_price * multipliers_t
        for p_idx in range(P):
            end_contract_value_base[p_idx] = float(currency_context.to_base(end_contract_value_base[p_idx], product_currency_arr[p_idx], time_index[t]))
        end_notional = _from_minor_units(_round_minor_units(desired_quantities * end_contract_value_base[np.newaxis, :]))
        end_occupied = np.where(
            use_margin,
            end_notional * margin_ratios_t,
            end_notional,
        )
        end_occupied = _from_minor_units(_floor_minor_units(np.nansum(end_occupied, axis=1)))

        net_returns_np[t] = net
        gross_returns_np[t] = gross
        product_gross_contrib_np[t] = gross_contrib
        product_fee_contrib_np[t] = np.where(
            equity[:, np.newaxis] > 0,
            fee_amount / equity[:, np.newaxis],
            0.0,
        )
        fee_costs_np[t] = fee_ratio
        trade_notional_ratio_np[t] = np.divide(
            np.nansum(buy_notional + sell_notional, axis=1),
            equity,
            out=np.zeros(M, dtype=float),
            where=equity > 0,
        )
        target_amounts_np[t] = _round_minor_units(position_notional)
        target_amounts_before_floor_np[t] = _round_minor_units(target_amounts_before_floor)
        prev_end_amounts_np[t] = _round_minor_units(end_notional)
        position_quantities_np[t] = desired_quantities
        margin_occupied_np[t] = _round_minor_units(end_occupied)
        pre_rebalance_total_equity_np[t] = _round_minor_units(pre_rebalance_total)
        post_rebalance_total_equity_np[t] = _round_minor_units(post_rebalance_total)
        total_equity_np[t] = _round_minor_units(end_equity)
        pre_rebalance_cash_np[t] = _round_minor_units(pre_rebalance_cash)
        post_rebalance_cash_np[t] = _round_minor_units(post_rebalance_cash)
        cash_np[t] = _round_minor_units(
            post_rebalance_cash
            + (end_equity - post_rebalance_total)
        )
        buy_fee_amount_np[t] = _round_minor_units(np.nansum(buy_fee, axis=1))
        sell_fee_amount_np[t] = _round_minor_units(np.nansum(sell_fee, axis=1))

        # Display-only one-lot estimates stay unrounded; real execution uses
        # whole-order minor_units costs in _buy_cost_minor_units.
        one_lot_margin_np[t] = one_lot_margin_display_mat
        one_lot_fee_np[t] = one_lot_fee_display_mat

        quantities = desired_quantities
        equity = end_equity
        prev_post_rebalance_total = post_rebalance_total.copy()
        prev_post_rebalance_cash = post_rebalance_cash.copy()

    return {
        'net_returns_np': net_returns_np,
        'gross_returns_np': gross_returns_np,
        'product_gross_contrib_np': product_gross_contrib_np,
        'product_fee_contrib_np': product_fee_contrib_np,
        'fee_costs_np': fee_costs_np,
        'trade_notional_ratio_np': trade_notional_ratio_np,
        'multi_session_triggered': 0,
        'target_amounts_np': target_amounts_np,
        'target_amounts_before_floor_np': target_amounts_before_floor_np,
        'prev_end_amounts_np': prev_end_amounts_np,
        'position_quantities_np': position_quantities_np,
        'margin_occupied_np': margin_occupied_np,
        'pre_rebalance_total_equity_np': pre_rebalance_total_equity_np,
        'post_rebalance_total_equity_np': post_rebalance_total_equity_np,
        'total_equity_np': total_equity_np,
        'pre_rebalance_cash_np': pre_rebalance_cash_np,
        'post_rebalance_cash_np': post_rebalance_cash_np,
        'post_settlement_cash_np': post_settlement_cash_np,
        'cash_np': cash_np,
        'buy_fee_amount_np': buy_fee_amount_np,
        'sell_fee_amount_np': sell_fee_amount_np,
        'liquidity_capacity_amounts_np': liquidity_capacity_amounts_np,
        'one_lot_margin_np': one_lot_margin_np,
        'one_lot_fee_np': one_lot_fee_np,
        'base_currency': base_currency,
        'product_currency_vec': product_currency_arr,
        'currency_conversion_fee_rate': currency_conversion_fee_rate,
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
    product_contrib = np.nan_to_num(product_contrib, nan=0.0, posinf=0.0, neginf=0.0)
    return product_contrib, np.nansum(product_contrib, axis=1)


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

    close_fee_vec accepts (P,) or (group_count, P). 1-D is broadcast to group_count.
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
    sell_fee = np.nansum(sell * effective, axis=1)
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
    sell_fee = np.nansum(sell * effective, axis=1)
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

    open_fee_vec accepts (P,) or (group_count, P). 1-D is broadcast to group_count.
    """
    buy = np.clip(target_amounts - np.asarray(prev_end_amounts), 0.0, None)
    sell = np.clip(np.asarray(prev_end_amounts) - target_amounts, 0.0, None)
    open_fees = np.asarray(open_fee_vec, dtype=float)
    if open_fees.ndim == 1:
        open_fees = open_fees[np.newaxis, :]  # (1, P) → broadcast
    buy_fee = np.nansum(buy * open_fees, axis=1)
    trade_notional_ratio = np.divide(
        np.nansum(buy + sell, axis=1),
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
    buy_fee = np.nansum(buy * open_fee_mat, axis=1)
    trade_notional_ratio = np.divide(
        np.nansum(buy + sell, axis=1),
        wealth_before_trade,
        out=np.zeros_like(buy_fee, dtype=float),
        where=wealth_before_trade > 0,
    )
    return buy, buy_fee, trade_notional_ratio
