"""Group test core implementation."""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from tqdm import tqdm

from Settings import factor_info_path
from tools.data.DataFreq import DataFreq
from tools.factors import Factor
from tools.factors.FactorTester import _align_ts_to_index, _extract_signal_index
from tools.factors.Parameters import FactorNextPeriodReturns


def ensure_factor_returns(
    tester: Any,
    factor: Factor,
    returns_col: FactorNextPeriodReturns = FactorNextPeriodReturns.NEXT_OPEN_TO_OPEN_ADJUSTED,
) -> pd.DataFrame:
    """Ensure tester.factor_returns has the raw RE returns table for factor."""
    desired_freq = tester.factor_return_freqs.get(factor)
    if desired_freq is None:
        desired_freq = factor.freq
    desired_key = getattr(desired_freq, "name", None) or str(desired_freq)
    returns_col_key = returns_col.value.name if isinstance(returns_col, FactorNextPeriodReturns) else str(returns_col)

    cached = tester.factor_returns.get(factor, pd.DataFrame())
    cached_freq = getattr(factor, "_return_freq_cached", None)
    cached_col = getattr(factor, "_return_col_cached", None)
    freq_matches = cached_freq == desired_key or (cached_freq is None and factor not in tester.factor_return_freqs)
    col_matches = cached_col == returns_col_key or cached_col is None
    if isinstance(cached, pd.DataFrame) and not cached.empty and freq_matches and col_matches:
        object.__setattr__(factor, "_return_freq_cached", desired_key)
        object.__setattr__(factor, "_return_col_cached", returns_col_key)
        return cached

    if factor.table is None or factor.table.empty:
        factor.evaluate(tester.products)

    from tools.factors.FactorFamily import CrossSectionIC

    try:
        rf_value = desired_freq.value if isinstance(desired_freq, DataFreq) else desired_freq
    except Exception:
        rf_value = factor.freq.value

    data_col = returns_col.value if isinstance(returns_col, FactorNextPeriodReturns) else returns_col
    shift = 0 if data_col.name.startswith("OPEN") else 1

    ic_family = CrossSectionIC()
    ic_factor = ic_family.get_factor(
        FE=factor,
        SC=data_col,
        RF=rf_value,
        S=shift,
        Lag=0,
        F=factor.freq.value,
    )
    ic_factor.clear()
    ic_factor.evaluate(tester.products, freq=factor._source_freq)

    raw_returns = ic_factor.get_intermediate("RE")
    if not isinstance(raw_returns, pd.DataFrame) or raw_returns.empty:
        raise ValueError(f"{factor.alias}: 无法生成收益率数据")
    tester.factor_returns[factor] = raw_returns
    object.__setattr__(factor, "_return_freq_cached", desired_key)
    object.__setattr__(factor, "_return_col_cached", returns_col_key)
    return raw_returns


def align_table_for_group(factor: Factor, raw_table: pd.DataFrame) -> pd.DataFrame:
    """Temporarily project a raw FE/RE table onto factor signal timestamps."""
    from tools.factors.FactorExpr import SignalAlign, signal_align

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
        return raw_table.copy(deep=False)
    return signal_align(
        raw_table,
        signal_node.signal_freq,
        basepoint=signal_node.basepoint,
        daily_basepoint=signal_node.daily_basepoint,
        end_session_skip=signal_node.end_session_skip,
        end_session_gap=signal_node.end_session_gap,
    )


