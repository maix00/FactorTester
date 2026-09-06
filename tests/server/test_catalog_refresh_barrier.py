from threading import Event
from io import BytesIO
from types import SimpleNamespace

import pytest

from server.manager.services.client_state import ClientStateService


@pytest.mark.parametrize('body', [b'', b'{}'])
def test_refresh_consumes_request_before_sending_response(body, monkeypatch):
    from server.manager.http.auth_routes import AuthenticationRoutesMixin
    from server.manager.http.write_routes import WriteRoutesMixin

    class Handler(WriteRoutesMixin, AuthenticationRoutesMixin):
        path = '/api/catalog/refresh'
        headers = {'Content-Length': str(len(body))}
        rfile = BytesIO(body)

        def _redirect_plain_http_to_https(self):
            return False

        def _public_login_gate(self, *args, **kwargs):
            return True

        def _session(self):
            return {'username': 'alice'}

    handler = Handler()
    handler.state = SimpleNamespace(client_state=SimpleNamespace(
        refresh_account_catalog=lambda _: {'status': 'synced'},
    ))
    responses = []

    def respond(handler, payload, status):
        # Unread TLS application data can reset a closing HTTP/1.0 response.
        assert handler.rfile.read() == b''
        responses.append((payload, status))

    monkeypatch.setattr('server.manager.http.write_routes.json_response', respond)
    handler.do_POST()
    assert responses == [({'success': True, 'sync': {'status': 'synced'}}, 200)]


def test_refresh_waits_for_read_after_write_and_bypasses_cooldown(tmp_path, monkeypatch):
    calls = []

    class Sync:
        access_cooldown = 100

        def sync(self, principal, *, force=False):
            calls.append((principal, force))
            return {"status": "synced"}

    monkeypatch.setattr(
        "server.manager.services.subordinate_factor_library.direct_subordinate_accounts",
        lambda *args: [],
    )
    client = ClientStateService(tmp_path, account_domain_sync=Sync())
    assert client.refresh_account_catalog("alice")["status"] == "synced"
    assert client.refresh_account_catalog("alice")["status"] == "synced"
    assert calls == [("alice", True), ("alice", True)]


def test_write_during_inflight_refresh_requests_another_pass(tmp_path, monkeypatch):
    entered, finish, repeated = Event(), Event(), Event()
    calls = []

    class Sync:
        access_cooldown = 100

        def sync(self, principal, *, force=False):
            calls.append(force)
            if len(calls) == 1:
                entered.set()
                assert finish.wait(2)
            else:
                repeated.set()
            return {"status": "synced"}

    monkeypatch.setattr(
        "server.manager.services.subordinate_factor_library.direct_subordinate_accounts",
        lambda *args: [],
    )
    client = ClientStateService(tmp_path, account_domain_sync=Sync())
    client._refresh_account_domain_async("alice")
    assert entered.wait(2)
    client._refresh_account_domain_async("alice", force=True)
    finish.set()
    assert repeated.wait(2)
    assert calls == [False, True]
