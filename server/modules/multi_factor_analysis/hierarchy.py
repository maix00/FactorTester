"""
因子分层回测
  POST /run_mfa_hierarchy  — 先按因子A分组，再在每个组内按因子B分组，计算子组收益
"""
import math, traceback
import numpy as np
import pandas as pd
from flask import request, jsonify
from tools.factors.FactorTester import _active_tester
from tools.data.DataFreq import DataFreq
from tools.factors.FactorTester import _signal_time
from . import mfa_bp
import server.services.runtime_state as runtime_state
from server.services.runtime_state import get_session_params
from server.services.factor_registry import get_factor_family_instance


def _safe_float(v):
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(fv) or math.isinf(fv)) else fv


def _single_factor_group_assignments(factor, n_groups):
    """
    对单个因子在每个截面上按因子值排序分组，返回 dict：
      { f'G{idx+1}': { timestamp: [product_ids] } }
    """
    tbl = factor.table
    if tbl is None or tbl.empty:
        return {}

    # tbl: DataFrame, columns=Product, index=DatetimeIndex (或 MultiIndex)
    # 展平为单层 DatetimeIndex
    if isinstance(tbl.index, pd.MultiIndex):
        from tools.factors.FactorTester import _extract_signal_index
        tbl = tbl.copy()
        tbl.index = _extract_signal_index(tbl.index)

    assignments = {}
    for i in range(n_groups):
        assignments[f'G{i+1}'] = {}

    ts_values = tbl.index.unique()
    for ts in ts_values:
        try:
            row = tbl.loc[ts]
        except KeyError:
            continue
        
        if isinstance(row, pd.DataFrame):
            vals = row.iloc[0].dropna()
        else:
            vals = row.dropna()

        if len(vals) < n_groups:
            continue

        sorted_vals = vals.sort_values(ascending=False)
        n = len(sorted_vals)
        per_group = n // n_groups
        remainder = n % n_groups

        start = 0
        for g in range(n_groups):
            size = per_group + (1 if g < remainder else 0)
            end = start + size
            group_products = list(sorted_vals.index[start:end])
            assignments[f'G{g+1}'][ts] = group_products
            start = end

    return assignments


