"""Native-client visitor entry remains separate from direct IP browser entry."""

from __future__ import annotations

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

import pytest

from server.manager import runtime as manager
from server.manager.http import visitor_access
from server.manager.http.visitor_access import (
    VisitorAccessStore,
    visitor_principal,
)


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


def test_visitor_access_uses_distinct_uuid_owner_namespaces() -> None:
    store = VisitorAccessStore()
    first = store.issue_session("https://101.133.144.27:7998")
    second = store.issue_session("https://101.133.144.27:7998")
    first_id = store.visitor_id_for_session(
        first, target_origin="https://101.133.144.27:7998",
    )
    second_id = store.visitor_id_for_session(
        second, target_origin="https://101.133.144.27:7998",
    )
    assert first_id and second_id and first_id != second_id
    assert visitor_principal(first_id).endswith(first_id)
    assert visitor_principal(second_id).endswith(second_id)


def test_redeeming_a_grant_twice_reuses_the_same_session() -> None:
    store = VisitorAccessStore()
    target = "https://101.133.144.27:7998"
    grant = store.issue_grant(target)

    first = store.redeem_grant(grant, target_origin=target)
    second = store.redeem_grant(grant, target_origin=target)

    assert first
    assert second == first
    assert store.valid_session(first, target_origin=target)


def test_device_bridge_is_bound_to_ingress_and_consumed_once() -> None:
    store = VisitorAccessStore()
    source = "https://eloquence-drizzly-fencing.ngrok-free.dev"
    target = "https://101.133.144.27:7998"
    bridge = store.issue_device_bridge(
        source_origin=source,
        target_origin=target,
    )

    assert store.device_bridge_target(bridge, source_origin=source) == target
    assert store.device_bridge_target(bridge, source_origin=target) == ""
    assert store.consume_device_bridge(
        bridge,
        source_origin=source,
        target_origin=target,
    )
    assert store.device_bridge_target(bridge, source_origin=source) == ""
    assert not store.consume_device_bridge(
        bridge,
        source_origin=source,
        target_origin=target,
    )


def test_direct_ip_compliance_offers_device_bridge_without_visitor_entry(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("FACTORTESTER_REQUIRE_LOGIN_FOR_UI", "1")
    monkeypatch.setenv("FACTORTESTER_REQUIRE_DEVICE_AUTH", "1")
    monkeypatch.setenv("FACTORTESTER_PUBLIC_SERVER", "1")
    monkeypatch.setenv(
        "FACTORTESTER_MANAGER_PUBLIC_ENDPOINT",
        "https://101.133.144.27:7998",
    )
    monkeypatch.setenv(
        "FACTORTESTER_PUBLIC_VISITOR_ORIGINS",
        "https://eloquence-drizzly-fencing.ngrok-free.dev",
    )
    state = manager.ManagerState(tmp_path, "python", server_id="public-main")
    opener = build_opener(_NoRedirect())

    with _running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}/compliance?next=%2Fjobs",
            headers=_headers(),
        )) as response:
            direct_body = response.read().decode("utf-8")

        bridge_match = re.search(
            r"https://eloquence-drizzly-fencing\.ngrok-free\.dev/device-bridge\?"
            r"bridge=([^\"&]+)&next=%2Fjobs",
            direct_body,
        )
        assert bridge_match
        bridge = bridge_match.group(1)

        bridge_request = Request(
            f"{base_url}/device-bridge?bridge={bridge}&next=%2Fjobs",
            headers={
                **_headers(),
                "Host": "eloquence-drizzly-fencing.ngrok-free.dev",
            },
        )
        with urlopen(bridge_request) as response:
            ingress_body = response.read().decode("utf-8")

    assert 'class="visitor-entry"' not in direct_body
    assert 'class="visitor-entry"' not in ingress_body
    assert 'const deviceBridge="' in ingress_body
    assert "101.133.144.27:7998/compliance" in ingress_body
    assert "device_bridge_failed=1" in ingress_body


def test_concurrent_grant_redeems_are_idempotent() -> None:
    store = VisitorAccessStore()
    target = "https://101.133.144.27:7998"
    grant = store.issue_grant(target)

    with ThreadPoolExecutor(max_workers=8) as executor:
        sessions = list(executor.map(
            lambda _: store.redeem_grant(grant, target_origin=target),
            range(8),
        ))

    assert sessions[0]
    assert all(session == sessions[0] for session in sessions)


def test_redeemed_grant_replay_expires(monkeypatch) -> None:
    store = VisitorAccessStore()
    target = "https://101.133.144.27:7998"
    now = 1_000.0
    monkeypatch.setattr(visitor_access.time, "time", lambda: now)
    grant = store.issue_grant(target)
    first = store.redeem_grant(grant, target_origin=target)

    monkeypatch.setattr(
        visitor_access.time,
        "time",
        lambda: now + visitor_access.VISITOR_GRANT_REPLAY_TTL_SECONDS + 1,
    )

    assert first
    assert store.redeem_grant(grant, target_origin=target) is None


def test_visitor_http_entry_replays_a_duplicate_grant(tmp_path) -> None:
    state = manager.ManagerState(
        tmp_path,
        "python",
        server_id="public-main",
    )
    state.visitor_access = VisitorAccessStore()
    state.require_login_for_ui = True
    state.require_device_auth = True
    state.public_server = True
    state.manager_public_endpoint = "https://101.133.144.27:7998"
    target = state.manager_public_endpoint
    grant = state.visitor_access.issue_grant(target)
    opener = build_opener(_NoRedirect())

    with _running_manager(state) as base_url:
        request = Request(
            f"{base_url}/visitor?grant={grant}&next=%2F",
            headers=_headers(),
        )
        with pytest.raises(HTTPError) as first_error:
            opener.open(request)
        with pytest.raises(HTTPError) as second_error:
            opener.open(request)

    assert first_error.value.code == 303
    assert second_error.value.code == 303
    assert first_error.value.headers["Location"] == "/"
    assert second_error.value.headers["Location"] == "/"
    assert first_error.value.headers["Set-Cookie"] == second_error.value.headers[
        "Set-Cookie"
    ]


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
