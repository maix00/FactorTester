"""Detail analytics for one group from the latest group-test run."""
from __future__ import annotations

from collections import Counter
from typing import Any

import numpy as np
import pandas as pd
from tools.factors.FactorTester import _signal_time
from tools.products.product_utils import product_display_name


def _safe_bool(obj) -> bool:
    """安全求布尔值，避免 numpy 数组的 ambiguous truth value 错误。"""
    if obj is None:
        return False
    if isinstance(obj, np.ndarray):
        return bool(obj.size > 0)
    return bool(obj)


def build_group_detail(
    group_index: int,
    products_by_group: dict,
    group_returns_np: np.ndarray,
    index_list: list,
    metrics: dict | None = None,
    product_gross_contrib_np: np.ndarray | None = None,
    valid_cols: list | None = None,
    group_gross_returns_np: np.ndarray | None = None,
    trade_notional_ratio_np: np.ndarray | None = None,
    fee_costs_np: np.ndarray | None = None,
    open_fee_vec: np.ndarray | None = None,
    close_fee_vec: np.ndarray | None = None,
    close_today_fee_vec: np.ndarray | None = None,
) -> dict[str, Any]:
    returns = np.asarray(group_returns_np[:, group_index], dtype=float)
    clean_returns = returns[np.isfinite(returns)]
    group_products = products_by_group.get(group_index, {})
    product_fee_rates = _build_product_fee_rates(valid_cols, open_fee_vec, close_fee_vec, close_today_fee_vec)
    total_periods = max(len(index_list), 1)

    entry_counts = Counter()
    product_display_map = {}
    for products in group_products.values():
        for product in products:
            display = product_display_name(product)
            entry_counts.update([display['name']])
            product_display_map[display['name']] = display

    # 矩阵运算：每个产品在组内每期的毛贡献，均值收益 = sum(contrib) / count(非零期数)
    if product_gross_contrib_np is not None and valid_cols:
        contrib_g = np.asarray(product_gross_contrib_np[:, group_index, :], dtype=float)  # (T, P)
        contrib_sums = np.nansum(contrib_g, axis=0)  # (P,)
        contrib_counts = np.sum(np.abs(contrib_g) > 0, axis=0)  # (P,) 出现次数
        with np.errstate(invalid='ignore'):
            contrib_means = np.divide(contrib_sums, contrib_counts)  # (P,)
        contrib_means[np.isnan(contrib_means)] = 0.0
        # 构建 product_name → mean_return 映射
        mean_return_by_name = {}
        for idx, product in enumerate(valid_cols):
            name = product_display_name(product)['name']
            mean_return_by_name[name] = float(contrib_means[idx])
    else:
        mean_return_by_name = {}

    entry_frequency = []
    for product, count in entry_counts.most_common():
        display = dict(product_display_map.get(product, {'name': product, 'desc': product}))
        display['fee'] = product_fee_rates.get(product)
        mean_ret = mean_return_by_name.get(product)
        entry_frequency.append({
            'product': display,
            'count': count,
            'frequency': count / total_periods,
            'mean_return': mean_ret,
        })

    periods = []
    cumulative_return = 1.0
    return_series = []
    for row_idx, idx_entry in enumerate(index_list):
        value = returns[row_idx]
        if not np.isfinite(value):
            continue
        cumulative_return *= 1.0 + float(value)
        return_series.append({
            'timestamp': pd.Timestamp(_signal_time(idx_entry)).isoformat(),
            'return': float(value),
            'cumulative_return': cumulative_return,
        })
        periods.append({
            'timestamp': pd.Timestamp(_signal_time(idx_entry)).isoformat(),
            'return': float(value),
            'products': [_display_with_fee(product, product_fee_rates) for product in group_products.get(idx_entry, [])],
        })
    periods_desc = sorted(periods, key=lambda item: item['return'], reverse=True)
    positive_run_analysis = _build_positive_run_analysis(return_series)
    intraday_analysis = _build_intraday_analysis(return_series)
    daily_analysis = _build_daily_analysis(return_series)
    calendar_analysis = _build_calendar_analysis(return_series)
    holding_analysis = _build_holding_analysis(group_products, index_list)
    capacity_analysis = _build_capacity_analysis(group_products, index_list)
    rolling_analysis = _build_rolling_analysis(return_series)
    tradability_analysis = _build_tradability_analysis(
        group_index,
        group_gross_returns_np,
        trade_notional_ratio_np,
        fee_costs_np,
    )
    period_robustness = _build_period_robustness(return_series)
    product_analysis = _build_product_analysis(group_index, product_gross_contrib_np, valid_cols, product_fee_rates)
    robustness_summary = _build_robustness_summary(
        positive_run_analysis,
        daily_analysis,
        period_robustness,
        product_analysis,
        calendar_analysis,
        holding_analysis,
        tradability_analysis,
        capacity_analysis,
        rolling_analysis,
    )

    if clean_returns.size:
        hist_counts, hist_edges = np.histogram(clean_returns, bins=min(20, max(5, int(np.sqrt(clean_returns.size)))))
        histogram = [
            {
                'left': float(hist_edges[idx]),
                'right': float(hist_edges[idx + 1]),
                'count': int(count),
            }
            for idx, count in enumerate(hist_counts)
        ]
        quantiles = {
            key: float(value)
            for key, value in zip(
                ('p05', 'p25', 'p50', 'p75', 'p95'),
                np.quantile(clean_returns, [0.05, 0.25, 0.50, 0.75, 0.95]),
            )
        }
    else:
        histogram = []
        quantiles = {}

    return {
        'group_index': group_index,
        'summary': metrics or {},
        'entry_frequency': entry_frequency,
        'top_periods': periods_desc[:10],
        'bottom_periods': list(reversed(periods_desc[-10:])),
        'distribution': {
            'histogram': histogram,
            'quantiles': quantiles,
            'period_count': int(clean_returns.size),
        },
        'return_series': return_series,
        'positive_run_analysis': positive_run_analysis,
        'intraday_analysis': intraday_analysis,
        'daily_analysis': daily_analysis,
        'calendar_analysis': calendar_analysis,
        'holding_analysis': holding_analysis,
        'capacity_analysis': capacity_analysis,
        'rolling_analysis': rolling_analysis,
        'tradability_analysis': tradability_analysis,
        'period_robustness': period_robustness,
        'robustness_summary': robustness_summary,
        'product_analysis': product_analysis,
        'explanations': _build_explanations(
            positive_run_analysis,
            daily_analysis,
            period_robustness,
            product_analysis,
            calendar_analysis,
            holding_analysis,
            tradability_analysis,
            capacity_analysis,
            rolling_analysis,
        ),
    }


