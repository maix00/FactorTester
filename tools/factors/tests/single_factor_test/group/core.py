"""Group test core implementation."""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple, cast

import numpy as np
import pandas as pd
from tqdm import tqdm

from Settings import factor_info_path
from tools.data.DataFreq import DataFreq
from tools.factors import Factor
from tools.factors.FactorTester import _align_ts_to_index, _extract_signal_index
from tools.factors.Parameters import FactorNextPeriodReturns
from tools.factors.tests.single_factor_test.group.result import GroupRunResult


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


def build_target_amounts(
    curr_mask_all: np.ndarray,
    prev_end_amounts: np.ndarray,
    wealth_before_trade: np.ndarray,
    rebalance_mode: str,
    close_fee_vec: np.ndarray | None = None,
) -> np.ndarray:
    """Build next-period target holdings for all groups with vectorized operations.

    Parameters
    ----------
    close_fee_vec : (P,) array of per-product close fee rates.
        When provided, the capital released from exits is reduced by the
        proportional close fee before being allocated to entering products.
        Omitting it preserves backward compatibility (fee applied later in
        Omitting it preserves backward compatibility, but may cause target over-allocation.
    """
    curr_mask = np.asarray(curr_mask_all, dtype=bool)
    prev_amounts = np.asarray(prev_end_amounts, dtype=float)
    wealth = np.asarray(wealth_before_trade, dtype=float)
    counts = curr_mask.sum(axis=1).astype(float)
    targets = np.zeros_like(prev_amounts, dtype=float)
    non_empty = counts > 0
    if not non_empty.any():
        return targets

    if rebalance_mode == "each_period":
        if close_fee_vec is not None:
            # Available cash = wealth minus close fees on all prior holdings.
            sell_fees = (prev_amounts * close_fee_vec[np.newaxis, :]).sum(axis=1)
            available = np.maximum(0.0, wealth - sell_fees)
            targets[non_empty] = (
                curr_mask[non_empty].astype(float)
                * (available[non_empty] / counts[non_empty])[:, np.newaxis]
            )
        else:
            targets[non_empty] = (
                curr_mask[non_empty].astype(float)
                * (wealth[non_empty] / counts[non_empty])[:, np.newaxis]
            )
        return targets

    prev_mask = prev_amounts > 0
    staying = curr_mask & prev_mask
    exiting = prev_mask & (~curr_mask)
    entering = curr_mask & (~prev_mask)
    n_entering = entering.sum(axis=1).astype(float)
    # Gross released amount (before close fee)
    sell_amounts = (prev_amounts * exiting.astype(float)).sum(axis=1)

    # Subtract close fee from released capital — the actual cash available
    # after selling is sell_amounts * (1 - close_fee) per exiting product.
    if close_fee_vec is not None:
        sell_fees = (prev_amounts * exiting.astype(float) * close_fee_vec[np.newaxis, :]).sum(axis=1)
        released = np.maximum(0.0, sell_amounts - sell_fees)
    else:
        released = sell_amounts

    targets = prev_amounts * staying.astype(float)
    rows_with_released = (n_entering > 0) & (released > 0)
    if rows_with_released.any():
        targets[rows_with_released] += (
            entering[rows_with_released].astype(float)
            * (released[rows_with_released] / n_entering[rows_with_released])[:, np.newaxis]
        )

    fallback_rows = non_empty & (n_entering > 0) & (~rows_with_released)
    if rebalance_mode == "buy_and_hold":
        # If membership expands without any released capital, equal-weight once to fund entrants.
        if fallback_rows.any():
            targets[fallback_rows] = (
                curr_mask[fallback_rows].astype(float)
                * (wealth[fallback_rows] / counts[fallback_rows])[:, np.newaxis]
            )
    elif rebalance_mode == "recycle":
        # Keep staying holdings; fund entrants with an equal-weight top-up when no capital was released.
        if fallback_rows.any():
            targets[fallback_rows] += (
                entering[fallback_rows].astype(float)
                * (wealth[fallback_rows] / counts[fallback_rows])[:, np.newaxis]
            )
    else:
        raise ValueError(f"Unknown rebalance_mode: {rebalance_mode!r}")

    totals = targets.sum(axis=1)
    # Rescale to wealth only when we did NOT deduct close fees (backward
    # compat).  When close_fee_vec is provided, exiting capital is already
    # net of fees so targets.sum() < wealth is expected — do not rescale.
    rescale = (
        non_empty
        & (totals > 0)
        & (np.abs(totals - wealth) > 1e-12)
        & (close_fee_vec is None)
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
    """Build multi-session target holdings for all groups in one matrix pass."""
    curr_mask = np.asarray(curr_mask_all, dtype=bool)
    prev_amounts = np.asarray(prev_end_amounts, dtype=float)
    wealth = np.asarray(wealth_before_trade, dtype=float)
    has_bar_vec = np.asarray(has_bar, dtype=bool)
    close_fees = np.asarray(close_fee_vec, dtype=float)

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
        sell_amounts.sum(axis=1) - (sell_amounts * close_fees[np.newaxis, :]).sum(axis=1),
    )
    entering_counts = entering_with_bar.sum(axis=1).astype(float)

    targets = prev_amounts * (staying | exiting_without_bar)
    funded = non_empty & (entering_counts > 0) & (recycled > 0)
    if funded.any():
        targets[funded] += (
            entering_with_bar[funded].astype(float)
            * (recycled[funded] / entering_counts[funded])[:, np.newaxis]
        )

    initial_funding = non_empty & (~prev_mask.any(axis=1)) & (entering_counts > 0)
    if initial_funding.any():
        targets[initial_funding] = (
            entering_with_bar[initial_funding].astype(float)
            * (wealth[initial_funding] / entering_counts[initial_funding])[:, np.newaxis]
        )

    # multi-session 已扣 close fee，不 rescale 回 wealth（targets.sum < wealth 是正确的）
    return targets


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
    """
    prev = np.asarray(prev_end_amounts, dtype=float)
    target = np.asarray(target_amounts, dtype=float)
    # 只对卖出部分收费：prev - target 为正时才收费（exiting portion）
    sell = np.clip(prev - target, 0.0, None)
    effective_close_fee_vec = np.asarray(
        close_today_fee_vec if close_today_fee_vec is not None else close_fee_vec,
        dtype=float,
    )
    sell_fee = (sell * effective_close_fee_vec[np.newaxis, :]).sum(axis=1)
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
    """
    buy = np.clip(target_amounts - np.asarray(prev_end_amounts), 0.0, None)
    sell = np.clip(np.asarray(prev_end_amounts) - target_amounts, 0.0, None)
    buy_fee = (buy * open_fee_vec[np.newaxis, :]).sum(axis=1)
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

    参数：
        open_fee_vec、close_fee_vec、close_today_fee_vec 由外部调用方构建传入，
        **不得**从 group_result 的属性中获取（group_result 的 fee 数据属于
        上一次 base group 运行时的上下文，可能与当前请求的费率配置不一致）。
    """
    membership_np = getattr(group_result, 'membership_np', None)
    period_returns_np = getattr(group_result, 'period_returns_np', None)

    if membership_np is None or period_returns_np is None:
        raise ValueError('GroupRunResult 缺少 membership_np 或 period_returns_np')

    T = membership_np.shape[0]
    sel = np.asarray(selected_idx, dtype=int)
    P = len(sel)

    # 裁剪到子集品种
    mask = membership_np[:, group_index, :][:, sel]           # (T, P)
    returns = period_returns_np[:, sel]                        # (T, P)
    open_fv = open_fee_vec[sel] if open_fee_vec is not None else np.zeros(P)
    # 根据 use_closetoday 选择平今或平昨
    if use_closetoday and close_today_fee_vec is not None:
        close_fv = close_today_fee_vec[sel]
    else:
        close_fv = close_fee_vec[sel] if close_fee_vec is not None else np.zeros(P)

    net_returns_arr = np.zeros(T, dtype=float)
    gross_returns_arr = np.zeros(T, dtype=float)
    fee_costs_arr = np.zeros(T, dtype=float)
    notional_ratio_arr = np.zeros(T, dtype=float)

    wealth = 1.0
    prev_amounts = np.zeros(P, dtype=float)

    for t in range(T):
        curr_mask = mask[t]                                  # (P,) bool
        n_products = curr_mask.sum()
        wb = wealth

        if n_products == 0:
            # 清仓：卖出所有持仓
            prev_2d = prev_amounts.reshape(1, -1)  # (1, P)
            zero_target = np.zeros_like(prev_2d)
            _, sell_fee = compute_sell_fee(
                prev_2d, zero_target, close_fv,
                close_today_fee_vec=None,  # close_fv 已选择平今/平昨
            )
            sell_fee = float(sell_fee[0])
            sell_fee_ratio = sell_fee / wb if wb > 0 else 0.0
            net_ret = -sell_fee_ratio  # 纯卖，无持仓，gross=0
            wealth = wb * (1.0 + net_ret)
            net_returns_arr[t] = net_ret
            gross_returns_arr[t] = 0.0
            fee_costs_arr[t] = sell_fee_ratio
            notional_ratio_arr[t] = prev_amounts.sum() / wb if wb > 0 else 0.0
            prev_amounts = np.zeros(P, dtype=float)
            continue

        # 非空组：build target amounts（单组模式，向量化但只有 1 行）
        mask_2d = curr_mask.reshape(1, -1)  # (1, P)
        prev_2d = prev_amounts.reshape(1, -1)  # (1, P)
        wb_2d = np.array([wb])  # (1,)

        # 用现有的 build_target_amounts（多时段暂不处理，精选组复用 base group 模式）
        target_2d = build_target_amounts(mask_2d, prev_2d, wb_2d, rebalance_mode, close_fee_vec=close_fv)
        target = target_2d[0]  # (P,)

        # 两步 fee 模型：Step1 卖（已在 build_target 中扣），Step2 买
        # Step 1: 卖出费用（只对 exiting 部分收费）
        _, sell_fee = compute_sell_fee(
            prev_2d, target_2d, close_fv,
            close_today_fee_vec=None,  # close_fv 已选择平今/平昨版本
        )
        sell_fee = float(sell_fee[0])
        sell_fee_ratio = sell_fee / wb if wb > 0 else 0.0

        # Step 2: 买入费用
        buy, buy_fee, trade_notional_ratio = compute_buy_costs(
            target_2d, prev_2d, open_fv, wb_2d,
        )
        buy_fee_val = float(buy_fee[0])
        buy_fee_ratio = buy_fee_val / wb if wb > 0 else 0.0
        notional_ratio = float(trade_notional_ratio[0])

        # gross returns（target 扣 buy_fee 后计算）
        ret_t = returns[t]  # (P,)
        buy_open_fees = buy * open_fv[np.newaxis, :]
        product_contrib, gross = compute_group_gross_returns(
            target_2d, wb_2d, ret_t, buy_open_fees=buy_open_fees,
        )
        gross = float(gross[0])

        # net returns: gross - sell_fee_ratio - buy_fee_ratio
        net_ret = gross - sell_fee_ratio - buy_fee_ratio

        wealth = wb * (1.0 + net_ret)
        net_returns_arr[t] = net_ret
        gross_returns_arr[t] = gross
        fee_costs_arr[t] = sell_fee_ratio + buy_fee_ratio
        notional_ratio_arr[t] = notional_ratio

        # update prev_end_amounts: 期末持仓 = 买入后实际投入 × 品种收益
        new_prev = (target - buy_open_fees[0]) * (1.0 + ret_t)
        prev_amounts = np.where(new_prev > 0, new_prev, 0.0)

    cumulative = np.cumprod(1.0 + net_returns_arr)
    return {
        'net_returns': net_returns_arr,
        'gross_returns': gross_returns_arr,
        'fee_costs': fee_costs_arr,
        'notional_ratios': notional_ratio_arr,
        'cumulative': cumulative,
    }


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
) -> Tuple[Any, Any, pd.DataFrame, np.ndarray, list]:
    """Single-factor group test core logic.

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

    products_dict = {
        g: {index_list[t]: [valid_cols[i]
                             for i in np.where(membership_np[t, g])[0]]
            for t in range(T)}
        for g in range(n_groups)
    }

    bad_ret_mask = np.isnan(returns_np) | np.isinf(returns_np) | (returns_np <= -1.0)
    returns_filled = np.where(bad_ret_mask, 0.0, returns_np)
    member_counts = membership_np.sum(axis=2).astype(float)

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

    # close_fee_vec 始终=平昨，close_today_fee_vec 始终=平今
    effective_close_fee_vec = close_today_fee_vec if use_closetoday else None

    group_gross_returns_np = np.zeros((T, n_groups), dtype=float)
    group_product_gross_contrib_np = np.zeros((T, n_groups, P), dtype=float)
    group_product_fee_contrib_np = np.zeros((T, n_groups, P), dtype=float)
    fee_costs_np = np.zeros((T, n_groups), dtype=float)
    trade_notional_ratio_np = np.zeros((T, n_groups), dtype=float)
    group_returns_np = np.zeros((T, n_groups), dtype=float)

    _VALID_MODES = frozenset({"each_period", "buy_and_hold", "recycle"})
    if rebalance_mode not in _VALID_MODES:
        raise ValueError(f"rebalance_mode must be one of {sorted(_VALID_MODES)}, got {rebalance_mode!r}")

    # ── 逐期矩阵化收益计算 ──
    # 所有组并行处理：prev_end_amounts: (n_groups, P), wealth: (n_groups,)
    wealth = np.ones(n_groups, dtype=float)
    prev_end_amounts = np.zeros((n_groups, P), dtype=float)

    # 多时段：预计算每期哪些品种有原始数据（注意：不是因子信号是否 NaN）
    data_has_bar = present_np  # (T, P)

    # 记录每期多时段策略触发的组（用于报告）
    multi_session_triggered_count = 0

    for t in range(T):
        curr_mask_all = membership_np[t]          # (n_groups, P) bool
        curr_count_all = member_counts[t]          # (n_groups,) float
        wealth_before_trade = wealth.copy()        # (n_groups,)

        # ── 本期是否触发多时段逻辑 ──
        # 判断标准：当期存在部分品种有原始数据、部分品种无原始数据（混合行）
        has_bar_t = data_has_bar[t]               # (P,) bool
        is_mixed_t = multi_session_active and has_bar_t.any() and (~has_bar_t).any()

        # ── 计算 target_amounts: (n_groups, P) ──
        target_amounts = np.zeros((n_groups, P), dtype=float)

        # --- 空组：curr_count == 0 ---
        empty_mask = curr_count_all == 0           # (n_groups,)
        non_empty_mask = ~empty_mask

        if empty_mask.any():
            # 空组清仓：只扣卖出费用，无买入
            sell_empty = prev_end_amounts[empty_mask]  # (n_empty, P)
            zero_target = np.zeros_like(sell_empty)
            effective_close_rates = effective_close_fee_vec if effective_close_fee_vec is not None else close_fee_vec
            _, sell_fee_empty = compute_sell_fee(
                sell_empty, zero_target, effective_close_rates,
                close_today_fee_vec=None,  # effective_close_rates 已选择
            )
            sell_fee_ratio_empty = np.divide(
                sell_fee_empty, wealth_before_trade[empty_mask],
                out=np.zeros_like(sell_fee_empty, dtype=float),
                where=wealth_before_trade[empty_mask] > 0,
            )
            net_ret_empty = -sell_fee_ratio_empty  # gross=0, net = -sell_fee_ratio
            wealth[empty_mask] = wealth_before_trade[empty_mask] * (1.0 + net_ret_empty)
            group_gross_returns_np[t, empty_mask] = 0.0
            group_product_gross_contrib_np[t, empty_mask] = 0.0
            # per-product fee contrib for empty groups
            sell_fee = sell_empty * effective_close_rates[np.newaxis, :]
            empty_fee_contrib = np.where(
                wealth_before_trade[empty_mask, np.newaxis] > 0,
                sell_fee / wealth_before_trade[empty_mask, np.newaxis],
                0.0,
            )
            group_product_fee_contrib_np[t, empty_mask] = empty_fee_contrib
            fee_costs_np[t, empty_mask] = sell_fee_ratio_empty
            group_returns_np[t, empty_mask] = net_ret_empty
            prev_end_amounts[empty_mask] = 0.0

        if not non_empty_mask.any():
            continue

        # --- 非空组 ---
        ne_idx = np.where(non_empty_mask)[0]

        if is_mixed_t:
            # ===== 多时段品种策略（逐期自适应）=====
            multi_session_triggered_count += 1
            target_amounts = build_multi_session_target_amounts(
                curr_mask_all,
                prev_end_amounts,
                wealth_before_trade,
                has_bar_t,
                close_fee_vec,
            )

        elif rebalance_mode in {"each_period", "buy_and_hold", "recycle"}:
            target_amounts = build_target_amounts(
                curr_mask_all,
                prev_end_amounts,
                wealth_before_trade,
                rebalance_mode,
                close_fee_vec=close_fee_vec,
            )

        # ── 两步 fee 模型：Step1 卖（已在 build_target 中扣 sell_fee），Step2 买 ──
        ne_target = target_amounts[ne_idx]           # (n_ne, P) — 已基于 wealth-sell_fee 分配
        ne_prev = prev_end_amounts[ne_idx]           # (n_ne, P)
        ne_wb = wealth_before_trade[ne_idx]          # (n_ne,)
        ne_cc = curr_count_all[ne_idx]               # (n_ne,)
        ne_ret = returns_filled[t]                   # (P,) — 本期收益

        # Step 1: 卖出费用（只对 exiting 部分收费）
        # sell = clip(prev - target, 0) — 只对卖出超出目标的部分收费
        sell, sell_fee = compute_sell_fee(
            ne_prev, ne_target, close_fee_vec,
            close_today_fee_vec=effective_close_fee_vec,
        )
        sell_fee_ratio = np.divide(
            sell_fee, ne_wb,
            out=np.zeros_like(sell_fee, dtype=float),
            where=ne_wb > 0,
        )

        # Step 2: 买入费用
        buy, buy_fee, trade_notional_ratio = compute_buy_costs(
            ne_target, ne_prev, open_fee_vec, ne_wb,
        )
        buy_fee_ratio = np.divide(
            buy_fee, ne_wb,
            out=np.zeros_like(buy_fee, dtype=float),
            where=ne_wb > 0,
        )

        # per-product fee contrib (as fraction of wealth)，用于后续精选组聚合
        product_close_vec = effective_close_fee_vec if effective_close_fee_vec is not None else close_fee_vec
        product_fee = buy * open_fee_vec[np.newaxis, :] + sell * product_close_vec[np.newaxis, :]
        product_fee_contrib = np.where(
            ne_wb[:, np.newaxis] > 0,
            product_fee / ne_wb[:, np.newaxis],
            0.0,
        )

        # 总收益：target 扣 buy_fee 后算 gross，sell_fee + buy_fee 在 net 公式里扣
        buy_open_fees = buy * open_fee_vec[np.newaxis, :]  # (n_ne, P)
        product_gross_contrib, gross = compute_group_gross_returns(
            ne_target, ne_wb, ne_ret, buy_open_fees=buy_open_fees,
        )
        net_ret = compute_group_net_returns(gross, sell_fee_ratio, buy_fee_ratio, ne_wb, ne_target)

        wealth[ne_idx] = ne_wb * (1.0 + net_ret)
        group_gross_returns_np[t, ne_idx] = gross
        group_product_gross_contrib_np[t, ne_idx] = product_gross_contrib
        group_product_fee_contrib_np[t, ne_idx] = product_fee_contrib
        fee_costs_np[t, ne_idx] = sell_fee_ratio + buy_fee_ratio
        trade_notional_ratio_np[t, ne_idx] = trade_notional_ratio
        group_returns_np[t, ne_idx] = net_ret

        # 更新 prev_end_amounts：期末持仓 = 买入后实际投入 × 品种收益
        # 实际投入 = target - buy_open_fees（已有持仓不受买入费影响）
        new_prev = (ne_target - buy_open_fees) * (1.0 + ne_ret[np.newaxis, :])
        new_prev[ne_cc == 0] = 0.0
        prev_end_amounts[ne_idx] = new_prev

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
        return test_by_group_single_factor(
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
        )

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
