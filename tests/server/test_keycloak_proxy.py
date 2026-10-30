from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from urllib.request import HTTPRedirectHandler, Request, build_opener

from server.manager.http.keycloak_proxy import (
    KeycloakProxyRoutesMixin,
    _allowed_path,
)


def test_keycloak_proxy_path_is_limited_to_configured_realm():
    assert _allowed_path("/identity/realms/trade/protocol/openid-connect/auth", "trade")
    assert _allowed_path("/identity/resources/abc/admin/app.js", "trade")
    assert _allowed_path("/identity/admin/trade/console/", "trade")
    assert _allowed_path("/identity/admin/realms/trade/users", "trade")
    assert not _allowed_path("/identity/admin/master/console/", "trade")
    assert not _allowed_path("/identity/realms/other/protocol/openid-connect/auth", "trade")
    assert not _allowed_path("/identity/admin/realms/trade/../master/users", "trade")
    assert not _allowed_path("/identity/admin/realms/trade/%2e%2e/master", "trade")
    assert not _allowed_path("/identityevil/realms/trade", "trade")


def test_proxy_forwards_fixed_realm_and_rewrites_private_redirect(
    monkeypatch,
):
    backend_requests = []

    class Backend(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            backend_requests.append((self.path, self.headers.get("X-Forwarded-Host")))
            body = b"keycloak-response"
            self.send_response(302)
            self.send_header("Location", f"http://{self.headers['Host']}/identity/continue")
            self.send_header("Set-Cookie", "AUTH_SESSION_ID=one; Path=/identity; HttpOnly")
            self.send_header("Set-Cookie", "KC_RESTART=two; Path=/identity; HttpOnly")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    backend = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
    backend_thread = threading.Thread(target=backend.serve_forever, daemon=True)
    backend_thread.start()
    monkeypatch.setenv(
        "TR_KEYCLOAK_PROXY_BACKEND_URL",
        f"http://127.0.0.1:{backend.server_address[1]}",
    )
    monkeypatch.setattr(
        "server.manager.http.keycloak_proxy._realm", lambda: "trade",
    )

    class State:
        manager_public_endpoint = "https://101.133.144.27:7998"

    class ProxyHandler(KeycloakProxyRoutesMixin, BaseHTTPRequestHandler):
        state = State()

        def _is_secure_transport(self):
            return True

        def _client_ip(self):
            return "192.0.2.25"

        def do_GET(self):  # noqa: N802
            from urllib.parse import urlsplit

            self._proxy_keycloak(urlsplit(self.path), method="GET")

        def log_message(self, *_args):
            pass

    proxy = ThreadingHTTPServer(("127.0.0.1", 0), ProxyHandler)
    proxy_thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    proxy_thread.start()
    try:
        request = Request(
            f"http://127.0.0.1:{proxy.server_address[1]}"
            "/identity/realms/trade/protocol/openid-connect/auth?client_id=manager",
            headers={"Cookie": "AUTH_SESSION_ID=browser", "Accept": "text/html"},
        )
        class DoNotRedirect(HTTPRedirectHandler):
            def redirect_request(self, *_args, **_kwargs):
                return None

        opener = build_opener(DoNotRedirect)
        try:
            opener.open(request, timeout=3)
        except Exception as exc:
            assert getattr(exc, "code", None) == 302
            assert exc.headers.get("Location") == (
                "https://101.133.144.27:7998/identity/continue"
            )
            cookies = exc.headers.get_all("Set-Cookie")
            assert len(cookies) == 2
            assert exc.read() == b"keycloak-response"
        assert backend_requests == [(
            "/identity/realms/trade/protocol/openid-connect/auth?client_id=manager",
            "101.133.144.27:7998",
        )]
    finally:
        proxy.shutdown()
        proxy.server_close()
        backend.shutdown()
        backend.server_close()