def _build_positive_run_analysis(return_series: list[dict[str, Any]]) -> dict[str, Any]:
    runs = []
    current = []
    for row in return_series:
        if row['return'] > 0:
            current.append(row)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)

    positive_runs = []
    for rows in runs:
        run_return = float(np.prod([1.0 + row['return'] for row in rows]) - 1.0)
        positive_runs.append({
            'start': rows[0]['timestamp'],
            'end': rows[-1]['timestamp'],
            'period_count': len(rows),
            'return': run_return,
        })
    positive_runs.sort(key=lambda item: item['return'], reverse=True)

    total_positive_run_return = sum(max(item['return'], 0.0) for item in positive_runs)
    top1 = positive_runs[:1]
    top3 = positive_runs[:3]

    def _without(selected: list[dict[str, Any]]) -> float:
        excluded = {(item['start'], item['end']) for item in selected}
        wealth = 1.0
        in_excluded = False
        current_key = None
        for row in return_series:
            row_ts = row['timestamp']
            if not in_excluded:
                for key in excluded:
                    if row_ts == key[0]:
                        in_excluded = True
                        current_key = key
                        break
            if in_excluded and current_key is not None:
                if row_ts == current_key[1]:
                    in_excluded = False
                    current_key = None
                continue
            wealth *= 1.0 + row['return']
        return wealth - 1.0

    top1_ratio = (top1[0]['return'] / total_positive_run_return) if (top1 and total_positive_run_return > 0) else None
    top3_ratio = (sum(item['return'] for item in top3) / total_positive_run_return) if total_positive_run_return > 0 else None
    without_top1 = _without(top1) if top1 else None
    without_top3 = _without(top3) if top3 else None
    concentrated = bool(
        (top1_ratio is not None and top1_ratio >= 0.5 and without_top1 is not None and without_top1 <= 0)
        or (top3_ratio is not None and top3_ratio >= 0.8 and without_top3 is not None and without_top3 <= 0)
    )
    return {
        'run_count': len(positive_runs),
        'top_runs': positive_runs[:5],
        'top1_positive_contribution_ratio': top1_ratio,
        'top3_positive_contribution_ratio': top3_ratio,
        'return_without_top1_run': without_top1,
        'return_without_top3_runs': without_top3,
        'is_concentrated': concentrated,
    }


