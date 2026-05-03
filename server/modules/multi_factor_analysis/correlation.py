"""
因子相关性矩阵
  POST /run_mfa_correlation  — Spearman + Pearson 相关性矩阵
"""
import math, traceback
import pandas as pd
from flask import request, jsonify
from tools.factors.FactorTester import _active_tester
from . import mfa_bp
from server.shared import (
    get_factor_family_instance, _get_session_params,
    _factor_testers_lock,
)
import server.shared as shared


def _safe_float(v):
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(fv) or math.isinf(fv)) else fv


@mfa_bp.route('/run_mfa_correlation', methods=['POST'])
def run_mfa_correlation():
    """计算所选因子间的截面相关性矩阵（Spearman + Pearson）。"""
    data = request.get_json()
    submission_id = data.get('submission_id')
    factor_family_alias = data.get('factor_family_alias')
    factor_aliases = data.get('factor_aliases', [])
    if not factor_aliases or len(factor_aliases) < 2:
        return jsonify({'success': False, 'error': '请至少选择2个因子'}), 400

    try:
        with _factor_testers_lock:
            tester = next((t for t in shared.factor_testers if t.alias == str(submission_id)), None)
        if not tester:
            return jsonify({'success': False, 'error': '未找到测试器实例'}), 404

        factor_family = get_factor_family_instance(factor_family_alias)
        all_factors = factor_family.get_factors(params_list=_get_session_params(factor_family_alias, factor_family))
        factors = [f for f in all_factors if f.alias in factor_aliases]
        if len(factors) < 2:
            return jsonify({'success': False, 'error': f'只匹配到{len(factors)}个因子'}), 400

        _token = _active_tester.set(tester)

        # 收集每个因子的截面数据（对齐时间）
        factor_series = {}
        all_index = None
        for f in factors:
            if f.table is None or f.table.empty:
                continue
            tbl = f.table
            if isinstance(tbl, pd.DataFrame):
                if isinstance(tbl.index, pd.MultiIndex):
                    s = tbl.mean(axis=1).groupby(level=0).mean()
                else:
                    s = tbl.mean(axis=1)
            else:
                s = tbl
            factor_series[f.alias] = s.dropna()
            if all_index is None:
                all_index = factor_series[f.alias].index
            else:
                all_index = all_index.intersection(factor_series[f.alias].index)

        if all_index is None or len(all_index) < 10:
            return jsonify({'success': False, 'error': '因子间重叠时间点太少，无法计算相关性'}), 400

        # 对齐数据
        aligned = {}
        for alias, s in factor_series.items():
            aligned[alias] = s.reindex(all_index)

        df = pd.DataFrame(aligned).dropna()
        n_obs = len(df)
        if n_obs < 10:
            return jsonify({'success': False, 'error': f'有效观测点不足 ({n_obs}), 需要至少10个'}), 400

        aliases_sorted = [f.alias for f in factors if f.alias in df.columns]

        # Spearman & Pearson
        spearman_corr = df[aliases_sorted].corr(method='spearman')
        pearson_corr  = df[aliases_sorted].corr(method='pearson')

        def _corr_to_matrix(corr_df, factor_list):
            names = factor_list
            m = []
            for i, rn in enumerate(names):
                row = []
                for j, cn in enumerate(names):
                    if j <= i:
                        v = corr_df.loc[rn, cn]
                        row.append(None if pd.isna(v) else round(float(v), 6))
                    else:
                        row.append(None)
                m.append(row)
            return {'labels': names, 'matrix': m}

        return jsonify({
            'success': True,
            'n_obs': n_obs,
            'spearman': _corr_to_matrix(spearman_corr, aliases_sorted),
            'pearson':  _corr_to_matrix(pearson_corr, aliases_sorted),
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()}), 500
