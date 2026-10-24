"""Manager Nautilus preview routing must stay authenticated and local."""

from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

from server.manager.http.job_proxy_routes import JobProxyRoutesMixin


class _Handler(JobProxyRoutesMixin):
    def __init__(self, *, authenticated: bool, route_server: str = "local-a") -> None:
        self.authenticated = authenticated
        self.route_server = route_server
        self.state = SimpleNamespace(server_id="local-a")
        self.headers = {}
        self.rfile = BytesIO()
        self.status = None
        self.routed = False

    def _session(self):
        return {"username": "tester"} if self.authenticated else None

    def _service_route(self, _parsed):
        return SimpleNamespace(server_id=self.route_server)

    def _send_gateway_response(self, *_args, **_kwargs):
        self.routed = True

    def send_response(self, status):
        self.status = status

    def send_header(self, *_args):
        pass

    def end_headers(self):
        pass

    @property
    def wfile(self):
        return BytesIO()


def test_nautilus_preview_requires_manager_session():
    handler = _Handler(authenticated=False)
    parsed = SimpleNamespace(path="/api/nautilus/capabilities", query="")
    assert handler._proxy_nautilus_preview(parsed, method="GET") is True
    assert handler.status == 401
    assert handler.routed is False


def test_nautilus_preview_rejects_remote_route_from_branch_selector():
    handler = _Handler(authenticated=True, route_server="remote-b")
    parsed = SimpleNamespace(
        path="/api/nautilus/capabilities", query="branch=another",
    )
    assert handler._proxy_nautilus_preview(parsed, method="GET") is True
    assert handler.status == 403
    assert handler.routed is False


def test_nautilus_preview_does_not_allow_trading_commands():
    handler = _Handler(authenticated=True)
    parsed = SimpleNamespace(path="/api/nautilus/orders", query="")
    assert handler._proxy_nautilus_preview(parsed, method="POST") is False
    assert handler.routed is False
