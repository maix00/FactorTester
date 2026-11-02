"""Manager control actions require a live Keycloak grant or a machine capability."""

from io import BytesIO
from types import SimpleNamespace

import pytest

from server.identity import server_admission
from server.manager.http import write_routes
from server.manager.http.service_selection import ServiceSelectionRoutesMixin


class _Handler(write_routes.WriteRoutesMixin):
    def __init__(self, path, *, session=None, capability=False):
        self.path = path
        self.session = session
        self.capability = capability
        self.headers = {"Content-Length": "13", "Origin": "http://127.0.0.1"}
        self.rfile = BytesIO(b"instance_id=x")
        self.state = SimpleNamespace()
        self.executed = []
        self.reply = None

    def __getattr__(self, name):
        if name.startswith("_"):
            return lambda *_args, **_kwargs: False
        raise AttributeError(name)

    def _public_login_gate(self, *_args, **_kwargs):
        return True

    def _session(self):
        return self.session

    def _has_capability(self):
        return self.capability

    def _has_api_authorization(self):
        return self.capability

    def _is_same_origin_browser_action(self):
        return True

    def _require_capability(self):
        self.reply = (401, {"error": "manager capability required"})

    def _resolve_operation(self, identifier):
        return lambda: self.executed.append(identifier) or "done"


@pytest.fixture
def replies(monkeypatch):
    monkeypatch.setattr(
        write_routes, "json_response",
        lambda handler, body, status=200, **_kwargs: setattr(handler, "reply", (status, body)),
    )


def test_same_origin_anonymous_cannot_restart_manager(replies):
    handler = _Handler("/restart-api")
    handler.do_POST()
    assert handler.reply[0] == 401
    assert handler.executed == []


@pytest.mark.parametrize("path", ["/restart-api", "/api/dispatch/requeue"])
def test_revoked_admin_role_in_old_token_cannot_control_manager(path, replies, monkeypatch):
    monkeypatch.setattr(server_admission, "current_manager_role", lambda *_args: False)
    handler = _Handler(path, session={
        "username": "alice", "keycloak_roles": ("admin_console:manage",),
    })
    handler.do_POST()
    assert handler.reply[0] == 403
    assert handler.executed == []


def test_live_admin_and_machine_capability_can_control_manager(replies, monkeypatch):
    monkeypatch.setattr(server_admission, "current_manager_role", lambda *_args: True)
    for handler in (
        _Handler("/restart-api", session={"username": "alice"}),
        _Handler("/restart-api", capability=True),
    ):
        handler.do_POST()
        assert handler.reply[0] == 200
        assert handler.executed == ["x"]


def test_manager_api_gate_checks_current_role_not_cached_capability(monkeypatch):
    session = {"username": "alice", "capabilities": {"manager": True},
               "keycloak_roles": ("admin_console:manage",)}

    class Selection(ServiceSelectionRoutesMixin):
        state = SimpleNamespace(session=lambda _token: session)
        def _bearer_token(self): return "old-token"
        def _has_secure_ui_transport(self): return True
        def _has_capability(self): return False

    selection = Selection()
    monkeypatch.setattr(server_admission, "current_manager_role", lambda *_args: False)
    assert not selection._has_api_authorization()
    monkeypatch.setattr(server_admission, "current_manager_role", lambda *_args: True)
    assert selection._has_api_authorization()
