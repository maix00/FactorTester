"""FactorParam 依赖收集必须「按本行引用」解析，不得回落到配置级并集。

回归背景（实测）：`build_factor_param_item` 原先在行内依赖为空时回落成
`metadata.factor_dependencies` 整包，而该并集里同时留着同一别名的**旧、新两条身份**
（`TsHiPosPMDayScope|C:[119.0]|$F:30m` → `factor:v2:71IcUrs5…` 与 `factor:v2:BPfJTnFT…`）。
行内 `X` 已是规范 ref 形态（不内联完整记录）时，`frozen_factor_record(ref)` 返回 None，
于是整包被上报 → 平台别名唯一性守卫正确拒绝：

    400 factor alias must be unique: TsHiPosPMDayScope|C:[119.0]|$F:30m

修法：ref 形态取值经由本配置的冻结映射解析出**该行自己的**依赖记录；即便需要回落，
也只保留行自身 params 里真正引用的 ref。
"""

from __future__ import annotations

from server.modules.shared import factor_param_utils


class _FakeFactorParam:
    """仅用于 isinstance 判据。"""


class _FakePlainParam:
    alias = "N"


def _param(alias="X"):
    param = _FakeFactorParam()
    param.alias = alias
    return param


def test_ref_form_dependency_is_resolved_from_frozen_map(monkeypatch):
    """`X` 存的是 factor:v2: ref 时，取回的是它自己那条记录，而不是整包并集。"""
    monkeypatch.setattr(factor_param_utils, "FactorParam", _FakeFactorParam)
    monkeypatch.setattr(factor_param_utils, "frozen_factor_record",
                        lambda value: value if isinstance(value, dict) else None)
    monkeypatch.setattr(factor_param_utils, "unique_frozen_factor_records", lambda values: list(values))

    own = {"ref": "factor:v2:OWN", "alias": "TsHiPosPMDayScope|C:[119.0]|$F:30m"}
    stale = {"ref": "factor:v2:STALE", "alias": "TsHiPosPMDayScope|C:[119.0]|$F:30m"}
    unrelated = {"ref": "factor:v2:OTHER", "alias": "TsDurDevDayScope|…"}

    got = factor_param_utils.frozen_factor_dependencies(
        [_param()], {"X": "factor:v2:OWN"},
        frozen_by_ref={"factor:v2:OWN": own, "factor:v2:STALE": stale, "factor:v2:OTHER": unrelated},
    )

    assert got == [own]                     # 只取本行引用的那条
    assert stale not in got                 # 陈旧同别名身份不得混入
    assert unrelated not in got             # 其它家族的依赖也不得混入


def test_inline_record_values_keep_working(monkeypatch):
    """内联完整记录（未修数据前的老形态）行为不变。"""
    monkeypatch.setattr(factor_param_utils, "FactorParam", _FakeFactorParam)
    monkeypatch.setattr(factor_param_utils, "frozen_factor_record",
                        lambda value: value if isinstance(value, dict) else None)
    monkeypatch.setattr(factor_param_utils, "unique_frozen_factor_records", lambda values: list(values))

    inline = {"ref": "factor:v2:INLINE", "alias": "A"}
    got = factor_param_utils.frozen_factor_dependencies([_param()], {"X": inline})
    assert got == [inline]


def test_runtime_factor_with_factor_ref_is_resolved(monkeypatch):
    """引擎交回的 Factor 对象只带 factor_ref 时，同样能取回记录。"""
    monkeypatch.setattr(factor_param_utils, "FactorParam", _FakeFactorParam)
    monkeypatch.setattr(factor_param_utils, "frozen_factor_record",
                        lambda value: value if isinstance(value, dict) else None)
    monkeypatch.setattr(factor_param_utils, "unique_frozen_factor_records", lambda values: list(values))

    class _Factor:
        factor_ref = "factor:v2:LIVE"

    rec = {"ref": "factor:v2:LIVE", "alias": "B"}
    got = factor_param_utils.frozen_factor_dependencies(
        [_param()], {"X": _Factor()}, frozen_by_ref={"factor:v2:LIVE": rec},
    )
    assert got == [rec]


def test_plain_params_are_ignored(monkeypatch):
    monkeypatch.setattr(factor_param_utils, "FactorParam", _FakeFactorParam)
    called = []
    monkeypatch.setattr(factor_param_utils, "frozen_factor_record",
                        lambda value: called.append(value) or None)
    monkeypatch.setattr(factor_param_utils, "unique_frozen_factor_records", lambda values: list(values))
    assert factor_param_utils.frozen_factor_dependencies([_FakePlainParam()], {"N": "20d"}) == []
    assert called == []


def test_referenced_records_exclude_stale_duplicate():
    """回落分支：同别名但未被本行引用的陈旧记录必须被排除。"""
    fresh = {"ref": "factor:v2:BPfJTnFT", "alias": "TsHiPosPMDayScope|C:[119.0]|$F:30m"}
    stale = {"ref": "factor:v2:71IcUrs5", "alias": "TsHiPosPMDayScope|C:[119.0]|$F:30m"}
    frozen_map = {fresh["ref"]: fresh, stale["ref"]: stale}
    frozen = {"params": {"X": fresh["ref"], "N": "20d"}}

    got = factor_param_utils.referenced_dependency_records(frozen, frozen_map)

    assert got == [fresh]
    assert stale not in got


def test_referenced_records_empty_when_row_has_no_reference():
    rec = {"ref": "factor:v2:ANY"}
    assert factor_param_utils.referenced_dependency_records({"params": {"V": "C", "C": 119.0}},
                                                            {rec["ref"]: rec}) == []
    assert factor_param_utils.referenced_dependency_records(None, {rec["ref"]: rec}) == []
