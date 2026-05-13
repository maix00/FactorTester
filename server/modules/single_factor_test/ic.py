"""
IC test endpoint: /run_ic_test
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import traceback
from typing import Any, Dict, List, Tuple, cast

import numpy as np
import pandas as pd
from flask import jsonify, request

from tools.factors import Factor
from tools.factors.FactorFamily import FactorFamily, _active_tester
from tools.factors.Parameters import FactorNextPeriodReturns
from tools.factors.tests.ic import run_ic_for_factor

from . import sft_bp
from server.services.factor_registry import get_factor_family_instance
from server.services.runtime_state import get_factor_tester, get_session_params


def _extract_signal_index(idx: pd.Index) -> pd.DatetimeIndex:
    if isinstance(idx, pd.MultiIndex):
        signal_name = next((n for n in idx.names if n and str(n).startswith('_SIGNAL')), None)
        level = idx.names.index(signal_name) if signal_name is not None else -1
        return pd.DatetimeIndex(idx.get_level_values(level), name=idx.names[level])
    return pd.DatetimeIndex(idx)


def _safe_round(v: Any, ndigits: int = 6) -> Any:
    if v is None:
        return None
    try:
        fv = float(v)
    except Exception:
        return None
    if np.isnan(fv) or np.isinf(fv):
        return None
    return round(fv, ndigits)


def _extract_product_names(*tables: pd.DataFrame | None) -> List[str]:
    names: List[str] = []
    seen: set[str] = set()
    for table in tables:
        if not isinstance(table, pd.DataFrame) or table.empty:
            continue
        for col in table.columns:
            c_name = str(getattr(col, 'name', col))
            if c_name and c_name not in seen:
                seen.add(c_name)
                names.append(c_name)
    return names


def _is_term_contract_product(product: Any) -> bool:
    marker = getattr(product, 'is_term_contract', None)
    if callable(marker):
        return bool(marker())
    return False


@sft_bp.route('/run_ic_test', methods=['POST'])
def run_ic_test():
    _saved_products = None
    tester = None
    data = request.get_json(silent=True) or {}
    submission_id = data.get('submission_id')
    factor_family_alias = data.get('factor_family_alias')
    factor_alias_return_freq = data.get('factors', [])
    paths = data.get('paths', [])

    ic_decay_lags = data.get('ic_decay_lags', None)
    rolling_window = data.get('rolling_window', None)
    ic_lag_raw = data.get('ic_lag', data.get('lag', 0))
    ic_lags_raw = data.get('ic_lags', None)

    _token = None
    try:
        if submission_id in (None, ''):
            return jsonify({'success': False, 'error': '缺少 submission_id'}), 400
        if factor_family_alias in (None, ''):
            return jsonify({'success': False, 'error': '缺少 factor_family_alias'}), 400

        raw_lags = (
            ic_lags_raw
            if isinstance(ic_lags_raw, list)
            else [ic_lags_raw] if ic_lags_raw is not None else [ic_lag_raw]
        )
        ic_lags: List[int] = []
        for raw in raw_lags:
            try:
                lag_i = int(raw)
            except (TypeError, ValueError):
                return jsonify({'success': False, 'error': f'ic_lag 非法: {raw}，必须是整数'}), 400
            if lag_i < 0:
                return jsonify({'success': False, 'error': 'ic_lag 不能小于 0'}), 400
            if lag_i not in ic_lags:
                ic_lags.append(lag_i)
        if not ic_lags:
            ic_lags = [0]
        primary_ic_lag = ic_lags[0]

        submission_id = str(submission_id)
        factor_family_alias = str(factor_family_alias)

        tester = get_factor_tester(submission_id, caller='run_ic_test')

        factor_family = get_factor_family_instance(factor_family_alias)
        assert isinstance(factor_family, FactorFamily), '未找到对应的因子家族实例'

        tester.sync_signal_index = None
        tester.sync_signal_index_replaced = None
        _token = _active_tester.set(tester)

        all_factors = factor_family.get_factors(
            params_list=get_session_params(factor_family_alias, factor_family)
        )

        matched_factors: List[Factor] = []
        for item in factor_alias_return_freq:
            f = next((x for x in all_factors if x.alias == item.get('alias')), None)
            if f is not None:
                matched_factors.append(f)

        if not matched_factors:
            return jsonify({
                'success': False,
                'error': '没有找到匹配的因子，请检查收益率频率设置中的因子是否属于当前因子家族',
            }), 400

        factors = matched_factors

        paths_hash = hashlib.md5(str(sorted(paths)).encode()).hexdigest()

        all_products = tester.products.copy()
        returns_col = FactorNextPeriodReturns.NEXT_OPEN_TO_OPEN_ADJUSTED

        ic_param_map: Dict[tuple, List[Factor]] = {}
        param_payloads: Dict[tuple, Dict[str, Any]] = {}
        series_by_factor_lag: Dict[Factor, Dict[int, pd.Series]] = {}
        stats_by_factor_lag: Dict[Factor, Dict[int, pd.Series]] = {}
        selected_product_names: List[str] = []

        shift = 0 if returns_col.value.name.startswith('OPEN') else 1

        for factor in factors:
            effective_freq = factor.freq
            if effective_freq is None:
                raise ValueError(f'Factor {factor.alias}: 无法确定收益率频率')

            for lag_i in ic_lags:
                key = (
                    str(factor._structural_key()),
                    effective_freq.name,
                    shift,
                    returns_col.value.name,
                    lag_i,
                )
                if key not in ic_param_map:
                    ic_param_map[key] = []
                    param_payloads[key] = {
                        'FE': factor,
                        'SC': returns_col.value,
                        'RF': effective_freq.value,
                        'S': shift,
                        'Lag': lag_i,
                        '$F': effective_freq.value,
                    }
                ic_param_map[key].append(factor)

        _saved_products = tester.products.copy() if hasattr(tester, 'products') else None
        try:
            tester.products = all_products.copy()
            param_items = list(ic_param_map.items())

            def _calc_one_group(item: Tuple[tuple, List[Factor]]):
                key, factor_list = item
                result = run_ic_for_factor(tester, param_payloads[key], factor_list)
                return key, result

            # Issue #3: Serialize computation to avoid ThreadPoolExecutor concurrent mutations
            for key, factor_list in param_items:
                lag_i = int(key[-1])
                _, ic_series, stats, re_table, fe_table = run_ic_for_factor(tester, param_payloads[key], factor_list)
                for factor in factor_list:
                    series_by_factor_lag.setdefault(factor, {})[lag_i] = ic_series.copy()
                    stats_by_factor_lag.setdefault(factor, {})[lag_i] = stats.copy()

                    if lag_i == primary_ic_lag:
                        r = tester._get_result(factor)
                        r.ic_series = ic_series.copy()
                        r.ic_stats = stats.copy()
                        if not re_table.empty:
                            r.returns = re_table.copy()
                        if not fe_table.empty:
                            # func_table 是 computed property，从 source_table + _func_expr 推导
                            # 这里确保 source_table 已存储（由 factor.evaluate() 写入），
                            # func_table 即可通过 r.func_table 获取
                            pass

                        p_names = _extract_product_names(fe_table, re_table)
                        if p_names:
                            for p_name in p_names:
                                if p_name not in selected_product_names:
                                    selected_product_names.append(p_name)
        except Exception as e:
            if _saved_products is not None:
                tester.products = _saved_products
            return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()})

        product_map: Dict[str, Any] = {}
        alias_map: Dict[str, Any] = {}
        for p in all_products:
            p_name = str(getattr(p, 'name', p))
            p_alias = str(getattr(p, 'alias', p_name))
            product_map[p_name] = p
            alias_map[p_alias] = p

        resolved_products: set[Any] = set()
        resolved_seen: set[int] = set()
        for p_name in selected_product_names:
            p_obj = product_map.get(p_name) or alias_map.get(p_name)
            if p_obj is None:
                continue
            obj_id = id(p_obj)
            if obj_id in resolved_seen:
                continue
            resolved_seen.add(obj_id)
            resolved_products.add(p_obj)

        # Issue #1: Restore original products after updating to resolved set
        tester.products = resolved_products if resolved_products else all_products.copy()

        ic_stats_all = pd.DataFrame({
            f.alias: (tester.results[f].ic_stats if f in tester.results else pd.Series(dtype=float)) for f in factors
        })
        columns = ic_stats_all.columns.tolist()
        rows = ic_stats_all.to_dict(orient='records')
        indices = ic_stats_all.index.tolist()
        for i, row in enumerate(rows):
            row['index'] = indices[i]
            for k, v in list(row.items()):
                if isinstance(v, float) and (pd.isna(v) or np.isinf(v)):
                    row[k] = None

        ic_decay_results: Dict[str, List[dict]] = {}
        if isinstance(ic_decay_lags, list) and len(ic_decay_lags) > 0:
            for factor in factors:
                base_ic = (tester.results[factor].ic_series if factor in tester.results else pd.Series(dtype=float)).dropna()
                decay_list: List[dict] = []
                for lag in ic_decay_lags:
                    try:
                        lag_i = int(lag)
                    except Exception:
                        continue
                    if lag_i <= 0:
                        continue
                    s = base_ic.iloc[::lag_i].dropna()
                    if len(s) > 1:
                        mean_val = float(s.mean())
                        std_val = float(s.std())
                        ir_val = (mean_val / std_val) if std_val != 0 else None
                        n_val = len(s)
                        t_val = (mean_val / (std_val / np.sqrt(n_val))) if std_val != 0 and n_val > 1 else None
                        decay_list.append({
                            'lag': lag_i,
                            'mean': _safe_round(mean_val),
                            'std': _safe_round(std_val),
                            'ir': _safe_round(ir_val),
                            't_stat': _safe_round(t_val),
                            'n': n_val,
                        })
                    else:
                        decay_list.append({
                            'lag': lag_i,
                            'mean': None,
                            'std': None,
                            'ir': None,
                            't_stat': None,
                            'n': 0,
                        })
                ic_decay_results[factor.alias] = decay_list

        response: dict = {
            'success': True,
            'paths_hash': paths_hash,
            'ic_lags': ic_lags,
            'primary_ic_lag': primary_ic_lag,
            'ic_stats': {'columns': ['index'] + columns, 'rows': rows},
            'factors': [],
        }

        for factor in factors:
            ic_s = (tester.results[factor].ic_series if factor in tester.results else pd.Series(dtype=float)).dropna()
            signal_ts = _extract_signal_index(ic_s.index) if len(ic_s) > 0 else pd.DatetimeIndex([])
            is_daily = factor.freq is not None and factor.freq.is_day_multiple()
            if is_daily:
                dates = [ts.strftime('%Y-%m-%d') for ts in signal_ts]
            else:
                raw = cast(np.ndarray, signal_ts.view(np.int64))
                dates = cast('list[str | int]', (raw // 10**6).tolist())
            vals = [
                None if (isinstance(v, float) and (pd.isna(v) or np.isinf(v))) else v
                for v in ic_s.values.tolist()
            ]

            autocorr = None
            if len(ic_s) > 2:
                try:
                    from statsmodels.tsa.stattools import acf
                    nlags = min(20, max(1, len(ic_s) // 2 - 1))
                    acf_vals = acf(ic_s.values, nlags=nlags, fft=False)
                    autocorr = [
                        {'lag': i, 'ac': _safe_round(v)}
                        for i, v in enumerate(acf_vals[1:], start=1)
                    ]
                except Exception:
                    autocorr = None

            rolling_ic = None
            if isinstance(rolling_window, (int, float)) and rolling_window > 1:
                win = int(rolling_window)
                s_vals = np.asarray(ic_s.values, dtype=float)
                if len(s_vals) >= win:
                    r_mean = []
                    r_ir = []
                    r_dates = []
                    for i in range(win - 1, len(s_vals)):
                        win_slice = np.asarray(s_vals[i - win + 1:i + 1], dtype=float)
                        m = float(np.mean(win_slice))
                        std_win = float(np.std(win_slice))
                        r = (m / std_win) if std_win != 0 else None
                        r_mean.append(_safe_round(m))
                        r_ir.append(_safe_round(r))
                        ts_i: Any = signal_ts[i]
                        if hasattr(ts_i, 'strftime'):
                            r_dates.append(ts_i.strftime('%Y-%m-%d') if is_daily else int(cast(np.int64, ts_i.value) // 10**6))
                        else:
                            r_dates.append(str(ts_i))
                    rolling_ic = {
                        'window': win,
                        'dates': r_dates,
                        'mean': r_mean,
                        'ir': r_ir,
                    }

            fe_table = fe_table  # IC 内部局部变量，仅用于提取产品列表
            products = []
            for p in sorted(tester.products, key=lambda p: str(getattr(p, 'alias', getattr(p, 'name', p)))):
                p_name = str(getattr(p, 'name', p))
                p_desc = str(getattr(p, 'desc', p_name))
                products.append({
                    'name': p_name,
                    'desc': p_desc,
                    'is_term_contract': _is_term_contract_product(p),
                })

            factor_data = {
                'name': factor.name,
                'alias': factor.alias,
                'ic_series': {'dates': dates, 'values': vals},
                'autocorr': autocorr,
                'products': products,
            }

            if len(ic_lags) > 1:
                lag_series_list = []
                lag_stats_dict: Dict[str, Dict[str, Any]] = {}
                for lag_i in ic_lags:
                    lag_series = series_by_factor_lag.get(factor, {}).get(lag_i, pd.Series(dtype=float)).dropna()
                    lag_ts = _extract_signal_index(lag_series.index) if len(lag_series) > 0 else pd.DatetimeIndex([])
                    lag_dates: list[str | int]
                    if is_daily:
                        lag_dates = [ts.strftime('%Y-%m-%d') for ts in lag_ts]
                    else:
                        raw = cast(np.ndarray, lag_ts.view(np.int64))
                        lag_dates = cast('list[str | int]', (raw // 10**6).tolist())
                    lag_vals = [
                        None if (isinstance(v, float) and (pd.isna(v) or np.isinf(v))) else v
                        for v in lag_series.values.tolist()
                    ]
                    lag_series_list.append({'lag': lag_i, 'dates': lag_dates, 'values': lag_vals})

                    lag_stat_s = stats_by_factor_lag.get(factor, {}).get(lag_i)
                    if isinstance(lag_stat_s, pd.Series):
                        lag_stats_dict[str(lag_i)] = {
                            str(k): _safe_round(v) for k, v in lag_stat_s.to_dict().items()
                        }

                factor_data['ic_series_by_lag'] = lag_series_list
                factor_data['ic_stats_by_lag'] = lag_stats_dict

            if ic_decay_results:
                factor_data['ic_decay'] = ic_decay_results.get(factor.alias, [])
            if rolling_ic:
                factor_data['rolling_ic'] = rolling_ic

            response['factors'].append(factor_data)

        existing = {f.alias for f in tester.factors}
        for f in factors:
            if f.alias not in existing:
                tester.factors.append(f)
                existing.add(f.alias)
            else:
                for i, ef in enumerate(tester.factors):
                    if ef.alias == f.alias:
                        tester.factors[i] = f
                        break

        return jsonify(response)

    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()})
    finally:
        # Issue #1: Restore original products state before exiting
        if _saved_products is not None and tester is not None:
            tester.products = _saved_products
        if _token is not None:
            _active_tester.reset(_token)