def _build_intraday_analysis(return_series: list[dict[str, Any]]) -> dict[str, Any]:
    if not return_series:
        return {'rows': [], 'top_times': [], 'bottom_times': []}

    df = pd.DataFrame(return_series)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['time'] = df['timestamp'].dt.strftime('%H:%M')
    grouped = df.groupby('time')['return'].agg(count='count', mean='mean', sum='sum', std='std').reset_index()
    grouped['t_like'] = grouped.apply(
        lambda row: float(row['mean'] / row['std'] * np.sqrt(row['count']))
        if row['std'] and np.isfinite(row['std']) else None,
        axis=1,
    )

    rows = [
        {
            'time': str(row['time']),
            'count': int(row['count']),
            'mean': float(row['mean']),
            'sum': float(row['sum']),
            'std': float(row['std']) if np.isfinite(row['std']) else None,
            't_like': float(row['t_like']) if row['t_like'] is not None and np.isfinite(row['t_like']) else None,
        }
        for _, row in grouped.iterrows()
    ]
    top_times = sorted(rows, key=lambda item: item['sum'], reverse=True)[:10]
    bottom_times = sorted(rows, key=lambda item: item['sum'])[:10]
    return {
        'rows': rows,
        'top_times': top_times,
        'bottom_times': bottom_times,
    }


def _build_daily_analysis(return_series: list[dict[str, Any]]) -> dict[str, Any]:
    if not return_series:
        return {'rows': [], 'top_days': [], 'bottom_days': [], 'return_without_top1_day': None, 'return_without_top5_days': None}
    df = pd.DataFrame(return_series)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['date'] = df['timestamp'].dt.strftime('%Y-%m-%d')
    grouped = df.groupby('date')['return'].agg(count='count', sum='sum', mean='mean').reset_index()
    rows = [
        {
            'date': str(row['date']),
            'count': int(row['count']),
            'sum': float(row['sum']),
            'mean': float(row['mean']),
        }
        for _, row in grouped.iterrows()
    ]
    top_days = sorted(rows, key=lambda item: item['sum'], reverse=True)
    bottom_days = sorted(rows, key=lambda item: item['sum'])

    def _without(days: list[dict[str, Any]]) -> float | None:
        excluded = {day['date'] for day in days}
        subset = df.loc[~df['date'].isin(excluded), 'return']
        if subset.empty:
            return None
        return float(np.prod(1.0 + subset.to_numpy(dtype=float)) - 1.0)

    return {
        'rows': rows,
        'top_days': top_days[:10],
        'bottom_days': bottom_days[:10],
        'return_without_top1_day': _without(top_days[:1]),
        'return_without_top5_days': _without(top_days[:5]),
    }


def _build_period_robustness(return_series: list[dict[str, Any]]) -> dict[str, Any]:
    if not return_series:
        return {}
    returns = np.asarray([row['return'] for row in return_series], dtype=float)
    order = np.argsort(-returns)

    def _without_top_ratio(ratio: float) -> dict[str, Any]:
        n_remove = max(1, int(np.ceil(len(returns) * ratio)))
        keep_mask = np.ones(len(returns), dtype=bool)
        keep_mask[order[:n_remove]] = False
        kept = returns[keep_mask]
        return {
            'removed_count': int(n_remove),
            'remaining_return': float(np.prod(1.0 + kept) - 1.0) if kept.size else None,
        }

    return {
        'without_top1pct': _without_top_ratio(0.01),
        'without_top5pct': _without_top_ratio(0.05),
    }


def _build_robustness_summary(
    positive_runs: dict[str, Any],
    daily_analysis: dict[str, Any],
    period_robustness: dict[str, Any],
    product_analysis: dict[str, Any],
    calendar_analysis: dict[str, Any],
    holding_analysis: dict[str, Any],
    tradability_analysis: dict[str, Any],
    capacity_analysis: dict[str, Any],
    rolling_analysis: dict[str, Any],
) -> dict[str, Any]:
    issues = []
    if positive_runs.get('is_concentrated'):
        issues.append('positive_runs')
    if daily_analysis.get('return_without_top1_day') is not None and daily_analysis['return_without_top1_day'] <= 0:
        issues.append('top_day')
    top5 = period_robustness.get('without_top5pct', {})
    if top5.get('remaining_return') is not None and top5['remaining_return'] <= 0:
        issues.append('top_periods')
    if product_analysis.get('is_concentrated'):
        issues.append('products')
    if calendar_analysis.get('month_concentration_ratio') is not None and calendar_analysis['month_concentration_ratio'] >= 0.5:
        issues.append('months')
    if holding_analysis.get('median_periods') is not None and holding_analysis['median_periods'] <= 1:
        issues.append('short_holding')
    if tradability_analysis.get('break_even_fee') is not None and tradability_analysis['break_even_fee'] <= 0.0002:
        issues.append('low_break_even_fee')
    if capacity_analysis.get('tiny_group_ratio') is not None and capacity_analysis['tiny_group_ratio'] >= 0.2:
        issues.append('tiny_groups')
    if rolling_analysis.get('negative_window_ratio') is not None and rolling_analysis['negative_window_ratio'] >= 0.5:
        issues.append('unstable_windows')
    return {
        'issues': issues,
        'is_fragile': bool(issues),
    }


