"""记录依赖列表的不变量：依赖 = 本行 params 引用到的因子（递归、按别名唯一）。

回归背景（实测）：配置的物化记录里同时留着同一别名的旧/新两条身份
（`TsHiPosPMDayScope|C:[119.0]|$F:30m` → `factor:v2:71IcUrs5…` 与 `factor:v2:BPfJTnFT…`）。
读取侧直接复用物化记录，于是整包被上报到工作区，平台别名唯一性守卫正确拒绝：

    400 factor alias must be unique: TsHiPosPMDayScope|C:[119.0]|$F:30m

收敛规则：只保留被 `identity.params` 引用到的依赖，并按别名去重（保留被引用的那条）；
带 `temporary` / `source_code` 的当场源码因子必须保留，否则内联因子执行不了。
"""

from __future__ import annotations

from server.modules.shared.factor_param_utils import (
    sanitize_factor_record_dependencies as sanitize,
)

PMT_ALIAS = "TsHiPosPMDayScope|C:[119.0]|$F:30m"


def _dep(ref, alias, **extra):
    return {"ref": ref, "alias": alias, "identity": {"family_alias": "X", "params": {}}, **extra}


def test_stale_duplicate_alias_is_collapsed_to_the_referenced_one():
    fresh = _dep("factor:v2:BPfJTnFT", PMT_ALIAS)
    stale = _dep("factor:v2:71IcUrs5", PMT_ALIAS)

    record = {
        "ref": "factor:v2:ROW",
        "alias": f"TsHistCmp|X:[{PMT_ALIAS}]|N:10d|$F:30m",
        "identity": {"params": {"X": "factor:v2:BPfJTnFT", "N": "10d"}},
        "factor_dependencies": [stale, fresh],
    }

    got = sanitize(record)["factor_dependencies"]
    assert got == [fresh]                      # 只留被引用的那条
    assert all(item["alias"] != PMT_ALIAS for item in got[1:])


def test_unreferenced_dependency_is_dropped():
    referenced = _dep("factor:v2:KEEP", "A")
    other = _dep("factor:v2:DROP", "B")
    record = {
        "identity": {"params": {"X": "factor:v2:KEEP"}},
        "factor_dependencies": [referenced, other],
    }
    assert sanitize(record)["factor_dependencies"] == [referenced]


def test_inline_source_dependencies_are_preserved():
    """当场源码/临时因子（无 ref 引用也要留），否则内联因子执行不了。"""
    inline = {"ref": "factor:v2:INLINE", "alias": "T", "source_code": "class T: ..."}
    temporary = {"ref": "factor:v2:TEMP", "alias": "U", "temporary": True}
    record = {
        "identity": {"params": {"X": "factor:v2:OTHER"}},
        "factor_dependencies": [inline, temporary],
    }
    kept = sanitize(record)["factor_dependencies"]
    assert inline in kept and temporary in kept


def test_nested_dependencies_are_sanitized_recursively():
    inner_fresh = _dep("factor:v2:IF", "P")
    inner_stale = _dep("factor:v2:IS", "P")
    parent = {
        "ref": "factor:v2:PARENT",
        "alias": "Parent",
        "identity": {"params": {"X": "factor:v2:IF"}},
        "factor_dependencies": [inner_stale, inner_fresh],
    }
    record = {
        "identity": {"params": {"X": "factor:v2:PARENT"}},
        "factor_dependencies": [parent],
    }
    got = sanitize(record)["factor_dependencies"]
    assert len(got) == 1
    assert got[0]["factor_dependencies"] == [inner_fresh]


def test_record_without_dependencies_is_untouched():
    record = {"ref": "factor:v2:LEAF", "identity": {"params": {"C": 119.0}}}
    assert sanitize(record) == record


def test_all_dependencies_dropped_removes_the_key():
    record = {
        "identity": {"params": {"X": "factor:v2:ONLY"}},
        "factor_dependencies": [_dep("factor:v2:OTHER", "Z")],
    }
    assert "factor_dependencies" not in sanitize(record)
