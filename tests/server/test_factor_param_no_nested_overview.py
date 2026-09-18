"""总览构建期间，参数查找必须按家族直接解析，而非重建总览（否则递归 + 十几秒）。"""

from __future__ import annotations

import pytest

from server.modules.shared import factor_param_resolver as resolver


class _FakeFactor:
    alias = "SomeFamily|N:1d"


class _FakeInstance:
    def factor_from_alias(self, alias):
        return _FakeFactor()

    def parse_alias(self, alias):
        return {"N": "1d", "$F": "30m"}


def test_lookup_during_overview_build_resolves_via_registry(monkeypatch):
    """总览构建期间的查找：不重建总览，直接按家族解析并返回正确记录。"""
    calls = {"overview": 0}

    def fake_overview(username, include_subordinates=False):
        calls["overview"] += 1
        raise AssertionError("构建总览期间不得再次构建总览")

    monkeypatch.setattr(resolver, "build_factor_library_overview", fake_overview)
    monkeypatch.setattr(resolver, "get_factor_family_instance",
                        lambda module_name, username=None: _FakeInstance())
    resolver._overview_build.active = True
    try:
        item = resolver._find_visible_factor("SomeFamily|N:1d", username="probe")
    finally:
        resolver._overview_build.active = False
    assert calls["overview"] == 0
    assert item["factor_family_alias"] == "SomeFamily"
    assert item["factor_alias"] == "SomeFamily|N:1d"
    assert item["params"] == [{"alias": "N", "value": "1d"}, {"alias": "$F", "value": "30m"}]


def test_lookup_during_overview_build_reports_missing_family(monkeypatch):
    """家族不存在时给与主路径一致的「找不到且无法唯一解析」错误，而不是挂死。"""
    monkeypatch.setattr(resolver, "build_factor_library_overview",
                        lambda *a, **k: {"factors": [], "families": []})
    monkeypatch.setattr(resolver, "get_factor_family_instance",
                        lambda module_name, username=None: (_ for _ in ()).throw(ImportError("missing")))
    resolver._overview_build.active = True
    try:
        with pytest.raises(ValueError, match="找不到且无法唯一解析"):
            resolver._find_visible_factor("Missing|N:1d", username="probe")
    finally:
        resolver._overview_build.active = False


def test_top_level_lookup_still_builds_once(monkeypatch):
    calls = {"overview": 0}

    def fake_overview(username, include_subordinates=False):
        calls["overview"] += 1
        return {"factors": [], "families": []}

    monkeypatch.setattr(resolver, "build_factor_library_overview", fake_overview)
    with pytest.raises(ValueError):
        resolver._find_visible_factor("SomeFamily|N:1d", username="probe")
    assert calls["overview"] == 1
    assert getattr(resolver._overview_build, "active", False) is False
