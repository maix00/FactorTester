"""构建整库总览时不得再触发总览构建（否则解析与总览互相递归，请求永不返回）。"""

from __future__ import annotations

import pytest

from server.modules.shared import factor_param_resolver as resolver


def _counting(monkeypatch):
    calls = {"overview": 0}

    def fake_overview(username, include_subordinates=False):
        calls["overview"] += 1
        return {"factors": [], "families": []}

    monkeypatch.setattr(resolver, "build_factor_library_overview", fake_overview)
    return calls


def test_lookup_inside_an_overview_build_never_rebuilds_the_overview(monkeypatch):
    calls = _counting(monkeypatch)
    resolver._overview_build.active = True
    try:
        with pytest.raises(Exception):
            resolver._find_visible_factor("AnyFamily|N:1d", username="probe-user")
    finally:
        resolver._overview_build.active = False
    assert calls["overview"] == 0, "构建总览期间不得再次构建总览，否则递归"


def test_normal_lookup_builds_the_overview_once(monkeypatch):
    calls = _counting(monkeypatch)
    with pytest.raises(Exception):
        resolver._find_visible_factor("AnyFamily|N:1d", username="probe-user")
    assert calls["overview"] == 1


def test_flag_is_cleared_even_when_the_build_raises(monkeypatch):
    def boom(username, include_subordinates=False):
        raise RuntimeError("overview failed")

    monkeypatch.setattr(resolver, "build_factor_library_overview", boom)
    with pytest.raises(RuntimeError):
        resolver._find_visible_factor("AnyFamily|N:1d", username="probe-user")
    assert getattr(resolver._overview_build, "active", False) is False
