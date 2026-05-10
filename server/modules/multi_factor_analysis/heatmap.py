"""
因子表现热力图
  POST /run_mfa_heatmap  — 多因子 IC 按月份/季度的热力图数据
"""
import math, traceback
import numpy as np
import pandas as pd
from flask import request, jsonify
from tools.factors.FactorTester import _active_tester
from tools.data.DataFreq import DataFreq
from tools.factors import Factor, CrossSectionIC
from tools.factors.Parameters import FactorNextPeriodReturns
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


@mfa_bp.route('/run_mfa_heatmap', methods=['POST'])
def run_mfa_heatmap():
    """
    计算多因子的 IC 热力图数据。

    请求参数：
        submission_id       : 测试器实例 ID
        factor_family_alias : 因子家族 alias
        factor_aliases      : 因子 alias 列表
        return_freq         : 收益率频率 (可选)
        group_by            : 'month' | 'quarter' (默认 'month')
        metric              : 'mean_ic' | 'cum_ic' | 'ir' (默认 'mean_ic')

    返回：
        {
            success: true,
            group_by: 'month',
            metric: 'mean_ic',
            labels: ['2023-01','2023-02',...],    # 时间段标签
            factors: ['MmRet', 'MmRSI', ...],     # 因子名列表
            matrix: [[0.05, 0.03, ...], ...],     # (factors × periods) 热力值矩阵
        }
    """
    data = request.get_json()
    submission_id = data.get('submission_id')
    factor_family_alias = data.get('factor_family_alias')
    factor_aliases = data.get('factor_aliases', [])
    return_freq_str = data.get('return_freq')
    group_by = data.get('group_by', 'month')  # 'month' | 'quarter'
    metric = data.get('metric', 'mean_ic')    # 'mean_ic' | 'cum_ic' | 'ir'

    if not factor_aliases or len(factor_aliases) < 2:
        return jsonify({'success': False, 'error': '请至少选择2个因子'}), 400
    if group_by not in ('month', 'quarter'):
        return jsonify({'success': False, 'error': 'group_by 仅支持 month/quarter'}), 400
    if metric not in ('mean_ic', 'cum_ic', 'ir'):
        return jsonify({'success': False, 'error': 'metric 仅支持 mean_ic/cum_ic/ir'}), 400

    try:
        tester = runtime_state.find_factor_tester(submission_id, allow_suffix=False)
        if not tester:
            return jsonify({'success': False, 'error': '未找到测试器实例'}), 404

        factor_family = get_factor_family_instance(factor_family_alias)
        all_factors = factor_family.get_factors(params_list=get_session_params(factor_family_alias, factor_family))
        factors = [f for f in all_factors if f.alias in factor_aliases]
        if len(factors) < 2:
            return jsonify({'success': False, 'error': f'只匹配到{len(factors)}个因子'}), 400

        _token = _active_tester.set(tester)

        freq = None
        if return_freq_str:
            try:
                freq = DataFreq(return_freq_str)
            except Exception:
                freq = None

        # 计算每个因子的 IC 序列
        factor_ic = {}
        returns_col = FactorNextPeriodReturns.NEXT_OPEN_TO_OPEN_ADJUSTED
        for f in factors:
            try:
                ic_family = CrossSectionIC()
                ic_factor = ic_family.get_factor(FE=f, SC=returns_col, RF=freq)
                ic_factor.evaluate(tester.products, source_freq=f._source_freq)
                ic_s = ic_factor.table['IC'].dropna()
                if len(ic_s) > 0:
                    factor_ic[f.alias] = ic_s
            except Exception:
                pass

        if len(factor_ic) < 2:
            return jsonify({'success': False, 'error': '有效IC序列不足2个因子'}), 400

        # 聚合到时间桶 (月/季度)
        grouped = {}
        for alias, ic_s in factor_ic.items():
            # 确保索引是 DatetimeIndex
            if hasattr(ic_s.index, 'get_level_values'):
                # 可能是 MultiIndex，取最后一层时间
                idx = ic_s.index
                if isinstance(idx, pd.MultiIndex):
                    time_idx = idx.get_level_values(-1)
                else:
                    time_idx = idx
            else:
                time_idx = ic_s.index
            time_idx = pd.DatetimeIndex(time_idx)

            if group_by == 'month':
                periods = time_idx.to_period('M')
            else:
                periods = time_idx.to_period('Q')

            ic_s_period = ic_s.copy()
            ic_s_period.index = periods

            gb = ic_s_period.groupby(level=0)
            if metric == 'mean_ic':
                grouped[alias] = gb.mean()
            elif metric == 'cum_ic':
                grouped[alias] = gb.sum()
            elif metric == 'ir':
                grouped[alias] = gb.mean() / gb.std().replace(0, np.nan)

        # 构建统一时间轴
        all_periods = None
        for alias, s in grouped.items():
            s_clean = s.dropna()
            if len(s_clean) == 0:
                continue
            if all_periods is None:
                all_periods = set(s_clean.index)
            else:
                all_periods = all_periods.intersection(set(s_clean.index))

        if all_periods is None or len(all_periods) < 2:
            return jsonify({'success': False, 'error': '重叠时间段不足2个'}), 400

        sorted_periods = sorted(all_periods, key=lambda p: p.start_time)
        period_labels = [str(p) for p in sorted_periods]

        # 构建矩阵
        factor_list = sorted(grouped.keys())
        matrix = []
        for alias in factor_list:
            s = grouped[alias].dropna()
            row = []
            for p in sorted_periods:
                if p in s.index:
                    row.append(round(float(s.loc[p]), 6))
                else:
                    row.append(None)
            matrix.append(row)

        return jsonify({
            'success': True,
            'group_by': group_by,
            'metric': metric,
            'periods': period_labels,
            'factors': factor_list,
            'matrix': matrix,
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()}), 500
