"""整库总览在一次解析中只构建一次（原先每个别名都重建，嵌套链下呈平方级）。"""

from __future__ import annotations

import pytest
from flask import Flask

from server.modules.shared import factor_param_resolver as resolver


class _CountingOverview:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, username, include_subordinates=False):
        self.calls += 1
        return {"factors": [], "families": []}


@pytest.fixture()
def counting(monkeypatch):
    counter = _CountingOverview()
    monkeypatch.setattr(resolver, "build_factor_library_overview", counter)
    return counter


def test_overview_is_built_once_per_request(counting):
    with Flask(__name__).test_request_context("/"):
        resolver._visible_library_overview("GTHT@MaxJJW")
        resolver._visible_library_overview("GTHT@MaxJJW")
        resolver._visible_library_overview("GTHT@MaxJJW")
    assert counting.calls == 1


def test_overview_is_not_shared_between_requests(counting):
    app = Flask(__name__)
    with app.test_request_context("/"):
        resolver._visible_library_overview("GTHT@MaxJJW")
    with app.test_request_context("/"):
        resolver._visible_library_overview("GTHT@MaxJJW")
    assert counting.calls == 2, "跨请求必须重新构建，否则会读到过期总览"


def test_overview_is_built_without_a_request_context(counting):
    resolver._visible_library_overview("GTHT@MaxJJW")
    resolver._visible_library_overview("GTHT@MaxJJW")
    assert counting.calls == 2