def get_factor_table_for_group(tester: Any, factor: Factor) -> pd.DataFrame:
    """Get the factor exposure table for group testing, reusing raw IC FE when present."""
    raw_fe = getattr(factor, "_ic_fe_intermediate", None)
    if not isinstance(raw_fe, pd.DataFrame) or raw_fe.empty:
        raw_fe = tester.factor_tables.get(factor)
    if isinstance(raw_fe, pd.DataFrame) and not raw_fe.empty:
        if isinstance(raw_fe.index, pd.MultiIndex) and any(str(n).startswith("_SIGNAL") for n in raw_fe.index.names):
            return raw_fe.copy(deep=False)
        return align_table_for_group(factor, raw_fe)

    if factor.table is None or factor.table.empty:
        factor.evaluate(tester.products)
    return factor.table.copy(deep=False)


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
) -> Tuple[Any, Any, pd.DataFrame, np.ndarray, list]:
    """Single-factor group test core logic."""
    start_date = pd.to_datetime(time_range[0]) if time_range is not None else tester.start_date
    end_date = pd.to_datetime(time_range[1]) if time_range is not None else tester.end_date

    raw_returns = ensure_factor_returns(tester, factor, returns_col=returns_col)
    returns_for_group = align_table_for_group(factor, raw_returns)
    assert not returns_for_group.empty

    table_src = get_factor_table_for_group(tester, factor).copy(deep=False)
    returns_src = returns_for_group.copy(deep=False)
    table_src.index = _extract_signal_index(table_src.index)
    returns_src.index = _extract_signal_index(returns_src.index)
    if start_date is not None:
        _sd = _align_ts_to_index(start_date, table_src.index)
        table_src = table_src[table_src.index >= _sd]
        _sd = _align_ts_to_index(start_date, returns_src.index)
        returns_src = returns_src[returns_src.index >= _sd]
    if end_date is not None:
        _ed = _align_ts_to_index(end_date, table_src.index)
        table_src = table_src[table_src.index <= _ed]
        _ed = _align_ts_to_index(end_date, returns_src.index)
        returns_src = returns_src[returns_src.index <= _ed]

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
    valid_cols = [c for c in all_cols if c in set(ret_cols)]
    if not valid_cols:
        raise ValueError(
            f"{factor.alias}: 因子表和收益表没有共同品种列；"
            f"factor_cols={len(all_cols)}, returns_cols={len(ret_cols)}"
        )

    table_np = table_src[valid_cols].to_numpy(dtype=float)
    returns_np = returns_src[valid_cols].to_numpy(dtype=float)
    index_list = list(table_src.index)
    T = len(index_list)

    n_names = {i: n_groups_name.get(i, "group_" + str(i)) for i in range(n_groups)}

    P = len(valid_cols)
    membership_np = np.zeros((T, n_groups, P), dtype=bool)
    current_members = np.zeros((n_groups, P), dtype=bool)

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
        g: {index_list[t]: [valid_cols[i] for i in np.where(membership_np[t, g])[0]]
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

    for g in range(n_groups):
        wealth = 1.0
        prev_end_amounts = np.zeros(P, dtype=float)
        for t in range(T):
            curr_mask = membership_np[t, g]
            curr_count = int(member_counts[t, g])
            wealth_before_trade = float(wealth)

            if wealth_before_trade <= 0:
                prev_end_amounts = np.zeros(P, dtype=float)
                continue

            if curr_count > 0:
                target_amounts = curr_mask.astype(float) * (wealth_before_trade / curr_count)
            else:
                target_amounts = np.zeros(P, dtype=float)

            buy_amounts = np.clip(target_amounts - prev_end_amounts, 0.0, None)
            sell_amounts = np.clip(prev_end_amounts - target_amounts, 0.0, None)
            fee_amount = float((buy_amounts * open_fee_vec + sell_amounts * close_fee_vec).sum())
            fee_ratio = fee_amount / wealth_before_trade

            if curr_count > 0:
                gross_ret = float((target_amounts / wealth_before_trade * returns_filled[t]).sum())
            else:
                gross_ret = 0.0

            net_ret = (1.0 - fee_ratio) * (1.0 + gross_ret) - 1.0
            wealth = wealth_before_trade * (1.0 + net_ret)

            group_gross_returns_np[t, g] = gross_ret
            fee_costs_np[t, g] = fee_ratio
            group_returns_np[t, g] = net_ret

            if curr_count > 0:
                prev_end_amounts = target_amounts * (1.0 + returns_filled[t]) * (1.0 - fee_ratio)
            else:
                prev_end_amounts = np.zeros(P, dtype=float)

    tester._last_fee_costs_np = fee_costs_np
    tester._last_group_gross_returns_np = group_gross_returns_np

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
    for idx in range(n_groups):
        r = group_returns_np[mask_report, idx]

        def _metrics(arr: np.ndarray) -> dict:
            s = pd.Series(arr).dropna()
            cum = (1 + s).cumprod()
            n = len(s)
            total_ret = (cum.iloc[-1] - 1) * 100 if n > 0 else 0
            annual_ret = (cum.iloc[-1] ** (252 / n) - 1) * 100 if n > 1 else 0
            vol = s.std() * np.sqrt(252) * 100
            sharpe = (s.mean() * 252) / (s.std() * np.sqrt(252)) if s.std() != 0 else 0
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

    tester.factor_reports[factor] = report_df
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
    **kwargs,
) -> Tuple[Any, Any, pd.DataFrame, np.ndarray, list]:
    """Run group test for one or more factors."""
    factors = [factors] if isinstance(factors, Factor) else (factors if factors is not None else tester.factors)

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

