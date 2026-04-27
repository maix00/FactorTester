"""
IC test endpoint: /run_ic_test
"""
import pickle, hashlib, traceback
import numpy as np
import pandas as pd
from pathlib import Path
from flask import request, jsonify
from tools.factors.FactorFamily import FactorFamily, _active_tester
from tools.products.Product import Product
from . import sft_bp
from server.shared import (
    get_factor_family_instance, _get_session_params,
    _factor_testers_lock,
)
import server.shared as shared


@sft_bp.route('/run_ic_test', methods=['POST'])
def run_ic_test():
    data = request.get_json()
    submission_id = data.get('submission_id')
    factor_family_alias = data.get('factor_family_alias')
    factor_alias_return_freq = data.get('factors', [])
    paths = data.get('paths', [])
    re_calc = data.get('re_calc', False)
    _token = None
    try:
        with _factor_testers_lock:
            tester = next((t for t in shared.factor_testers if t.alias == str(submission_id)), None)
        assert tester is not None, "未找到对应的测试器实例"

        factor_family = get_factor_family_instance(factor_family_alias)
        assert isinstance(factor_family, FactorFamily), "未找到对应的因子家族实例"

        tester.sync_signal_index = None
        tester.sync_signal_index_replaced = None
        _token = _active_tester.set(tester)

        factors = factor_family.get_factors(params_list=_get_session_params(factor_family_alias, factor_family))
        # 过滤：只保留在当前因子家族中实际存在的因子
        matched_factors = []
        matched_items = []
        for item in factor_alias_return_freq:
            f = next((f for f in factors if f.alias == item['alias']), None)
            if f is not None:
                matched_factors.append(f)
                matched_items.append(item)
        if not matched_factors:
            return jsonify({'error': '没有找到匹配的因子，请检查收益率频率设置中的因子是否属于当前因子家族'}), 400
        factors = matched_factors
        factor_alias_return_freq = matched_items
        return_freqs = {
            factor: (None if item.get('return_freq') in (None, '', 'N') else item.get('return_freq'))
            for factor, item in zip(factors, factor_alias_return_freq)
        }

        cache_dir_ic     = Path('../data/cache/ic')
        cache_dir_factor = Path('../data/cache/factor')
        cache_dir_ic.mkdir(parents=True, exist_ok=True)
        cache_dir_factor.mkdir(parents=True, exist_ok=True)

        sorted_paths = sorted(paths)
        paths_hash = hashlib.md5(str(sorted_paths).encode()).hexdigest()
        scp_str = str(shared.start_calc_point).replace(':', '-').replace(' ', '_') if shared.start_calc_point else 'latest'
        start_date_str = str(tester.start_date).replace(':', '-').replace(' ', '_')
        end_date_str   = str(tester.end_date).replace(':', '-').replace(' ', '_')
        all_products = tester.products.copy()

        for factor in factors:
            run_products = all_products.copy()
            factor.clear()
            return_freq = return_freqs.get(factor, None)
            factor_series_cache = cache_dir_factor / f"{factor.alias}_{scp_str}.pkl"
            factor_ic_cache     = cache_dir_ic     / f"{paths_hash}_{factor.alias}_{return_freq}_{start_date_str}_{end_date_str}.pkl"

            table = None
            if not re_calc and factor_series_cache.exists():
                with open(factor_series_cache, 'rb') as f:
                    table, scp_cache = pickle.load(f)
                if shared.start_calc_point == scp_cache:
                    run_products = set(p for p in tester.products if p not in table.columns)
                else:
                    table = None
            if run_products:
                try:
                    tester.products = run_products.copy()
                    tester.calc_factor(factors=factor)
                except Exception:
                    pass
                finally:
                    tester.products = all_products.copy()
                    if factor.table is None or factor.table.empty:
                        run_products = set()
            if table is None and (factor.table is None or factor.table.empty):
                raise ValueError("/run_ic_test: 无法计算因子数据，且缓存中无数据可用")
            if table is not None:
                if factor.table is None or factor.table.empty:
                    factor.table = table
                else:
                    for col in table.columns:
                        assert col not in factor.table.columns, f"/run_ic_test: 列名冲突: {col}"
                    factor.table = pd.concat([table, factor.table], axis=1)
            if factor.table is not None and not factor.table.empty:
                if not hasattr(factor, 'freq') or factor.freq is None:
                    factor.freq = factor.get_freq()
                factor._set_products()
            if run_products:
                with open(factor_series_cache, 'wb') as f:
                    pickle.dump((factor.table, shared.start_calc_point), f)
            run_products = all_products.copy()

            ic_series = None
            ic_stats  = None
            returns_table = pd.DataFrame()
            if not re_calc and factor_ic_cache.exists():
                with open(factor_ic_cache, 'rb') as f:
                    ic_s_c, ic_st_c, prods_c, rf_c, ret_c, sd_c, ed_c = pickle.load(f)
                if prods_c == run_products and rf_c == return_freq and sd_c == tester.start_date and ed_c == tester.end_date:
                    ic_series, ic_stats, returns_table, run_products = ic_s_c, ic_st_c, ret_c, set()
            if run_products:
                try:
                    ic_s_df, ic_st_df = tester.calc_ic(factors=factor, return_freq=return_freq)
                    returns_table = factor.returns
                    ic_series = ic_s_df.iloc[:, 0]
                    ic_stats  = ic_st_df.iloc[:, 0]
                except Exception:
                    pass
            assert ic_series is not None and ic_stats is not None and not returns_table.empty, \
                "/run_ic_test: 无法计算IC数据，且缓存中无数据可用"
            factor.ic_series = ic_series
            factor.ic_stats  = ic_stats
            if run_products:
                with open(factor_ic_cache, 'wb') as f:
                    pickle.dump((factor.ic_series, factor.ic_stats, all_products, return_freq,
                                 returns_table, tester.start_date, tester.end_date), f)

        tester.products = all_products.copy()
        ic_stats_all = pd.concat([f.ic_stats for f in factors], axis=1)
        ic_stats_all.rename(columns=lambda x: str(x), inplace=True)
        columns = ic_stats_all.columns.tolist()
        rows    = ic_stats_all.to_dict(orient='records')
        indices = ic_stats_all.index.tolist()
        for i, row in enumerate(rows):
            row['index'] = indices[i]

        response: dict = {
            'success': True,
            'paths_hash': paths_hash,
            'ic_stats': {'columns': ['index'] + columns, 'rows': rows},
            'factors': [],
        }

        for factor in factors:
            ic_s = factor.ic_series.dropna()
            if isinstance(ic_s.index, pd.MultiIndex):
                _sig = next((str(n) for n in ic_s.index.names if str(n).startswith('_SIGNAL')), None)
                _lvl = ic_s.index.names.index(_sig) if _sig else -1
                signal_ts = pd.DatetimeIndex(ic_s.index.get_level_values(_lvl))
            else:
                signal_ts = pd.DatetimeIndex(ic_s.index)
            _daily = factor.freq is not None and factor.freq.is_day_multiple()
            dates = [ts.strftime('%Y-%m-%d') for ts in signal_ts] if _daily else (signal_ts.view(np.int64) // 10**6).tolist()
            vals  = [None if (isinstance(v, float) and (pd.isna(v) or pd.isnull(v))) else v for v in ic_s.values.tolist()]
            response['factors'].append({
                'name': factor.name, 'alias': factor.alias,
                'ic_series': {'dates': dates, 'values': vals},
                'products': [
                    {'name': p.name, 'desc': getattr(p, 'desc', p.name)}
                    for p in (factor.table.columns if factor.table is not None else [])
                    if p in tester.products and isinstance(p, Product)
                ],
            })

        # Merge into tester.factors
        existing = {f.alias for f in tester.factors}
        for f in factors:
            if f.alias not in existing:
                tester.factors.append(f); existing.add(f.alias)
            else:
                for i, ef in enumerate(tester.factors):
                    if ef.alias == f.alias:
                        tester.factors[i] = f; break

        return jsonify(response)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()})
    finally:
        if _token is not None:
            _active_tester.reset(_token)
