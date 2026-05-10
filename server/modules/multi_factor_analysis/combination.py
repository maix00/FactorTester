"""
因子合成回测
  POST /run_mfa_combination  — 等权/IC加权/IR加权/最大夏普/最小方差/风险平价  + 分组回测
"""
import math, traceback
import numpy as np
import pandas as pd
from flask import request, jsonify
from scipy.optimize import minimize
from tools.factors.FactorTester import _active_tester
from tools.data.DataFreq import DataFreq
from tools.factors.FactorTester import _signal_time
from tools.factors.Factors import Factor
from tools.factors.Parameters import FactorNextPeriodReturns
from . import mfa_bp
from server.shared import (
    _get_session_params,
    _factor_testers_lock,
)
from server.services.factor_registry import get_factor_family_instance
import server.shared as shared


# ── 辅助：对齐因子截面 ──────────────────────────────────────
def _align_factor_sections(factors):
    """收集各因子截面值，对齐时间索引。返回 (DataFrame, aliases_present)。"""
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
        raise ValueError(f'因子间重叠时间点不足 ({len(all_index) if all_index is not None else 0})')

    aligned = {a: s.reindex(all_index) for a, s in factor_series.items()}
    df = pd.DataFrame(aligned)
    aliases_present = [a for a in [f.alias for f in factors] if a in df.columns]
    if len(aliases_present) < 2:
        raise ValueError(f'对齐后有效因子不足2个')
    return df, aliases_present