def _build_product_analysis(
    group_index: int,
    product_gross_contrib_np: np.ndarray | None,
    valid_cols: list | None,
    product_fee_rates: dict[str, dict[str, float]] | None = None,
) -> dict[str, Any]:
    if product_gross_contrib_np is None or not _safe_bool(valid_cols):
        return {'rows': [], 'top_products': [], 'bottom_products': [], 'is_concentrated': False}
    contrib = np.asarray(product_gross_contrib_np[:, group_index, :], dtype=float)
    sums = np.nansum(contrib, axis=0)
    counts = np.sum(np.abs(contrib) > 0, axis=0)
    rows = []
    for idx, product in enumerate(valid_cols):
        display = product_display_name(product)
        display['fee'] = (product_fee_rates or {}).get(display['name'])
        rows.append({
            'product': display,
            'active_period_count': int(counts[idx]),
            'gross_contribution': float(sums[idx]),
            'mean_active_contribution': float(sums[idx] / counts[idx]) if counts[idx] else None,
        })
    top_products = sorted(rows, key=lambda item: item['gross_contribution'], reverse=True)
    bottom_products = sorted(rows, key=lambda item: item['gross_contribution'])
    positive_total = sum(max(row['gross_contribution'], 0.0) for row in rows)
    top1_ratio = (top_products[0]['gross_contribution'] / positive_total) if top_products and positive_total > 0 else None
    top3_ratio = (
        sum(max(row['gross_contribution'], 0.0) for row in top_products[:3]) / positive_total
        if positive_total > 0 else None
    )
    return {
        'rows': rows,
        'top_products': top_products[:10],
        'bottom_products': bottom_products[:10],
        'top1_positive_contribution_ratio': top1_ratio,
        'top3_positive_contribution_ratio': top3_ratio,
        'is_concentrated': bool(
            (top1_ratio is not None and top1_ratio >= 0.5)
            or (top3_ratio is not None and top3_ratio >= 0.8)
        ),
    }


def _build_calendar_analysis(return_series: list[dict[str, Any]]) -> dict[str, Any]:
    if not return_series:
        return {'month_rows': [], 'day_rows': [], 'year_rows': [], 'month_concentration_ratio': None}
    df = pd.DataFrame(return_series)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['month'] = df['timestamp'].dt.strftime('%m')
    df['day'] = df['timestamp'].dt.strftime('%d')
    df['year'] = df['timestamp'].dt.strftime('%Y')

    def _rows(key: str) -> list[dict[str, Any]]:
        grouped = df.groupby(key)['return'].agg(count='count', sum='sum', mean='mean').reset_index()
        return [
            {
                key: str(row[key]),
                'count': int(row['count']),
                'sum': float(row['sum']),
                'mean': float(row['mean']),
            }
            for _, row in grouped.iterrows()
        ]

    month_rows = _rows('month')
    positive_month_total = sum(max(row['sum'], 0.0) for row in month_rows)
    top_month = max(month_rows, key=lambda row: row['sum'], default=None)
    month_ratio = (top_month['sum'] / positive_month_total) if top_month and positive_month_total > 0 else None
    return {
        'month_rows': sorted(month_rows, key=lambda row: row['sum'], reverse=True),
        'day_rows': sorted(_rows('day'), key=lambda row: row['sum'], reverse=True),
        'year_rows': sorted(_rows('year'), key=lambda row: row['sum'], reverse=True),
        'month_concentration_ratio': month_ratio,
    }


