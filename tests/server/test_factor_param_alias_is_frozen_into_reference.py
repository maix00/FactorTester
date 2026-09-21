"""FactorParam 槽位填裸别名时，必须由代码解析并冻结成规范 ref。

平台既有形态是 factor:v2: ref（唯一标识，全库 37 处嵌套参数都是这一形态）。
此前服务层对字符串取值按原样存储，导致「别名形态」的行被写进库：冻结侧与校验侧对同一行
算出不同的 self_formula_fingerprint，任何由库身份冻结的 RunSpec 都被判
"factor formula changed after RunSpec freeze"。调用方只应给别名，ref 必须由代码派生。
"""

from __future__ import annotations

import pytest

from server.modules.shared import factor_param_utils


class _DummyFactorParam:
    """仅用于 isinstance 判据。"""


class _DummyPlainParam:
    """非 FactorParam：一律不参与解析。"""


@pytest.fixture(name='param_kind')
def param_kind_fixture(monkeypatch):
    monkeypatch.setattr(factor_param_utils, 'FactorParam', _DummyFactorParam)
    return _DummyFactorParam


def test_alias_is_resolved_and_frozen_into_a_reference(monkeypatch, param_kind):
    sentinel = object()
    monkeypatch.setattr(factor_param_utils, 'frozen_factor_record',
                        lambda value: {'ref': 'factor:v2:DERIVED', 'identity': {}, 'schema_version': 2}
                        if value is sentinel else None)

    import tools.factors.factor_param_resolution as resolution
    monkeypatch.setattr(resolution, 'resolve_factor_param_value',
                        lambda value: sentinel if value == 'TsHiPosPMDayScope|C:[119.0]|$F:30m' else None)

    frozen = factor_param_utils.freeze_factor_param_alias(
        param_kind(), 'TsHiPosPMDayScope|C:[119.0]|$F:30m',
    )

    assert frozen is not None
    assert frozen['ref'] == 'factor:v2:DERIVED'          # ref 由代码派生，非调用方手写


@pytest.mark.parametrize('value', ['2m', 'CA', '119.0', '', '   '])
def test_constants_and_columns_are_left_alone(monkeypatch, param_kind, value):
    """常值/列引用不带参数段，不得被包装成因子。"""
    import tools.factors.factor_param_resolution as resolution
    monkeypatch.setattr(resolution, 'resolve_factor_param_value',
                        lambda _value: pytest.fail('常值/列不应参与解析'))

    assert factor_param_utils.freeze_factor_param_alias(param_kind(), value) is None


def test_existing_reference_is_not_reprocessed(monkeypatch, param_kind):
    import tools.factors.factor_param_resolution as resolution
    monkeypatch.setattr(resolution, 'resolve_factor_param_value',
                        lambda _value: pytest.fail('已是 ref 不应再解析'))

    assert factor_param_utils.freeze_factor_param_alias(
        param_kind(), 'factor:v2:ALREADY0000000000000000000000000000000000',
    ) is None


def test_resolver_failure_is_not_silently_stored(monkeypatch, param_kind):
    """解析基础设施故障必须阻止写入未冻结别名。"""
    import tools.factors.factor_param_resolution as resolution

    def _boom(_value):
        raise RuntimeError('No FactorParam resolver is registered.')

    monkeypatch.setattr(resolution, 'resolve_factor_param_value', _boom)

    with pytest.raises(RuntimeError, match='No FactorParam resolver'):
        factor_param_utils.freeze_factor_param_alias(
            param_kind(), 'SomeFamily|N:[10d]',
        )


def test_resolver_returning_none_is_rejected(monkeypatch, param_kind):
    import tools.factors.factor_param_resolution as resolution
    monkeypatch.setattr(resolution, 'resolve_factor_param_value', lambda _value: None)

    with pytest.raises(ValueError, match='could not be resolved'):
        factor_param_utils.freeze_factor_param_alias(
            param_kind(), 'SomeFamily|N:[10d]',
        )


def test_non_factor_param_slots_are_untouched(monkeypatch):
    import tools.factors.factor_param_resolution as resolution
    monkeypatch.setattr(resolution, 'resolve_factor_param_value',
                        lambda _value: pytest.fail('非 FactorParam 槽位不应解析'))

    assert factor_param_utils.freeze_factor_param_alias(
        _DummyPlainParam(), 'SomeFamily|N:[10d]',
    ) is None
