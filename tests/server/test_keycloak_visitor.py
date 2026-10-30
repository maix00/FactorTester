from __future__ import annotations

import json
import threading
from urllib.request import Request, urlopen

from server.identity.keycloak_visitor import (
    KeycloakVisitorPolicyProvider,
    VisitorPolicy,
)
from server.manager import runtime as manager
from server.manager.http.request_security import RequestSecurityMixin


class _Keycloak:
    def __init__(self, roles: list[str]) -> None:
        self.roles = roles
        self.grants = 0
        self.introspections = 0

    def client_credentials(self):
        self.grants += 1
        return {"access_token": "guest-token", "expires_in": 60}

    def introspect(self, token):
        self.introspections += 1
        assert token == "guest-token"
        return {
            "active": True,
            "iss": "https://id.example/realms/trade",
            "sub": "keycloak-guest-subject",
            "client_id": "tr-public-visitor",
            "exp": 4_000_000_000,
            "resource_access": {
                "tr-public-visitor": {"roles": self.roles},
            },
        }


def test_visitor_policy_is_projected_only_from_the_keycloak_service_account():
    client = _Keycloak(["access", "submit"])
    provider = KeycloakVisitorPolicyProvider(
        client,
        issuer="https://id.example/realms/trade",
        client_id="tr-public-visitor",
        roles_client_id="tr-public-visitor",
    )

    policy = provider.policy()

    assert policy == VisitorPolicy(
        "keycloak-guest-subject", frozenset({"access", "submit"})
    )
    assert policy.can_access is True
    assert policy.can_submit is True
    assert policy.can_download_artifacts is False
    assert client.grants == client.introspections == 1
    assert provider.policy() == policy
    assert client.grants == client.introspections == 1


def test_visitor_policy_fails_closed_on_wrong_client_or_missing_access_role():
    for role in ("submit", "artifact-download"):
        client = _Keycloak([role])
        provider = KeycloakVisitorPolicyProvider(
            client,
            issuer="https://id.example/realms/trade",
            client_id="tr-public-visitor",
            roles_client_id="tr-public-visitor",
        )
        assert provider.policy() is None

    client = _Keycloak(["access"])
    original = client.introspect

    def wrong_client(token):
        claims = original(token)
        claims["client_id"] = "manager-admin"
        return claims

    client.introspect = wrong_client
    provider = KeycloakVisitorPolicyProvider(
        client,
        issuer="https://id.example/realms/trade",
        client_id="tr-public-visitor",
        roles_client_id="tr-public-visitor",
    )
    assert provider.policy() is None


def _headers(cookie: str = "") -> dict[str, str]:
    values = {
        "Host": "101.133.144.27:7998",
        "X-Forwarded-Proto": "https",
        "X-Forwarded-For": "8.8.8.8",
    }
    if cookie:
        values["Cookie"] = cookie
    return values


def test_keycloak_guest_cookie_does_not_grant_without_keycloak_policy(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("TRADERESEARCH_AUTH_MODE", "keycloak")
    monkeypatch.setenv("FACTORTESTER_REQUIRE_LOGIN_FOR_UI", "1")
    monkeypatch.setenv("FACTORTESTER_PUBLIC_SERVER", "1")
    monkeypatch.setattr(manager, "control_store_from_env", lambda *_args: None)
    state = manager.ManagerState(tmp_path, "python", server_id="public-main")
    state.require_login_for_ui = True
    state.public_server = True
    origin = "https://101.133.144.27:7998"
    visitor_token = state.visitor_access.issue_session(origin)

    class _Probe(RequestSecurityMixin):
        def __init__(self, cookie: str = "") -> None:
            self.state = state
            self.client_address = ("127.0.0.1", 0)
            self.headers = _headers(cookie)
            self.redirects = []

        def _bearer_token(self) -> str:
            return ""

        def _send_redirect(self, location: str, **_kwargs) -> None:
            self.redirects.append(location)

    monkeypatch.setattr(
        RequestSecurityMixin,
        "_keycloak_visitor_policy",
        staticmethod(lambda: None),
    )
    probe = _Probe(f"ft-manager-visitor={visitor_token}")
    assert probe._visitor_mode() is None
    assert probe._anonymous_ui_allowed() is False


def test_keycloak_guest_entry_creates_ui_session_only_after_policy_check(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("TRADERESEARCH_AUTH_MODE", "keycloak")
    monkeypatch.setenv("FACTORTESTER_REQUIRE_LOGIN_FOR_UI", "1")
    monkeypatch.setenv("FACTORTESTER_PUBLIC_SERVER", "1")
    monkeypatch.setattr(manager, "control_store_from_env", lambda *_args: None)
    state = manager.ManagerState(tmp_path, "python", server_id="public-main")
    state.require_login_for_ui = True
    state.public_server = True
    state.manager_public_endpoint = "https://101.133.144.27:7998"
    policy = VisitorPolicy("keycloak-guest-subject", frozenset({"access"}))

    class _Probe(RequestSecurityMixin):
        def __init__(self) -> None:
            self.state = state
            self.client_address = ("127.0.0.1", 0)
            self.headers = _headers()
            self.redirects = []

        def _bearer_token(self) -> str:
            return ""

        def _send_redirect(self, location: str, **kwargs) -> None:
            self.redirects.append((location, kwargs.get("cookie", "")))

    monkeypatch.setattr(
        RequestSecurityMixin,
        "_keycloak_visitor_policy",
        staticmethod(lambda: policy),
    )
    grant = state.visitor_access.issue_grant(state.manager_public_endpoint)
    probe = _Probe()
    from urllib.parse import urlsplit

    probe._serve_visitor_entry(
        urlsplit(f"/visitor?grant={grant}&next=%2Fapp")
    )
    location, cookie = probe.redirects[0]
    assert location == "/app"
    assert cookie.startswith("ft-manager-visitor=")


def test_public_session_endpoint_projects_visitor_after_keycloak_policy(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("TRADERESEARCH_AUTH_MODE", "keycloak")
    monkeypatch.setenv("FACTORTESTER_REQUIRE_LOGIN_FOR_UI", "1")
    monkeypatch.setenv("FACTORTESTER_PUBLIC_SERVER", "1")
    monkeypatch.setattr(manager, "control_store_from_env", lambda *_args: None)
    state = manager.ManagerState(tmp_path, "python", server_id="public-main")
    state.require_login_for_ui = True
    state.public_server = True
    origin = "https://101.133.144.27:7998"
    visitor_token = state.visitor_access.issue_session(origin)
    policy = VisitorPolicy(
        "keycloak-guest-subject", frozenset({"access", "submit"})
    )
    monkeypatch.setattr(
        RequestSecurityMixin,
        "_keycloak_visitor_policy",
        staticmethod(lambda: policy),
    )
    manager.Handler.state = state
    server = manager.ThreadingHTTPServer(("127.0.0.1", 0), manager.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/session",
            headers=_headers(f"ft-manager-visitor={visitor_token}"),
        )
        with urlopen(request) as response:
            payload = json.loads(response.read())
        assert payload["username"] == "public-visitor"
        assert payload["role"] == "visitor"
        assert payload["visitor_login"] is True
        assert payload["keycloak_subject"] == "keycloak-guest-subject"
        assert payload["capabilities"] == {
            "manager": False,
            "research": False,
            "public_visitor": True,
        }
        assert payload["keycloak_roles"] == ["access", "submit"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
