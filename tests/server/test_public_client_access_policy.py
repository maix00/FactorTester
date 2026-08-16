"""Native-client visitor entry remains separate from direct IP browser entry."""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from server.manager import runtime as manager


@contextmanager
def _running_manager(state):
    manager.Handler.state = state
    server = manager.ThreadingHTTPServer(("127.0.0.1", 0), manager.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def _headers(*, cookie: str = "", client: bool = False) -> dict[str, str]:
    value = {
        "Host": "101.133.144.27:7998",
        "X-Forwarded-Proto": "https",
        "X-Forwarded-For": "8.8.8.8",
    }
    if cookie:
        value["Cookie"] = cookie
    if client:
        value["X-FactorTester-Client-Access"] = "ftclient"
    return value


def test_native_client_entry_does_not_make_direct_ip_browser_entry_public(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("FACTORTESTER_REQUIRE_LOGIN_FOR_UI", "1")
    monkeypatch.setenv("FACTORTESTER_REQUIRE_DEVICE_AUTH", "1")
    monkeypatch.setenv("FACTORTESTER_PUBLIC_SERVER", "1")
    monkeypatch.setenv(
        "FACTORTESTER_MANAGER_PUBLIC_ENDPOINT",
        "https://101.133.144.27:7998",
    )
    state = manager.ManagerState(tmp_path, "python", server_id="public-main")
    monkeypatch.setattr(state, "worktrees", lambda: [])
    opener = build_opener(_NoRedirect())

    with _running_manager(state) as base_url:
        native = Request(
            f"{base_url}/jobs",
            headers=_headers(client=True),
        )
        try:
            opener.open(native)
        except HTTPError as error:
            assert error.code == 303
            assert error.headers["Location"].startswith("/compliance?")
            client_cookie = error.headers["Set-Cookie"].split(";", 1)[0]
        else:  # pragma: no cover - the gate must redirect an unauthenticated client
            raise AssertionError("native client unexpectedly bypassed the login gate")

        with urlopen(Request(
            f"{base_url}/compliance?next=%2Fjobs",
            headers=_headers(cookie=client_cookie),
        )) as response:
            compliance = response.read().decode("utf-8")
        assert 'class="visitor-entry"' in compliance

        try:
            opener.open(Request(
                f"{base_url}/visitor?next=%2Fjobs",
                headers=_headers(cookie=client_cookie),
            ))
        except HTTPError as error:
            assert error.code == 303
            assert error.headers["Location"] == "/jobs"
            visitor_cookie = error.headers["Set-Cookie"].split(";", 1)[0]
        else:  # pragma: no cover - visitor entry is an explicit redirect action
            raise AssertionError("native visitor entry did not create a session")

        with urlopen(Request(
            f"{base_url}/compliance",
            headers=_headers(),
        )) as response:
            direct_ip = response.read().decode("utf-8")
        assert 'class="visitor-entry"' not in direct_ip

        try:
            urlopen(Request(
                f"{base_url}/api/jobs",
                headers=_headers(client=True),
            ))
        except HTTPError as error:
            # A native-client marker is never an API/authentication bypass.
            assert error.code == 401
            payload = json.loads(error.read())
            assert payload["success"] is False
            assert "required" in payload["error"]
        else:  # pragma: no cover - the marker must not bypass API auth
            raise AssertionError("native client marker bypassed API authentication")

        with urlopen(Request(
            f"{base_url}/compliance",
            headers=_headers(cookie=visitor_cookie),
        )) as response:
            visitor_compliance = response.read().decode("utf-8")
        assert 'class="visitor-entry"' not in visitor_compliance
