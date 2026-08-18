from __future__ import annotations

from server.manager.http.mihomo_proxy import _remove_token
from server.manager.http.mihomo_routes import MihomoDashboardRoutesMixin


def test_dashboard_proxy_drops_browser_controller_token() -> None:
    assert _remove_token("/traffic?token=browser-secret&interval=1") == "/traffic?interval=1"


def test_dashboard_proxy_only_allows_safe_mutations() -> None:
    allowed = MihomoDashboardRoutesMixin._mihomo_write_allowed

    assert allowed("DELETE", "/connections") is True
    assert allowed("DELETE", "/connections/abc") is True
    assert allowed("PUT", "/proxies/main") is True
    assert allowed("POST", "/configs") is False
    assert allowed("PUT", "/configs") is False
