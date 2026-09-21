"""别名解析返回 Factor 对象时，保存路径必须把它冻结成规范记录（不得退回别名）。

回归背景：解析器按契约返回 Factor，而冻结函数此前只接受 dict 记录，导致「拿不到记录」
就退回别名存储，进而出现同一别名两条身份、提交被 400 拒绝（factor alias must be unique）。
"""

import pytest

from server.modules.shared import factor_param_utils as fpu
from tools.parameters import FactorParam


class _Expr:
    def semantic_fingerprint(self):
        return "a" * 64


class _Family:
    alias = "SgChgPct"
    expr = _Expr()

    def __init__(self):
        self.params = [FactorParam("P"), FactorParam("N")]
        self._params_list = [{"P": "CA", "N": "250d"}]


class _Factor:
    owner_ref = "GTHT@MaxJJW@392452984564"
    alias = "SgChgPct|P:[CA]|N:250d"
    expr = _Expr()

    def __init__(self):
        self._source_expr = _Expr()
        self.factor_family = _Family()


def test_resolved_factor_object_is_frozen_into_record(monkeypatch):
    import tools.factors.factor_param_resolution as resolution

    monkeypatch.setattr(
        resolution, "resolve_factor_param_value",
        lambda value, *a, **k: _Factor(), raising=True,
    )
    record = fpu.freeze_factor_param_alias(FactorParam("X"), "SgChgPct|P:[CA]|N:250d")
    assert isinstance(record, dict), record
    assert str(record.get("ref", "")).startswith("factor:v2:"), record
    identity = record.get("identity") or {}
    assert str(identity.get("family_ref", "")).startswith("factor-family:"), identity
    assert identity.get("family_alias") == "SgChgPct"
    assert identity.get("self_formula_fingerprint") == "a" * 64


def test_resolved_factor_without_owner_is_rejected(monkeypatch):
    import tools.factors.factor_param_resolution as resolution

    broken = _Factor()
    broken.owner_ref = ""
    monkeypatch.setattr(resolution, "resolve_factor_param_value",
                        lambda value, *a, **k: broken, raising=True)
    with pytest.raises(ValueError):
        fpu.freeze_factor_param_alias(FactorParam("X"), "SgChgPct|N:250d")


def test_constants_and_refs_are_untouched(monkeypatch):
    import tools.factors.factor_param_resolution as resolution

    def _boom(*a, **k):  # 不应被调用
        raise AssertionError("resolver should not be called")

    monkeypatch.setattr(resolution, "resolve_factor_param_value", _boom, raising=True)
    assert fpu.freeze_factor_param_alias(FactorParam("X"), "CA") is None
    assert fpu.freeze_factor_param_alias(FactorParam("X"), "factor:v2:" + "b" * 43) is None