def _build_holding_analysis(group_products: dict, index_list: list) -> dict[str, Any]:
    runs = []
    active: dict[str, int] = {}
    for idx_entry in index_list:
        current = {product_display_name(product)['name'] for product in group_products.get(idx_entry, [])}
        for product in list(active):
            if product not in current:
                runs.append(active.pop(product))
        for product in current:
            active[product] = active.get(product, 0) + 1
    runs.extend(active.values())
    if not runs:
        return {'run_count': 0, 'mean_periods': None, 'median_periods': None, 'p95_periods': None}
    arr = np.asarray(runs, dtype=float)
    return {
        'run_count': int(arr.size),
        'mean_periods': float(np.mean(arr)),
        'median_periods': float(np.median(arr)),
        'p95_periods': float(np.quantile(arr, 0.95)),
    }


def _build_explanations(
    positive_runs: dict[str, Any],
    daily_analysis: dict[str, Any],
    period_robustness: dict[str, Any],
    product_analysis: dict[str, Any],
    calendar_analysis: dict[str, Any],
    holding_analysis: dict[str, Any],
    tradability_analysis: dict[str, Any],
    capacity_analysis: dict[str, Any],
    rolling_analysis: dict[str, Any],
) -> list[str]:
    lines = []
    if positive_runs.get('is_concentrated'):
        lines.append('收益明显依赖少数连续正收益段。')
    if daily_analysis.get('return_without_top1_day') is not None and daily_analysis['return_without_top1_day'] <= 0:
        lines.append('去掉贡献最高的单一交易日后，累计收益转为非正。')
    top5 = period_robustness.get('without_top5pct', {})
    if top5.get('remaining_return') is not None and top5['remaining_return'] <= 0:
        lines.append('去掉最好 5% 时段后，累计收益转为非正。')
    if product_analysis.get('is_concentrated'):
        lines.append('毛收益对少数产品较集中。')
    if calendar_analysis.get('month_concentration_ratio') is not None and calendar_analysis['month_concentration_ratio'] >= 0.5:
        lines.append('正收益在月份上存在集中。')
    if holding_analysis.get('median_periods') is not None and holding_analysis['median_periods'] <= 1:
        lines.append('持仓中位数仅 1 期，属于高周转信号。')
    if tradability_analysis.get('break_even_fee') is not None and tradability_analysis['break_even_fee'] <= 0.0002:
        lines.append('可承受的单边等比例成本较低，成本敏感。')
    if capacity_analysis.get('tiny_group_ratio') is not None and capacity_analysis['tiny_group_ratio'] >= 0.2:
        lines.append('较多期数组内样本偏少，结果可能受小样本影响。')
    if rolling_analysis.get('negative_window_ratio') is not None and rolling_analysis['negative_window_ratio'] >= 0.5:
        lines.append('滚动窗口中负收益占比较高，时间稳定性不足。')
    return lines


def _build_tradability_analysis(
    group_index: int,
    group_gross_returns_np: np.ndarray | None,
    trade_notional_ratio_np: np.ndarray | None,
    fee_costs_np: np.ndarray | None = None,
) -> dict[str, Any]:
    if group_gross_returns_np is None or trade_notional_ratio_np is None:
        return {}
    gross = np.asarray(group_gross_returns_np[:, group_index], dtype=float)
    notional = np.asarray(trade_notional_ratio_np[:, group_index], dtype=float)
    fee_cost = (
        np.asarray(fee_costs_np[:, group_index], dtype=float)
        if fee_costs_np is not None else np.full_like(gross, np.nan, dtype=float)
    )
    valid = np.isfinite(gross) & np.isfinite(notional)
    gross = gross[valid]
    notional = notional[valid]
    fee_cost = fee_cost[valid] if fee_cost.shape[0] == valid.shape[0] else np.asarray([], dtype=float)
    if gross.size == 0:
        return {}

    def _total_return(fee: float) -> float:
        net = (1.0 - fee * notional) * (1.0 + gross) - 1.0
        return float(np.prod(1.0 + net) - 1.0)

    low, high = 0.0, 0.05
    if _total_return(low) <= 0:
        break_even = 0.0
    elif _total_return(high) > 0:
        break_even = None
    else:
        for _ in range(60):
            mid = (low + high) / 2.0
            if _total_return(mid) > 0:
                low = mid
            else:
                high = mid
        break_even = high

    sensitivity = [
        {'fee': fee, 'total_return': _total_return(fee)}
        for fee in (0.0, 0.0001, 0.0002, 0.0003, 0.0005)
    ]
    return {
        'avg_trade_notional_ratio': float(np.mean(notional)),
        'median_trade_notional_ratio': float(np.median(notional)),
        'avg_actual_fee_cost': float(np.nanmean(fee_cost)) if fee_cost.size and np.isfinite(fee_cost).any() else None,
        'median_actual_fee_cost': float(np.nanmedian(fee_cost)) if fee_cost.size and np.isfinite(fee_cost).any() else None,
        'actual_fee_per_traded_notional': (
            float(np.nansum(fee_cost) / np.sum(notional))
            if fee_cost.size and np.isfinite(fee_cost).any() and np.sum(notional) > 0 else None
        ),
        'break_even_fee': break_even,
        'sensitivity': sensitivity,
    }


