"""构建总览期间的查找不得再次构建总览（否则登记会因递归膨胀而超时）。"""

from __future__ import annotations

import pytest

from server.modules.shared import factor_param_resolver as resolver


def test_lookup_inside_overview_build_does_not_rebuild(monkeypatch):
    calls = {"n": 0}

    def fake_overview(username, include_subordinates=False):
        calls["n"] += 1
        return {"factors": [], "families": []}

    monkeypatch.setattr(resolver, "build_factor_library_overview", fake_overview)
    resolver._overview_build.active = True
    try:
        with pytest.raises(Exception):
            resolver._find_visible_factor("SomeFamily|N:1d", username="probe")
    finally:
        resolver._overview_build.active = False
    assert calls["n"] == 0, "总览构建期间不得再次构建总览"


def test_top_level_lookup_builds_once_and_clears_the_flag(monkeypatch):
    calls = {"n": 0}

    def fake_overview(username, include_subordinates=False):
        calls["n"] += 1
        resolver._find_visible_factor("Nested|N:1d", username=username)  # 模拟构建过程中的解析
        return {"factors": [], "families": []}

    monkeypatch.setattr(resolver, "build_factor_library_overview", fake_overview)
    with pytest.raises(Exception):
        resolver._find_visible_factor("SomeFamily|N:1d", username="probe")
    assert calls["n"] == 1, "顶层查找只构建一次总览（嵌套查找不得再构建）"
    assert getattr(resolver._overview_build, "active", False) is False