# ── 组合优化权重 ────────────────────────────────────────────
def _optimize_weights(returns_df, method='max_sharpe', lambda_reg=0.01):
    """
    基于因子历史收益率估算协方差矩阵，优化组合权重。

    参数：
        returns_df : (T, N) 因子收益率 DataFrame（对齐后的因子模拟组合收益）
        method     : 'max_sharpe' / 'min_variance' / 'risk_parity'
        lambda_reg : L2 正则化系数（防止过拟合）

    返回：
        weights : np.ndarray (N,)
        metrics : dict { 'expected_return', 'expected_vol', 'sharpe' }
    """
    N = returns_df.shape[1]
    mu  = returns_df.mean().values     # (N,)  期望收益
    cov = returns_df.cov().values      # (N,N) 协方差矩阵
    # 加入小量对角正则化
    cov += np.eye(N) * lambda_reg * np.trace(cov) / N

    aliases = list(returns_df.columns)
    w0 = np.ones(N) / N  # 等权初始值

    # 约束：sum(w) = 1, w >= 0
    cons = [{'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0}]
    bounds = [(0.0, 1.0)] * N

    if method == 'min_variance':
        def obj(w):
            return 0.5 * w @ cov @ w
        result = minimize(obj, w0, bounds=bounds, constraints=cons, method='SLSQP',
                          options={'maxiter': 5000, 'ftol': 1e-12})

    elif method == 'max_sharpe':
        # 最大化 Sharpe ≈ mu^T w / sqrt(w^T cov w)，等价于最小化 -mu^T w / sqrt(...)
        def obj(w):
            ret = mu @ w
            vol = np.sqrt(max(w @ cov @ w, 1e-12))
            return -ret / vol
        result = minimize(obj, w0, bounds=bounds, constraints=cons, method='SLSQP',
                          options={'maxiter': 5000, 'ftol': 1e-12})

    elif method == 'risk_parity':
        # 风险平价：使每个因子的风险贡献相等
        # RC_i = w_i * (Cov w)_i / sqrt(w^T Cov w)
        def obj(w):
            sigma = np.sqrt(max(w @ cov @ w, 1e-12))
            rc = w * (cov @ w) / sigma   # 边际风险贡献
            target = sigma / N           # 目标：均分总风险
            return np.sum((rc - target) ** 2)
        result = minimize(obj, w0, bounds=bounds, constraints=cons, method='SLSQP',
                          options={'maxiter': 5000, 'ftol': 1e-12})

    else:
        raise ValueError(f'不支持的优化方法: {method}')

    w_opt = result.x
    w_opt = np.maximum(w_opt, 0)
    w_opt = w_opt / w_opt.sum()

    ret = mu @ w_opt
    vol = np.sqrt(w_opt @ cov @ w_opt)
    sharpe = ret / vol if vol > 0 else 0.0

    return w_opt, {'expected_return': round(float(ret), 6),
                   'expected_vol': round(float(vol), 6),
                   'sharpe': round(float(sharpe), 4)}


def _estimate_factor_returns(tester, factors, freq):
    """估计每个因子的"模拟组合收益序列"（因子 Z-score × 下期收益 cross-sectional mean）。"""
    ret_series = {}
    for f in factors:
        if f.table is None or f.table.empty:
            continue
        try:
            # 获取因子值 Z-score
            tbl = f.table
            if isinstance(tbl, pd.DataFrame):
                if isinstance(tbl.index, pd.MultiIndex):
                    s = tbl.mean(axis=1).groupby(level=0).mean()
                else:
                    s = tbl.mean(axis=1)
            else:
                s = tbl
            z = ((s - s.mean()) / s.std()).fillna(0)

            # 获取下期收益
            cached_returns = tester.factor_returns.get(f, pd.DataFrame())
            if cached_returns.empty or getattr(f, '_return_freq_cached', None) != freq:
                f.calc_returns(next_return=True, return_freq=freq)
            ret_df = tester.factor_returns.get(f, pd.DataFrame())
            if isinstance(ret_df, pd.DataFrame):
                if isinstance(ret_df.index, pd.MultiIndex):
                    r_s = ret_df.mean(axis=1).groupby(level=0).mean()
                else:
                    r_s = ret_df.mean(axis=1)
            else:
                r_s = ret_df

            common = z.index.intersection(r_s.index)
            if len(common) > 1:
                # 因子模拟组合收益 ≈ sign(z) * r (简化版：Z-score 加权截面收益)
                ret_series[f.alias] = (z.loc[common] * r_s.loc[common]).dropna()
        except Exception:
            pass
    return ret_series


# ── API ─────────────────────────────────────────────────────
@mfa_bp.route('/run_mfa_combination', methods=['POST'])
def run_mfa_combination():
    """因子合成回测：等权 / IC 加权 / IR 加权 / 最大夏普 / 最小方差 / 风险平价。"""
    data = request.get_json()
    submission_id = data.get('submission_id')
    factor_family_alias = data.get('factor_family_alias')
    factor_aliases = data.get('factor_aliases', [])
    method = data.get('method', 'equal_weight')  # equal_weight, ic_weight, ir_weight, max_sharpe, min_variance, risk_parity
    n_groups = data.get('n_groups', 5)
    return_freq_str = data.get('return_freq')

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

        freq = None
        if return_freq_str:
            try:
                freq = DataFreq(return_freq_str)
            except Exception:
                freq = None

        # 1. 对齐因子截面
        df_factors, aliases_present = _align_factor_sections(factors)
        df_z = ((df_factors - df_factors.mean()) / df_factors.std()).fillna(0)
        n = len(aliases_present)

        # 2. 权重计算
        weights = {}
        optimization_metrics = None

        if method in ('equal_weight', 'ic_weight', 'ir_weight'):
            # --- 原有静态权重 ------------------------------------------------
            ic_means = {}
            ir_vals_dict = {}
            returns_col = FactorNextPeriodReturns.NEXT_OPEN_TO_OPEN_ADJUSTED
            for f in factors:
                try:
                    ic_family = CrossSectionIC()
                    ic_factor = ic_family.get_factor(FE=f, SC=returns_col, RF=freq)
                    ic_factor.evaluate(tester.products, source_freq=f._source_freq)
                    ic_s = ic_factor.table['IC'].dropna()
                    m_val = float(ic_s.mean()) if len(ic_s) > 0 else 0.0
                    s_val = float(ic_s.std()) if len(ic_s) > 0 else 1.0
                    ic_means[f.alias] = m_val
                    ir_vals_dict[f.alias] = max(m_val / s_val if s_val > 0 else 0, 0.001)
                except Exception:
                    ic_means[f.alias] = 0.0
                    ir_vals_dict[f.alias] = 0.001

            if method == 'equal_weight':
                w = 1.0 / n
                for a in aliases_present:
                    weights[a] = w
            elif method == 'ic_weight':
                ic_vals = [max(ic_means.get(a, 0), 0.001) for a in aliases_present]
                total = sum(ic_vals)
                weights = {a: max(v, 0.001) / total if total > 0 else 1.0 / n
                           for a, v in zip(aliases_present, ic_vals)}
            elif method == 'ir_weight':
                ir_vals = [ir_vals_dict.get(a, 0.001) for a in aliases_present]
                total = sum(ir_vals)
                weights = {a: v / total if total > 0 else 1.0 / n
                           for a, v in zip(aliases_present, ir_vals)}

        elif method in ('max_sharpe', 'min_variance', 'risk_parity'):
            # --- 组合优化权重 ------------------------------------------------
            ret_series = _estimate_factor_returns(tester,
                [f for f in factors if f.alias in aliases_present], freq)
            # 对齐各因子收益率序列
            ret_df = pd.DataFrame(ret_series).dropna()
            if ret_df.shape[0] < 30:
                return jsonify({'success': False,
                    'error': f'因子收益率重叠样本不足 ({ret_df.shape[0]}), 需要至少30'}), 400

            # 仅保留 aliases_present 中存在的列
            ret_df = ret_df[[a for a in aliases_present if a in ret_df.columns]]
            if ret_df.shape[1] < 2:
                return jsonify({'success': False, 'error': '对齐后有效因子收益率不足2列'}), 400

            w_opt, opt_metrics = _optimize_weights(ret_df, method=method)
            opt_aliases = list(ret_df.columns)
            weights = {a: round(float(w_opt[i]), 6) for i, a in enumerate(opt_aliases)}
            optimization_metrics = opt_metrics

        else:
            return jsonify({'success': False, 'error': f'不支持的合成方法: {method}'}), 400

        # 3. 合成因子
        composite = pd.Series(0.0, index=df_z.index)
        for alias, w in weights.items():
            if alias in df_z.columns:
                composite += w * df_z[alias]

        # 4. 分组回测
        composite_factor = Factor(name='composite', family=factor_family)
        composite_factor.table = composite.to_frame(name='_COMPOSITE_')
        composite_factor.freq = factors[0].freq if factors[0].freq else factor_family.get_default_freq()
        composite_factor.calc_returns(next_return=True, return_freq=freq)

        _returns, _returns_dict, report_df, cum_np, idx_list = tester.test_by_group(
            factors=composite_factor, n_groups=n_groups, time_range=None,
            plot_flag=False, save_plot=False, plot_show=False,
            fee=0.0, fee_map={},
        )

        timestamps = [int(_signal_time(d).timestamp() * 1000) for d in idx_list]

        groups_data = []
        for g in range(n_groups):
            vals = [round(float(v), 8) if not (math.isnan(v) or math.isinf(v)) else None
                    for v in cum_np[:, g]]
            groups_data.append({
                'name': f'Group {g+1}',
                'timestamps': timestamps,
                'cumulative_returns': vals,
            })

        # Long-Short
        long_vals  = cum_np[:, 0]
        short_vals = cum_np[:, n_groups - 1]
        ls_vals = []
        long_cap, short_cap = 0.5, 0.5
        total_cap = 1.0
        for l, s in zip(long_vals, short_vals):
            lr = 0.0 if (math.isnan(l) or math.isinf(l)) else float(l) - 1.0
            sr = 0.0 if (math.isnan(s) or math.isinf(s)) else float(s) - 1.0
            long_cap  *= (1.0 + lr)
            short_cap *= (1.0 - sr)
            new_total = long_cap + short_cap
            ls_vals.append(round(new_total / total_cap - 1.0, 8))
            total_cap = new_total

        groups_data.append({
            'name': 'Long-Short',
            'timestamps': timestamps,
            'cumulative_returns': ls_vals,
        })

        resp = {
            'success': True,
            'method': method,
            'weights': {a: round(float(w), 6) for a, w in weights.items()},
            'n_groups': n_groups,
            'groups': groups_data,
        }
        if optimization_metrics:
            resp['optimization_metrics'] = optimization_metrics

        return jsonify(resp)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()}), 500

        return jsonify({
            'success': True,
            'method': method,
            'weights': {a: round(float(w), 6) for a, w in weights.items()},
            'n_groups': n_groups,
            'groups': groups_data,
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()}), 500
