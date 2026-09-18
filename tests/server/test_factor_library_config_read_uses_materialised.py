"""读取家族配置时必须复用已物化的解析结果，不得每次重新解析整棵依赖链。

背景：GET /api/factor-library/configurations/<family> 逐行调用本函数；深链单实例解析数秒，
24 个实例即可把一次读取拖到数分钟并触发客户端 RemoteDisconnected（实测 >5 分钟且客户端断连）。
"""

import pytest

from server.modules.custom_factors import factor_library_service as service


def _config(params_list, resolved_factors):
    config = {'params_list': params_list, 'scope_key': 'default', 'product_group': 'default'}
    if resolved_factors is not None:
        config['resolved_factors'] = resolved_factors
    return config


@pytest.fixture(name='explode_if_resolved')
def explode_if_resolved_fixture(monkeypatch):
    calls = []

    def _boom(*args, **kwargs):
        calls.append(args)
        raise AssertionError('读取已物化的条目时不应再做实时解析')

    monkeypatch.setattr(service, 'build_factor_param_item', _boom)
    monkeypatch.setattr(service, 'resolve_param_factor_family', _boom)
    monkeypatch.setattr(service, 'hydrate_frozen_factor_params', _boom)
    return calls


def test_aligned_materialisation_is_reused_without_resolving(explode_if_resolved):
    stored = {'ref': 'factor:v2:AAA', 'alias': 'TsHistCmp|X:[TsDurDevDayScope]|N:[20d]',
              'identity': {'family_alias': 'TsHistCmp'}, 'schema_version': 2, 'scope_key': 'default'}
    config = _config([{'X': 'TsDurDevDayScope', 'N': '20d'}], [stored])

    item = service.build_library_factor_param_item(
        'GTHT@MaxJJW@1', {'username': 'GTHT@MaxJJW@1'}, 'TsHistCmp', config,
        config['params_list'][0], 0, {}, {},
    )

    assert explode_if_resolved == []          # 完全没走解析路径
    assert item['ref'] == 'factor:v2:AAA'
    assert item is not stored                 # 返回副本，调用方改不动存储


def test_materialisation_shorter_than_params_falls_back_to_resolution(monkeypatch):
    """物化条目缺失/不对齐时仍必须能用实时解析兜住（否则老配置读不出来）。"""
    called = []

    def _fallback(*args, **kwargs):
        called.append(args)
        return {'ref': 'factor:v2:LIVE', 'alias': 'live'}

    monkeypatch.setattr(service, 'build_factor_param_item', _fallback)
    monkeypatch.setattr(service, 'resolve_param_factor_family', lambda *a, **k: (None, {}))
    monkeypatch.setattr(service, 'hydrate_frozen_factor_params', lambda row, frozen: row)
    monkeypatch.setattr(service, '_configuration_frozen_factor_map', lambda config, row: {})
    monkeypatch.setattr(service, '_configuration_factor_resolver',
                        lambda config, user, values: __import__('contextlib').nullcontext())

    config = _config([{'X': 'a'}, {'X': 'b'}], [{'ref': 'factor:v2:AAA'}])  # 1 条 vs 2 行

    item = service.build_library_factor_param_item(
        'GTHT@MaxJJW@1', {'username': 'GTHT@MaxJJW@1'}, 'TsHistCmp', config,
        config['params_list'][1], 1, {}, {},
    )

    assert called, '不对齐时必须回退到实时解析'
    assert item['ref'] == 'factor:v2:LIVE'


def test_rows_without_materialisation_still_resolve(monkeypatch):
    called = []
    monkeypatch.setattr(service, 'build_factor_param_item',
                        lambda *a, **k: (called.append(a), {'ref': 'factor:v2:LIVE'})[1])
    monkeypatch.setattr(service, 'resolve_param_factor_family', lambda *a, **k: (None, {}))
    monkeypatch.setattr(service, 'hydrate_frozen_factor_params', lambda row, frozen: row)
    monkeypatch.setattr(service, '_configuration_frozen_factor_map', lambda config, row: {})
    monkeypatch.setattr(service, '_configuration_factor_resolver',
                        lambda config, user, values: __import__('contextlib').nullcontext())

    config = _config([{'X': 'a'}], None)

    item = service.build_library_factor_param_item(
        'GTHT@MaxJJW@1', {'username': 'GTHT@MaxJJW@1'}, 'TsHistCmp', config,
        config['params_list'][0], 0, {}, {},
    )

    assert called
    assert item['ref'] == 'factor:v2:LIVE'
