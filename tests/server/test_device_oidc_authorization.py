"""A signed device proof is not an authorization to create a Manager session."""
from types import SimpleNamespace
from urllib.parse import urlsplit

from server.manager.domain.devices import DeviceChallengeStore, device_public_key_digest
from server.manager.http.auth_routes import AuthenticationRoutesMixin
from server.manager.http import device_routes


KEY = {"kty": "EC", "crv": "P-256", "x": "A" * 43, "y": "A" * 43}
OTHER_KEY = {**KEY, "x": "B" * 42 + "A"}
DEVICE = "device-1234567890123456"


def test_ticket_binds_key_origin_and_is_one_use():
    tickets = DeviceChallengeStore()
    ticket = tickets.issue_device_login_ticket(username="alice", device_id=DEVICE,
                                               origin="https://manager", public_key=KEY)
    assert tickets.consume_device_login_ticket(ticket, origin="https://manager") == (
        "alice", DEVICE, device_public_key_digest(KEY),
    )
    import pytest
    with pytest.raises(PermissionError):
        tickets.consume_device_login_ticket(ticket, origin="https://manager")


def test_device_proof_returns_oidc_handoff_not_a_manager_session(monkeypatch):
    responses = []
    monkeypatch.setattr(device_routes, 'json_response',
                        lambda _handler, payload, status=200, **_kw: responses.append((status, payload)))
    tickets = DeviceChallengeStore()
    challenge_id, _challenge = tickets.issue()
    handler = device_routes.DeviceNetworkRoutesMixin()
    handler.state = SimpleNamespace(device_challenges=tickets, device_registry=SimpleNamespace(
        verify=lambda **_kwargs: {'username': 'alice', 'device_id': DEVICE, 'public_key': KEY}))
    handler._has_secure_ui_transport = lambda: True
    handler._json_body = lambda _limit: {'challenge_id': challenge_id, 'device_id': DEVICE,
                                         'public_key': KEY, 'signature': 'verified-by-registry'}
    handler._request_origin = lambda: 'https://manager'
    handler._client_ip = lambda: '192.0.2.1'
    handler._device_verify()
    status, response = responses[-1]
    assert status == 200 and response['requires_keycloak'] is True
    assert response['login_url'].startswith('/auth/oidc/start?')
    assert 'device_ticket=' in response['login_url']
    assert 'token' not in response and 'username' not in response


def test_oidc_device_login_rechecks_keycloak_and_device_key(monkeypatch):
    from server.identity import keycloak_device, manager_oidc, server_admission

    session = {"username": "alice", "keycloak_subject": "subject-1", "tr_identity_id": "stable-1"}
    monkeypatch.setattr(manager_oidc, "finish_login", lambda **_: ("token", session, "/app", "ticket"))
    monkeypatch.setattr(server_admission, "server_admission", lambda *_args, **_kwargs: (True, ""))
    state = {"allowed": True, "key": KEY}
    monkeypatch.setattr(keycloak_device, "may_use_device", lambda **_: state["allowed"])

    class Handler(AuthenticationRoutesMixin):
        state = SimpleNamespace(server_id="manager-1", device_challenges=SimpleNamespace(
            consume_device_login_ticket=lambda *_args, **_kwargs: ("alice", DEVICE, device_public_key_digest(KEY)),
        ), device_registry=SimpleNamespace(key_binding=lambda **_kwargs: {"public_key": state["key"], "enabled": True}))

        def _cookie_value(self, _name): return "expected"
        def _is_secure_transport(self): return True
        def _request_origin(self): return "https://manager"
        def _send_redirect(self, path, *, cookie): self.result = (path, cookie)

    handler = Handler()
    callback = urlsplit("/auth/oidc/callback?state=expected&code=example")
    handler._oidc_login_callback(callback)
    assert handler.result[0] == "/app"
    state["allowed"] = False
    handler._oidc_login_callback(callback)
    assert handler.result[0] == "/app?auth_error=device"
    state.update(allowed=True, key=OTHER_KEY)
    handler._oidc_login_callback(callback)
    assert handler.result[0] == "/app?auth_error=device"
