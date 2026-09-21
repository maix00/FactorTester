"""记录依赖列表的不变量：依赖 = 本行 params 引用到的因子（递归、按别名唯一）。

回归背景（实测）：配置的物化记录里同时留着同一别名的旧/新两条身份
（`TsHiPosPMDayScope|C:[119.0]|$F:30m` → `factor:v2:71IcUrs5…` 与 `factor:v2:BPfJTnFT…`）。
读取侧直接复用物化记录，于是整包被上报到工作区，平台别名唯一性守卫正确拒绝：

    400 factor alias must be unique: TsHiPosPMDayScope|C:[119.0]|$F:30m

收敛规则：只保留被 `identity.params` 引用到的依赖，并按别名去重（保留被引用的那条）；
带 `temporary` / `source_code` 的当场源码因子必须保留，否则内联因子执行不了。
"""

from __future__ import annotations

import pytest

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
        "identity": {"params": {"X": inline["ref"]}},
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


def test_missing_referenced_dependency_is_reported():
    record = {
        "identity": {"params": {"X": "factor:v2:ONLY"}},
        "factor_dependencies": [_dep("factor:v2:OTHER", "Z")],
    }
    with pytest.raises(ValueError, match="依赖记录缺失: factor:v2:ONLY"):
        sanitize(record)


def test_flat_transport_keeps_transitive_child_without_expanding_graph():
    child = _dep("factor:v2:CHILD", "Child")
    parent = _dep("factor:v2:PARENT", "Parent")
    parent["identity"]["params"] = {"X": child["ref"]}
    stale = _dep("factor:v2:STALE", "Child")
    record = {
        "identity": {"params": {"X": parent["ref"]}},
        "factor_dependencies": [parent, stale, child],
    }

    got = sanitize(record)["factor_dependencies"]
    assert got == [parent, child]
    assert all("factor_dependencies" not in item for item in got)


def test_two_reachable_versions_of_one_alias_are_rejected():
    first = _dep("factor:v2:FIRST", "Same")
    second = _dep("factor:v2:SECOND", "Same")
    record = {
        "identity": {"params": {"X": first["ref"], "Y": second["ref"]}},
        "factor_dependencies": [first, second],
    }
    with pytest.raises(ValueError, match="多个被引用的冻结身份: Same"):
        sanitize(record)


def test_legacy_alias_is_kept_only_when_it_identifies_one_record():
    alias = "Nested|N:10d"
    only = _dep("factor:v2:ONLY", alias)
    record = {
        "identity": {"params": {"X": alias}},
        "factor_dependencies": [only, _dep("factor:v2:STALE", "Stale")],
    }
    assert sanitize(record)["factor_dependencies"] == [only]


def test_legacy_alias_with_two_versions_is_not_guessed_by_list_order():
    alias = "Nested|N:10d"
    record = {
        "identity": {"params": {"X": alias}},
        "factor_dependencies": [
            _dep("factor:v2:OLD", alias), _dep("factor:v2:NEW", alias),
        ],
    }
    with pytest.raises(ValueError, match="无法确定旧参数引用"):
        sanitize(record)


def test_cycle_in_flat_transport_is_rejected():
    first = _dep("factor:v2:FIRST", "First")
    second = _dep("factor:v2:SECOND", "Second")
    first["identity"]["params"] = {"X": second["ref"]}
    second["identity"]["params"] = {"X": first["ref"]}
    record = {
        "identity": {"params": {"X": first["ref"]}},
        "factor_dependencies": [first, second],
    }
    with pytest.raises(ValueError, match="依赖形成循环"):
        sanitize(record)
