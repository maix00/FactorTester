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
    rebalance_mode: str = "each_period",
) -> Tuple[Any, Any, pd.DataFrame, np.ndarray, list]:
    """Single-factor group test core logic.

    rebalance_mode:
      - "each_period":   每期等权再平衡 — 所有组成员每期重新平分资金（默认）
      - "buy_and_hold":  组内持仓不动 — 只在产品进出组时才买卖
      - "recycle":       资金回收再分配 — 新产品用退出产品的资金，不够再等权补足

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

    # ── 首尾全 NaN 行截断 ──
    # 数据首尾可能存在所有品种均为 NaN 的行（数据尚未开始或已结束），截断之
    _all_nan = np.all(np.isnan(table_np), axis=1)  # (T,) — 整行全 NaN
    _first_valid = int(np.argmin(_all_nan))  # 第一个非全NaN行（argmin找到第一个False=0）
    _last_valid = int(len(_all_nan) - 1 - np.argmin(_all_nan[::-1]))  # 最后一个非全NaN行

    if _all_nan.all():
        raise ValueError(f"{factor.alias}: 因子值序列全部为 NaN，无法进行分组测试。")

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

    # ── 按列的首部 NaN 填充（仅用于多时段品种检测，不覆盖 table_np）──
    # 某些品种在中途才上市，首部全为 NaN，不应被误判为"多时段品种"
    # 策略：对每列找到第一个有效值的行号，将其之前的 NaN 填 0.0
    not_nan = ~np.isnan(table_np)                   # (T, P)
    first_valid = np.argmax(not_nan, axis=0)          # (P,)  每列第一个非NaN行号；全NaN列=0
    col_has_any = np.asarray(not_nan.any(axis=0), dtype=bool)  # (P,)  哪些列有至少一个有效值，强制为array避免P=1时标量化
    row_idx = np.arange(T, dtype=int)[:, np.newaxis]  # (T, 1)
    head_mask = (row_idx < first_valid[np.newaxis, :]) & col_has_any[np.newaxis, :]  # (T, P)
    table_filled_np = np.where(head_mask, 0.0, table_np)

    # ── 多时段品种检测 ──
    # 使用填充后的 table_filled_np，排除首部未上市品种的干扰
    _mixed_mask = np.any(np.isnan(table_filled_np), axis=1) & (~np.all(np.isnan(table_filled_np), axis=1))
    multi_session_active = bool(_mixed_mask.any())
    if multi_session_active:
        # 统计真正缺失的品种（排除首部未上市部分）
        _after_head_nan = np.isnan(table_filled_np) & ~head_mask          # (T, P) 只保留首部之后的NaN
        _missing_cols = np.where(np.any(_after_head_nan, axis=0))[0]       # 哪些列在首部之后有NaN
        _missing_names = [str(valid_cols[i]) for i in _missing_cols]
        print(
            f"[INFO] {factor.alias}: 检测到 {int(_mixed_mask.sum())}/{T} 期存在部分品种缺失信号 "
            f"（{len(_missing_names)} 个品种有缺失：{', '.join(_missing_names[:5])}"
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
            # 多时段策略：信号缺失品种保留在当前组中，不被踢出
            # isnan_fac=True 表示该品种本期无信号 → 保留
            carry_members = current_members & (~isbad_ret[np.newaxis, :])
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
            for slot, g in enumerate(active_groups):
                assigned = new_idx[bucket_idx == slot]
                current_members[g, assigned] = True

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

    group_gross_returns_np = np.zeros((T, n_groups), dtype=float)
    fee_costs_np = np.zeros((T, n_groups), dtype=float)
    group_returns_np = np.zeros((T, n_groups), dtype=float)

    _VALID_MODES = frozenset({"each_period", "buy_and_hold", "recycle"})
    if rebalance_mode not in _VALID_MODES:
        raise ValueError(f"rebalance_mode must be one of {sorted(_VALID_MODES)}, got {rebalance_mode!r}")

    # ── 逐期矩阵化收益计算 ──
    # 所有组并行处理：prev_end_amounts: (n_groups, P), wealth: (n_groups,)
    wealth = np.ones(n_groups, dtype=float)
    prev_end_amounts = np.zeros((n_groups, P), dtype=float)

    # 多时段：预计算每期哪些品种有因子信号
    fac_has_signal = ~np.isnan(table_np)  # (T, P)

    # 记录每期多时段策略触发的组（用于报告）
    multi_session_triggered_count = 0

    for t in range(T):
        curr_mask_all = membership_np[t]          # (n_groups, P) bool
        curr_count_all = member_counts[t]          # (n_groups,) float
        wealth_before_trade = wealth.copy()        # (n_groups,)

        # ── 本期是否触发多时段逻辑 ──
        # 判断标准：当期存在部分品种有信号、部分品种无信号（混合行）
        has_signal_t = fac_has_signal[t]           # (P,) bool
        is_mixed_t = multi_session_active and has_signal_t.any() and (~has_signal_t).any()

        # ── 计算 target_amounts: (n_groups, P) ──
        target_amounts = np.zeros((n_groups, P), dtype=float)

        # --- 空组：curr_count == 0 ---
        empty_mask = curr_count_all == 0           # (n_groups,)
        non_empty_mask = ~empty_mask

        if empty_mask.any():
            # 空组清仓，卖出所有 prev_end_amounts
            sell_empty = prev_end_amounts[empty_mask]  # (n_empty, P)
            fee_empty = (sell_empty * close_fee_vec[np.newaxis, :]).sum(axis=1)  # (n_empty,)
            fee_ratio_empty = np.where(wealth_before_trade[empty_mask] > 0,
                                       fee_empty / wealth_before_trade[empty_mask], 0.0)
            net_ret_empty = (1.0 - fee_ratio_empty) * (1.0 + 0.0) - 1.0
            wealth[empty_mask] = wealth_before_trade[empty_mask] * (1.0 + net_ret_empty)
            group_gross_returns_np[t, empty_mask] = 0.0
            fee_costs_np[t, empty_mask] = fee_ratio_empty
            group_returns_np[t, empty_mask] = net_ret_empty
            prev_end_amounts[empty_mask] = 0.0

        if not non_empty_mask.any():
            continue

        # --- 非空组 ---
        ne_idx = np.where(non_empty_mask)[0]

        if is_mixed_t:
            # ===== 多时段品种策略（逐期自适应）=====
            multi_session_triggered_count += 1

            prev_mask_all = prev_end_amounts > 0    # (n_groups, P) — 上期持仓

            # 对非空组逐组计算（因涉及跨品种资金转移，需知道每组的 staying/exiting/entering）
            for g in ne_idx:
                cm = curr_mask_all[g]                # (P,) — 当期成员
                pm = prev_mask_all[g]                # (P,) — 上期持仓
                pa = prev_end_amounts[g]             # (P,) — 上期金额
                wb = wealth_before_trade[g]

                staying = cm & pm
                exiting = pm & (~cm)
                entering = cm & (~pm)

                # 退出产品中：有信号的卖出，无信号的保留金额
                exiting_sig = exiting & has_signal_t
                exiting_nosig = exiting & (~has_signal_t)

                # 进入产品中：只有有信号的才真正进入
                entering_sig = entering & has_signal_t
                n_entering = int(entering_sig.sum())

                # 卖出有信号的退出产品（扣除手续费）
                sell_exit = pa * exiting_sig.astype(float)
                sell_gross = float(sell_exit.sum())
                sell_fee_exit = float((sell_exit * close_fee_vec).sum())
                recycled = max(0.0, sell_gross - sell_fee_exit)

                tg = np.zeros(P, dtype=float)

                # 无信号的退出产品：保留金额
                if exiting_nosig.any():
                    tg += pa * exiting_nosig.astype(float)
                # 留存产品：保留金额
                if staying.any():
                    tg += pa * staying.astype(float)
                # 新进入者：用回收资金买入
                if n_entering > 0 and recycled > 0:
                    tg += entering_sig.astype(float) * (recycled / n_entering)

                # 归一化到 wealth_before_trade
                total_tg = float(tg.sum())
                if total_tg > 0 and abs(total_tg - wb) > 1e-12:
                    tg *= (wb / total_tg)

                target_amounts[g] = tg

        elif rebalance_mode == "each_period":
            # 每期等权：所有组成员重新平分资金
            for g in ne_idx:
                cm = curr_mask_all[g]
                cc = curr_count_all[g]
                if cc > 0:
                    target_amounts[g] = cm.astype(float) * (wealth_before_trade[g] / cc)

        elif rebalance_mode == "buy_and_hold":
            # 持仓不动：只在进出时调仓
            prev_mask_all = prev_end_amounts > 0
            for g in ne_idx:
                cm = curr_mask_all[g]
                pm = prev_mask_all[g]
                pa = prev_end_amounts[g]
                wb = wealth_before_trade[g]
                cc = curr_count_all[g]

                staying = cm & pm
                exiting = pm & (~cm)
                entering = cm & (~pm)
                n_ent = int(entering.sum())

                sell_exit = pa * exiting.astype(float)
                released = float(sell_exit.sum())

                tg = np.zeros(P, dtype=float)
                if staying.any():
                    tg += pa * staying.astype(float)
                if n_ent > 0 and released > 0:
                    tg += entering.astype(float) * (released / n_ent)
                elif n_ent > 0 and wb > 0:
                    tg = cm.astype(float) * (wb / cc)

                total_tg = float(tg.sum())
                if total_tg > 0 and abs(total_tg - wb) > 1e-12:
                    tg *= (wb / total_tg)

                target_amounts[g] = tg

        elif rebalance_mode == "recycle":
            # 资金回收再分配
            prev_mask_all = prev_end_amounts > 0
            for g in ne_idx:
                cm = curr_mask_all[g]
                pm = prev_mask_all[g]
                pa = prev_end_amounts[g]
                wb = wealth_before_trade[g]
                cc = curr_count_all[g]

                staying = cm & pm
                exiting = pm & (~cm)
                entering = cm & (~pm)
                n_ent = int(entering.sum())
                n_stay = int(staying.sum())

                sell_exit = pa * exiting.astype(float)
                recycled = float(sell_exit.sum())

                tg = np.zeros(P, dtype=float)
                if n_ent > 0:
                    if recycled > 0:
                        tg += entering.astype(float) * (recycled / n_ent)
                    else:
                        tg += entering.astype(float) * (wb / cc)
                if n_stay > 0:
                    tg += pa * staying.astype(float)

                total_tg = float(tg.sum())
                if total_tg > 0 and abs(total_tg - wb) > 1e-12:
                    tg *= (wb / total_tg)

                target_amounts[g] = tg

        else:
            raise ValueError(f"Unknown rebalance_mode: {rebalance_mode!r}")

        # ── 统一计算买卖/手续费/收益（矩阵运算，所有非空组）──
        ne_target = target_amounts[ne_idx]           # (n_ne, P)
        ne_prev = prev_end_amounts[ne_idx]           # (n_ne, P)
        ne_wb = wealth_before_trade[ne_idx]          # (n_ne,)
        ne_cc = curr_count_all[ne_idx]               # (n_ne,)
        ne_ret = returns_filled[t]                   # (P,) — 本期收益

        buy = np.clip(ne_target - ne_prev, 0.0, None)   # (n_ne, P)
        sell = np.clip(ne_prev - ne_target, 0.0, None)  # (n_ne, P)
        fee = (buy * open_fee_vec[np.newaxis, :] + sell * close_fee_vec[np.newaxis, :]).sum(axis=1)  # (n_ne,)
        fee_ratio = fee / ne_wb

        # 总收益
        gross = (ne_target / ne_wb[:, np.newaxis] * ne_ret[np.newaxis, :]).sum(axis=1)  # (n_ne,)
        net_ret = (1.0 - fee_ratio) * (1.0 + gross) - 1.0

        wealth[ne_idx] = ne_wb * (1.0 + net_ret)
        group_gross_returns_np[t, ne_idx] = gross
        fee_costs_np[t, ne_idx] = fee_ratio
        group_returns_np[t, ne_idx] = net_ret

        # 更新 prev_end_amounts
        ne_cc_safe = np.where(ne_cc > 0, ne_cc, 1.0)
        new_prev = ne_target * (1.0 + ne_ret[np.newaxis, :]) * (1.0 - fee_ratio[:, np.newaxis])
        new_prev[ne_cc == 0] = 0.0
        prev_end_amounts[ne_idx] = new_prev

    if multi_session_active:
        print(f"[INFO] {factor.alias}: 多时段品种策略在 {multi_session_triggered_count}/{T} 期中触发。")

    tester._last_fee_costs_np = fee_costs_np
    tester._last_group_gross_returns_np = group_gross_returns_np
    tester._last_group_returns_np = group_returns_np
    tester._last_group_products = products_dict  # {g: {t_index: [product_names]}}
    tester._last_group_valid_cols = valid_cols    # 品种名称列表（按列顺序）
    tester._last_group_index_list = index_list
    tester._last_multi_session_active = multi_session_active  # 是否启用了多时段策略

    returns_dict = {g: {index_list[t]: float(group_returns_np[t, g]) for t in range(T)} for g in range(n_groups)}

    bad = np.isnan(group_returns_np) | np.isinf(group_returns_np) | (group_returns_np <= -1.0)
    cum_rets_filled = np.where(bad, 0.0, group_returns_np)
    cumulative_returns_np = np.cumprod(1 + cum_rets_filled, axis=0)

    avg_turnover = np.zeros(n_groups, dtype=float)
    for g in range(n_groups):
        turnovers = []
        for t in range(1, T):
            prev = membership_np[t - 1, g]
            curr = membership_np[t, g]
            prev_count = int(prev.sum())
            curr_count = int(curr.sum())
            if curr_count == 0 and prev_count == 0:
                continue
            avg_count = (prev_count + curr_count) / 2.0
            if avg_count == 0:
                continue
            changed = int((prev ^ curr).sum()) / 2.0
            turnovers.append(changed / avg_count)
        avg_turnover[g] = float(np.mean(turnovers)) if turnovers else 0.0

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
    tester._last_group_report_df = report_df.copy()
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
    rebalance_mode: str = "each_period",
    **kwargs,
) -> Tuple[Any, Any, pd.DataFrame, np.ndarray, list]:
    """Run group test for one or more factors.

    rebalance_mode:
      - \"each_period\":   每期等权再平衡（默认）
      - \"buy_and_hold\":  组内持仓不动
      - \"recycle\":       资金回收再分配
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