def _build_product_fee_rates(
    valid_cols: list | None,
    open_fee_vec: np.ndarray | None,
    close_fee_vec: np.ndarray | None,
    close_today_fee_vec: np.ndarray | None = None,
) -> dict[str, dict[str, float]]:
    """返回 {产品名: {open, close, close_today, close_yesterday, total, _is_real_fee}}。

    如果回测中所有品种费率均为 0（用户未设置），则从全局费率表获取真实费率并标记 _is_real_fee。
    """
    if not valid_cols or open_fee_vec is None or close_fee_vec is None:
        return {}
    open_rates = np.asarray(open_fee_vec, dtype=float)
    close_rates = np.asarray(close_fee_vec, dtype=float)
    close_today_rates = (
        np.asarray(close_today_fee_vec, dtype=float)
        if close_today_fee_vec is not None else close_rates
    )
    if len(valid_cols) != open_rates.shape[0] or len(valid_cols) != close_rates.shape[0]:
        return {}

    # 用户是否设置了费率
    user_has_fee = bool(np.any(open_rates > 0) or np.any(close_rates > 0))
    use_real_fee = not user_has_fee

    if use_real_fee:
        from sources.LocalCNFutures.FeeData import load_latest
        df_fees = load_latest()
        fee_by_code = {}
        if not df_fees.empty:
            for _, row in df_fees.iterrows():
                fee_by_code[str(row['variety_code']).upper()] = row

    rows = {}
    for idx, product in enumerate(valid_cols):
        display = product_display_name(product)
        if use_real_fee:
            code = str(product if isinstance(product, str) else getattr(product, 'name', product)).split('.')[0].upper()
            variety_fee = fee_by_code.get(code)
            if variety_fee is not None:
                o = float(variety_fee['open_ratio']) if pd.notna(variety_fee['open_ratio']) else 0.0
                c = float(variety_fee['close_ratio']) if pd.notna(variety_fee['close_ratio']) else 0.0
                ct = float(variety_fee['closetoday_ratio']) if pd.notna(variety_fee['closetoday_ratio']) else c
            else:
                o = c = ct = 0.0
        else:
            o = float(open_rates[idx])
            c = float(close_rates[idx])
            ct = float(close_today_rates[idx])
        rows[display['name']] = {
            'open': o,
            'close': c,
            'close_today': ct,
            'close_yesterday': c,
            'total': o + c,
            '_is_real_fee': use_real_fee,
        }
    return rows


def _display_with_fee(product: Any, product_fee_rates: dict[str, dict[str, float]]) -> dict[str, Any]:
    display = product_display_name(product)
    display['fee'] = product_fee_rates.get(display['name'])
    return display


def _build_capacity_analysis(group_products: dict, index_list: list) -> dict[str, Any]:
    counts = np.asarray([len(group_products.get(idx_entry, [])) for idx_entry in index_list], dtype=float)
    if counts.size == 0:
        return {}
    return {
        'mean_count': float(np.mean(counts)),
        'median_count': float(np.median(counts)),
        'min_count': int(np.min(counts)),
        'empty_ratio': float(np.mean(counts == 0)),
        'tiny_group_ratio': float(np.mean(counts <= 2)),
    }


def _build_rolling_analysis(return_series: list[dict[str, Any]]) -> dict[str, Any]:
    if len(return_series) < 5:
        return {'rows': [], 'window_size': None, 'negative_window_ratio': None}
    returns = np.asarray([row['return'] for row in return_series], dtype=float)
    window = min(max(5, int(np.ceil(len(returns) * 0.1))), 60)
    rows = []
    for end in range(window, len(returns) + 1):
        chunk = returns[end - window:end]
        rows.append({
            'timestamp': return_series[end - 1]['timestamp'],
            'return': float(np.prod(1.0 + chunk) - 1.0),
        })
    return {
        'rows': rows,
        'window_size': int(window),
        'negative_window_ratio': float(np.mean([row['return'] < 0 for row in rows])) if rows else None,
    }