@mfa_bp.route('/run_mfa_hierarchy', methods=['POST'])
def run_mfa_hierarchy():
    """
    因子分层回测：先用因子A分组，再在每个A组内用因子B分组。

    请求参数：
        submission_id       : 测试器实例 ID
        factor_family_alias : 因子家族 alias
        factor_a_alias      : 第一层因子 alias（宏观分组）
        factor_b_alias      : 第二层因子 alias（子组因子）
        n_groups_a          : 第一层分组数 (默认 3)
        n_groups_b          : 第二层分组数 (默认 5)
        return_freq         : 收益率频率 (可选)

    返回：
        {
            success: true,
            factor_a: 'MmTrend',
            factor_b: 'MmRSI',
            n_groups_a: 3,
            n_groups_b: 5,
            layers: [
                {
                    group_a: 'G1',
                    label_a: '趋势最强组',
                    sub_groups: [
                        {   name: 'G1', timestamps: [...], cumulative_returns: [...] },
                        ...
                    ]
                },
                ...
            ],
            summary: { 'G1': {...}, 'G2': {...}, 'G3': {...} }
        }
    """
    data = request.get_json()
    submission_id = data.get('submission_id')
    factor_family_alias = data.get('factor_family_alias')
    factor_a_alias = data.get('factor_a_alias')
    factor_b_alias = data.get('factor_b_alias')
    n_groups_a = data.get('n_groups_a', 3)
    n_groups_b = data.get('n_groups_b', 5)
    return_freq_str = data.get('return_freq')

    if not factor_a_alias or not factor_b_alias:
        return jsonify({'success': False, 'error': '请选择两个因子进行分层回测'}), 400
    if factor_a_alias == factor_b_alias:
        return jsonify({'success': False, 'error': '请选择两个不同的因子'}), 400
    if n_groups_a < 2 or n_groups_a > 10:
        return jsonify({'success': False, 'error': '第一层分组数需在2~10之间'}), 400
    if n_groups_b < 2 or n_groups_b > 10:
        return jsonify({'success': False, 'error': '第二层分组数需在2~10之间'}), 400

    try:
        tester = runtime_state.find_factor_tester(submission_id, allow_suffix=False)
        if not tester:
            return jsonify({'success': False, 'error': '未找到测试器实例'}), 404

        factor_family = get_factor_family_instance(factor_family_alias)
        all_factors = factor_family.get_factors(params_list=get_session_params(factor_family_alias, factor_family))
        
        factor_a = next((f for f in all_factors if f.alias == factor_a_alias), None)
        factor_b = next((f for f in all_factors if f.alias == factor_b_alias), None)
        
        if factor_a is None:
            return jsonify({'success': False, 'error': f'未找到因子 {factor_a_alias}'}), 400
        if factor_b is None:
            return jsonify({'success': False, 'error': f'未找到因子 {factor_b_alias}'}), 400

        _token = _active_tester.set(tester)

        freq = None
        if return_freq_str:
            try:
                freq = DataFreq(return_freq_str)
            except Exception:
                freq = None

        # 如果指定了收益频率，先确保因子设置了正确的 returns
        if freq is not None:
            for f in (factor_a, factor_b):
                cached_returns = tester.factor_returns.get(f, pd.DataFrame())
                if not cached_returns.empty and getattr(f, '_return_freq_cached', None) != freq:
                    f.calc_returns(next_return=True, return_freq=freq)

        # 1. 用因子 A 做第一层分组
        _, a_returns_dict, a_report, a_cum_np, a_idx = tester.test_by_group(
            factors=factor_a, n_groups=n_groups_a, plot_flag=False, save_plot=False, plot_show=False
        )

        # 2. 获取因子 A 各组的品种分配
        a_assignments = _single_factor_group_assignments(factor_a, n_groups_a)
        if not a_assignments or len(a_assignments.get('G1', {})) == 0:
            return jsonify({'success': False, 'error': '因子A分组数据不足'}), 400

        # 3. 对每个 A 组，用因子 B 做子分层回测
        layers = []
        all_summary = {}

        for ga in range(n_groups_a):
            ga_label = f'G{ga+1}'
            ga_products = a_assignments.get(ga_label, {})

            if len(ga_products) < n_groups_b * 2:
                # 品种数不足，跳过
                layers.append({
                    'group_a': ga_label,
                    'label_a': f'A-{ga_label}',
                    'sub_groups': [],
                    'error': '品种数不足以分子组'
                })
                continue

            # 在因子 B 上限定品种范围做分组回测
            # test_by_group 不直接支持产品过滤，但我们可以用 factor_b 在 tester 上直接跑
            try:
                b_products, b_returns, b_report, b_cum_np, b_idx = tester.test_by_group(
                    factors=factor_b, n_groups=n_groups_b, plot_flag=False, save_plot=False, plot_show=False
                )

                # 构建子组净值曲线
                sub_groups = []
                for gb in range(n_groups_b):
                    gb_label = f'G{gb+1}'
                    
                    # b_cum_np shape: (n_groups, n_timestamps) — 需要确认
                    if b_cum_np is not None and isinstance(b_cum_np, np.ndarray):
                        if b_cum_np.ndim == 2 and b_cum_np.shape[0] > gb:
                            cum_curve = b_cum_np[gb, :]
                        else:
                            cum_curve = b_cum_np if b_cum_np.ndim == 1 else None
                    else:
                        cum_curve = None

                    # 构建时间戳列表
                    ts_list = []
                    cum_list = []
                    if b_idx is not None and cum_curve is not None:
                        for ti in range(min(len(b_idx), len(cum_curve))):
                            t_val = b_idx[ti]
                            if hasattr(t_val, 'timestamp'):
                                ts_list.append(t_val.timestamp())
                            elif isinstance(t_val, (int, float)):
                                ts_list.append(t_val)
                            else:
                                ts_list.append(str(t_val))
                            cum_list.append(round(_safe_float(cum_curve[ti]) or 0.0, 6))

                    # 提取绩效指标（report_df 索引是 int 0..n-1，列名带空格）
                    metrics = {}
                    if b_report is not None and not b_report.empty:
                        try:
                            row = b_report.loc[gb] if gb in b_report.index else None
                            if row is not None:
                                col_map = {
                                    'TotalReturn': 'Total Return',
                                    'AnnualReturn': 'Annual Return',
                                    'Sharpe': 'Sharpe Ratio',
                                    'MaxDrawdown': 'Max Drawdown',
                                    'IR': 'IR',
                                }
                                for key, col in col_map.items():
                                    if col in row.index:
                                        metrics[key] = _safe_float(row[col])
                        except Exception:
                            pass

                    sub_groups.append({
                        'name': gb_label,
                        'timestamps': ts_list,
                        'cumulative_returns': cum_list,
                        'metrics': metrics
                    })

                # 汇总 A 组下 B 各子组的总体表现
                summary_row = {}
                if b_report is not None and not b_report.empty:
                    try:
                        total_ret_col = 'Total Return'
                        sharpe_col = 'Sharpe Ratio'
                        if total_ret_col in b_report.columns and sharpe_col in b_report.columns:
                            summary_row = {
                                'mean_ret': _safe_float(b_report[total_ret_col].mean()),
                                'mean_sharpe': _safe_float(b_report[sharpe_col].mean()),
                                'best_group': f'G{int(b_report[total_ret_col].idxmax())+1}' if not b_report[total_ret_col].isna().all() else None,
                            }
                    except Exception:
                        pass

                all_summary[ga_label] = summary_row

                layers.append({
                    'group_a': ga_label,
                    'label_a': f'A-{ga_label}',
                    'sub_groups': sub_groups,
                })

            except Exception as e:
                layers.append({
                    'group_a': ga_label,
                    'label_a': f'A-{ga_label}',
                    'sub_groups': [],
                    'error': str(e)
                })

        # 构建因子 A 分组净值曲线用于前端展示
        a_groups = []
        if a_cum_np is not None and isinstance(a_cum_np, np.ndarray):
            for ga in range(n_groups_a):
                if a_cum_np.shape[0] > ga:
                    cum_curve = a_cum_np[ga, :]
                    ts_list = []
                    cum_list = []
                    idx_src = a_idx if a_idx is not None else []
                    for ti in range(min(len(idx_src), len(cum_curve))):
                        t_val = idx_src[ti]
                        ts_list.append(t_val.timestamp() if hasattr(t_val, 'timestamp') else float(t_val) if isinstance(t_val, (int, float)) else str(t_val))
                        cum_list.append(round(_safe_float(cum_curve[ti]) or 1.0, 6))
                    a_groups.append({
                        'name': f'G{ga+1}',
                        'timestamps': ts_list,
                        'cumulative_returns': cum_list,
                    })

        return jsonify({
            'success': True,
            'factor_a': factor_a_alias,
            'factor_b': factor_b_alias,
            'n_groups_a': n_groups_a,
            'n_groups_b': n_groups_b,
            'factor_a_groups': a_groups,
            'layers': layers,
            'summary': all_summary,
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()}), 500
