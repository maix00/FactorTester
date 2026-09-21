"""保存路径必须把 FactorParam 槽位里的**因子别名**冻结成规范记录。

回归背景：调用方（API/CLI/前端）给 FactorParam 槽位传裸别名时，曾经因为解析结果（Factor）
拿不到冻结记录而被静默退回别名形态，使同一行在冻结侧与校验侧算出不同的
self_formula_fingerprint，最终表现为「factor formula changed」或「factor alias must be unique」。
"""

import pytest

from server.modules.custom_factors import factor_library_service as fls
from tools.parameters import FactorParam


class _Expr:
    def semantic_fingerprint(self) -> str:
        return "a" * 64


class _NestedFamily:
    alias = "TsHiPosPMDayScope"

    def __init__(self):
        self.params = []
        self.expr = _Expr()
        self.seen_alias = None

    def factor_from_alias(self, alias):
        self.seen_alias = alias
        return _Factor(alias)


class _Factor:
    def __init__(self, alias):
        self.alias = alias
        self.expr = _Expr()


class _ParentFamily:
    def __init__(self):
        self.params = [FactorParam("X"), FactorParam("N")]


def _patch(monkeypatch, item):
    nested = _NestedFamily()
    monkeypatch.setattr(
        fls, "get_factor_family_instance",
        lambda family_alias, username=None: nested, raising=True,
    )
    # 桩家族不实现参数归一化；这一步由平台既有测试覆盖，这里只验证冻结这一环。
    monkeypatch.setattr(
        fls, "normalize_factor_param_row",
        lambda family, params: dict(params), raising=True,
    )
    import server.modules.shared.factor_param_resolver as resolver
    monkeypatch.setattr(
        resolver, "_find_visible_factor",
        lambda alias, username=None: item, raising=True,
    )
    return nested


def test_alias_valued_factor_param_is_frozen_into_reference(monkeypatch):
    """别名 → 规范记录（带 ref），且 ref 由代码派生，调用方不必手写。"""
    nested = _patch(monkeypatch, {
        "factor_alias": "TsHiPosPMDayScope|C:[119.0]|$F:30m",
        "factor_family_alias": "TsHiPosPMDayScope",
        "owner_username": "GTHT@MaxJJW@392452984564",
        "owner_ref": "account:MaxJJW",
        "params": [{"alias": "C", "value": 119.0}, {"alias": "$F", "value": "30m"}],
    })
    rows = fls._freeze_alias_factor_param_rows(
        "GTHT@MaxJJW@392452984564", _ParentFamily(),
        [{"X": "TsHiPosPMDayScope|C:[119.0]|$F:30m", "N": "20d"}],
    )
    frozen = rows[0]["X"]
    assert isinstance(frozen, dict), frozen
    assert str(frozen.get("ref", "")).startswith("factor:v2:"), frozen
    assert frozen.get("identity"), frozen
    assert nested.seen_alias == "TsHiPosPMDayScope|C:[119.0]|$F:30m"
    # 非因子槽位不受影响
    assert rows[0]["N"] == "20d"


def test_constant_and_column_values_are_left_alone(monkeypatch):
    """列引用与常值不参与解析（'30m'、'CA' 原样保留）。"""
    _patch(monkeypatch, {})  # 若被调用会因缺少家族信息而报错，从而暴露误判
    rows = fls._freeze_alias_factor_param_rows(
        "u", _ParentFamily(), [{"X": "CA", "N": "30m"}],
    )
    assert rows[0] == {"X": "CA", "N": "30m"}


def test_unresolvable_alias_raises_instead_of_silently_storing_alias(monkeypatch):
    """解析不到必须报错，不能静默按别名落库。"""
    import server.modules.shared.factor_param_resolver as resolver

    def _boom(alias, username=None):
        raise ValueError(f"因子库中找不到且无法唯一解析因子: {alias}")

    monkeypatch.setattr(resolver, "_find_visible_factor", _boom, raising=True)
    monkeypatch.setattr(fls, "get_factor_family_instance", lambda *a, **k: _NestedFamily())
    with pytest.raises(ValueError):
        fls._freeze_alias_factor_param_rows(
            "u", _ParentFamily(), [{"X": "NoSuchFamily|N:20d", "N": "20d"}],
        )


def test_already_frozen_reference_is_untouched(monkeypatch):
    """已经是 ref 的取值不再二次解析。"""
    _patch(monkeypatch, {})  # 同样：被调用即报错
    ref = "factor:v2:" + "a" * 43
    rows = fls._freeze_alias_factor_param_rows("u", _ParentFamily(), [{"X": ref, "N": "20d"}])
    assert rows[0]["X"] == ref
