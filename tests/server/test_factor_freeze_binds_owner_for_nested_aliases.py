"""冻结复权定义时，嵌套别名必须带 owner 解析。

背景：TsHistCmp（用户自定义家族）的 X 参数是另一个用户自定义家族的别名
（如 TsDurDevDayScope|Dur:[...]）。_load_revision_definition 直接调用
family.factor_from_alias(alias)，解析嵌套别名时没有解析器作用域，
get_factor_family_instance 拿不到 username → 退化成「公共注册表里没有 + 无活动会话」→
submit 报 400「factor formula cannot be frozen」，交易日对齐一族全部无法提交回测。
"""

import pytest

from server.modules.shared import factor_param_resolver as fpr
from server.services import factor_revisions


class _FakeExpr:
    def semantic_fingerprint(self):
        return 'fp-family'


class _FakeFactor:
    expr = object()


class _FakeFamily:
    """factor_from_alias 内部会解析嵌套别名（走 scoped resolver）。"""

    expr = _FakeExpr()

    def parse_alias(self, alias):
        return {"X": "TsDurDevDayScope|Dur:[x]"}

    def factor_from_alias(self, alias):
        # 真实实现经由 tools.factors.factor_param_resolution 的 scoped resolver
        from tools.factors.factor_param_resolution import resolve_factor_param_value as scoped

        scoped("TsDurDevDayScope|Dur:[x]")
        return _FakeFactor()


@pytest.fixture(name='nested_resolution_calls')
def nested_resolution_calls_fixture(monkeypatch):
    calls = []
    normalized = []

    def _record(value, **kwargs):
        calls.append((value, kwargs.get('username')))
        return {'ref': 'factor:v2:NESTED'}

    def _normalize(family, params):
        normalized.append(params)
        return params

    monkeypatch.setattr(fpr, 'resolve_factor_param_value', _record)
    monkeypatch.setattr(factor_revisions, 'normalize_factor_param_row', _normalize)
    monkeypatch.setattr(factor_revisions, 'resolve_factor_family_source',
                        lambda ref, username=None: {'canonical_family_ref': f'{username}:TsHistCmp'})
    monkeypatch.setattr(factor_revisions, 'get_factor_family_instance',
                        lambda ref, username=None: _FakeFamily())
    monkeypatch.setattr(factor_revisions, 'instantiate_factor_metadata',
                        lambda family, params, username=None: {
                            'self_formula_fingerprint': 'fp', 'normalized_params': params})
    monkeypatch.setattr(factor_revisions, 'fixed_column_refs', lambda expr: {'col'})
    return calls


def test_nested_alias_is_resolved_with_the_owner_username(nested_resolution_calls):
    factor_revisions._load_revision_definition(
        family_ref='TsHistCmp',
        factor_aliases=['TsHistCmp|X:[TsDurDevDayScope|Dur:[x]]|N:20d|$F:30m'],
        owner='GTHT@MaxJJW@392452984564',
    )

    assert nested_resolution_calls, '嵌套别名应当被解析'
    assert [username for _, username in nested_resolution_calls] == ['GTHT@MaxJJW@392452984564']


def test_frozen_definition_keeps_alias_fingerprint_and_columns(nested_resolution_calls):
    definition = factor_revisions._load_revision_definition(
        family_ref='TsHistCmp',
        factor_aliases=['TsHistCmp|X:[TsDurDevDayScope|Dur:[x]]|N:20d|$F:30m'],
        owner='GTHT@MaxJJW@392452984564',
    )

    assert definition['factor_family_alias'] == 'TsHistCmp'
    assert definition['factor_owner_ref'] == 'GTHT@MaxJJW@392452984564'
    assert definition['resolved_factors'][0]['column_refs'] == ['col']


def test_freeze_normalises_params_through_the_canonical_row_normaliser(monkeypatch):
    """回归根因：别名解析出的 '119.0'（字符串）必须经 canonical 归一化。

    family.parse_alias 只做语法切分，数值参数仍是字符串；登记路径物化的身份里是 119.0（数值）。
    两侧不归一化时 self_formula_fingerprint 与 params 不等，服务端守卫会把任何由库里身份
    冻结出来的 RunSpec 判成「factor formula changed after RunSpec freeze」。
    """
    seen = []

    monkeypatch.setattr(fpr, 'resolve_factor_param_value',
                        lambda value, **kwargs: {'ref': 'factor:v2:NESTED'})
    monkeypatch.setattr(factor_revisions, 'resolve_factor_family_source',
                        lambda ref, username=None: {'canonical_family_ref': f'{username}:TsHistCmp'})
    monkeypatch.setattr(factor_revisions, 'get_factor_family_instance',
                        lambda ref, username=None: _FakeFamily())
    monkeypatch.setattr(factor_revisions, 'instantiate_factor_metadata',
                        lambda family, params, username=None: {
                            'self_formula_fingerprint': 'fp', 'normalized_params': params})
    monkeypatch.setattr(factor_revisions, 'fixed_column_refs', lambda expr: {'col'})

    def _normalize(family, params):
        seen.append(dict(params))
        return {**params, 'C': 119.0}

    monkeypatch.setattr(factor_revisions, 'normalize_factor_param_row', _normalize)

    definition = factor_revisions._load_revision_definition(
        family_ref='TsHistCmp',
        factor_aliases=['TsHistCmp|X:[TsDurDevDayScope|Dur:[x]]|N:20d|$F:30m'],
        owner='GTHT@MaxJJW@392452984564',
    )

    assert seen, '冻结路径必须走 canonical 归一化'
    assert definition['resolved_factors'][0]['params']['C'] == 119.0