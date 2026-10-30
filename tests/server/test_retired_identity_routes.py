from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from server.manager import runtime


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/admin/access-control"),
    ("DELETE", "/api/admin/public-visitor-allowlist"),
    ("POST", "/api/admin/access-control/devices/revoke"),
])
def test_removed_local_identity_apis_never_fall_through_to_service_proxy(
    method, path, tmp_path,
):
    class Handler(runtime.Handler):
        def _redirect_plain_http_to_https(self):
            return False

        def _public_login_gate(self, _parsed, *, method):
            return True

        def _proxy_authenticated_local_service(self, *_args, **_kwargs):
            raise AssertionError("retired identity API reached a service proxy")

    Handler.state = runtime.ManagerState(tmp_path, "python")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(
            f"http://127.0.0.1:{server.server_port}{path}",
            method=method,
            data=b"{}" if method in {"POST", "DELETE"} else None,
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(HTTPError) as failure:
            urlopen(request)
        assert failure.value.code == 410
        payload = json.loads(failure.value.read().decode("utf-8"))
        assert payload["code"] == "keycloak_managed_identity"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize(
    ("path", "expected_code"),
    (
        ("/auth/login", "keycloak_login_required"),
        ("/auth/register", "keycloak_registration_required"),
    ),
)
def test_local_password_and_public_registration_are_retired(
    path, expected_code, tmp_path,
):
    class Handler(runtime.Handler):
        def _redirect_plain_http_to_https(self):
            return False

        def _public_login_gate(self, _parsed, *, method):
            return True

    Handler.state = runtime.ManagerState(tmp_path, "python")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(
            f"http://127.0.0.1:{server.server_port}{path}",
            method="POST",
            data=b'{"username":"alice","password":"not-used"}',
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(HTTPError) as failure:
            urlopen(request)
        assert failure.value.code == 410
        payload = json.loads(failure.value.read().decode("utf-8"))
        assert payload["code"] == expected_code
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
