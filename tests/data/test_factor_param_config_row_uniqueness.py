"""登记行的唯一性是落库不变量：任何写入方都不能留下重复行。

历史缺陷：唯一性只由「追加」这一条路径（save_single_library_factor 的幂等检查）自己保证，
PUT /api/factor-library/configurations/<family> 把调用方给的列表原样落库，重复行因此可以从
任意写入方进来；随后按别名引用就变成「无法唯一解析」。
"""

from __future__ import annotations

import settings as Settings
from tools.data.account_manage import load_factor_param_config, save_factor_param_config
from tools.data.sqlite.account_manager.factor_param_config import save_factor_param_config_payload


def _use_tmp_db(monkeypatch, tmp_path):
    monkeypatch.setattr(Settings, 'CACHE_DB_PATH', tmp_path / 'dedupe.sqlite')


def test_duplicate_rows_dropped_and_materialisation_stays_aligned(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    rows = [{'X': 'A', 'N': '30d'}, {'X': 'A', 'N': '30d'}, {'X': 'A', 'N': '10d'},
            {'X': 'A', 'N': '30d'}]
    resolved = [{'ref': f'factor:v2:{i}'} for i in range(len(rows))]

    save_factor_param_config('alice', 'Fam', rows, resolved_factors=resolved)
    stored = load_factor_param_config('alice', 'Fam')

    # 首次出现的两行留下，后两条重复行丢弃
    assert stored['params_list'] == [rows[0], rows[2]]
    # 物化记录必须同序裁剪，否则「读取复用物化」会与 params_list 错位
    assert stored['resolved_factors'] == [resolved[0], resolved[2]]


def test_clean_config_is_written_untouched(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    rows = [{'X': 'A', 'N': '10d'}, {'X': 'A', 'N': '20d'}]

    save_factor_param_config('alice', 'Fam', rows, resolved_factors=[{'ref': 'a'}, {'ref': 'b'}])
    stored = load_factor_param_config('alice', 'Fam')

    assert stored['params_list'] == rows
    assert [item['ref'] for item in stored['resolved_factors']] == ['a', 'b']


def test_payload_choke_point_dedupes_for_writers_that_bypass_the_service(monkeypatch, tmp_path):
    """PUT/导入/镜像恢复等直接落 payload 的写入方同样受不变量保护。"""
    _use_tmp_db(monkeypatch, tmp_path)
    payload = {
        'id': 'alice', 'scope_key': 'default', 'product_group': 'default',
        'params_list': [{'X': 'B'}, {'X': 'B'}],
        'resolved_factors': [{'ref': 'first'}, {'ref': 'second'}],
    }

    save_factor_param_config_payload('alice', 'Fam', payload, 'default')
    stored = load_factor_param_config('alice', 'Fam')

    assert stored['params_list'] == [{'X': 'B'}]
    assert stored['resolved_factors'] == [{'ref': 'first'}]


def test_rows_that_differ_only_in_key_order_are_the_same_registration(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    rows = [{'X': 'A', 'N': '30d'}, {'N': '30d', 'X': 'A'}]

    save_factor_param_config('alice', 'Fam', rows)

    assert load_factor_param_config('alice', 'Fam')['params_list'] == [{'X': 'A', 'N': '30d'}]
