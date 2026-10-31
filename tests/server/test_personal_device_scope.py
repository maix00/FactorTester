from types import SimpleNamespace

import pytest
from server.manager.http import device_routes


@pytest.mark.parametrize('session,allowed,expected_owner,expected_scope', [
    (None, False, '', 'server'),
    ({'username': 'alice', 'role': 'super_admin'}, False, 'alice', 'account'),
    ({'username': 'alice', 'role': 'user'}, True, '', 'server'),
    ({'username': 'alice', 'role': 'user'}, False, 'alice', 'account'),
])
def test_device_summary_uses_current_keycloak_administration(session, allowed, expected_owner, expected_scope, monkeypatch):
    responses, owners = [], []
    monkeypatch.setattr(device_routes, 'json_response',
                        lambda _handler, payload, status=200, **_kw: responses.append((status, payload)))
    monkeypatch.setattr('server.identity.server_admission.current_manager_role', lambda *_args: allowed)
    route = device_routes.DeviceNetworkRoutesMixin()
    route._session = lambda: session
    route.state = SimpleNamespace(device_registry=SimpleNamespace(
        public_device_total_count=lambda *, username: owners.append(username) or 2,
        public_user_count=lambda: 2,
        backend_status=lambda: {},
    ))
    route._device_summary()
    assert responses[-1][0] == 200
    assert responses[-1][1]['scope'] == expected_scope
    assert owners == [expected_owner]


def test_device_summary_rejects_session_without_user(monkeypatch):
    responses = []
    monkeypatch.setattr(device_routes, 'json_response', lambda _handler, payload, status=200, **_kw: responses.append(status))
    monkeypatch.setattr('server.identity.server_admission.current_manager_role', lambda *_args: False)
    route = device_routes.DeviceNetworkRoutesMixin()
    route._session = lambda: {'role': 'super_admin'}
    route._device_summary()
    assert responses == [403]


@pytest.mark.parametrize('role', ['user', 'super_admin'])
def test_personal_devices_and_revoke_always_use_current_owner(role, monkeypatch):
    responses = []
    monkeypatch.setattr(device_routes, 'json_response',
                        lambda handler, payload, status=200, **kw: responses.append((status, payload)))
    records = [{'device_id': 'mine', 'username': 'alice'},
               {'device_id': 'other', 'username': 'bob'}]
    revoked = []
    queried = []
    def listing(*, username, include_disabled):
        queried.append(username)
        return [r for r in records if r['username'] == username]
    registry = SimpleNamespace(
        list=listing,
        key_binding=lambda **kw: {'public_key': 'key'},
        public_device_total_count=lambda **kw: len(listing(include_disabled=False, **kw)),
        backend_status=lambda: {'backend': 'postgresql'},
        revoke=lambda device_id: revoked.append(device_id) or records[0],
    )
    route = device_routes.DeviceNetworkRoutesMixin()
    route.state = SimpleNamespace(device_registry=registry, server_id='public')
    route._session = lambda: {'username': 'alice', 'role': role}
    monkeypatch.setattr('server.identity.keycloak_device.revoke_device', lambda **kw: True)
    route._device_list()
    assert responses[-1][1]['devices'] == [records[0]]
    assert responses[-1][1]['public_device_total_count'] == 1
    route._json_body = lambda limit: {'device_id': 'other'}
    route._device_revoke()
    assert responses[-1][0] == 403
    assert revoked == []
    route._json_body = lambda limit: {'device_id': 'mine'}
    route._device_revoke()
    assert responses[-1][0] == 200
    assert revoked == ['mine']
    assert set(queried) == {'alice'}


def test_revoke_does_not_report_success_if_keycloak_fails(monkeypatch):
    responses, revoked = [], []
    monkeypatch.setattr(device_routes, 'json_response', lambda _h, payload, status=200, **_kw: responses.append(status))
    def fail(**_kw):
        raise RuntimeError('unavailable')
    monkeypatch.setattr('server.identity.keycloak_device.revoke_device', fail)
    route = device_routes.DeviceNetworkRoutesMixin()
    route.state = SimpleNamespace(server_id='public', device_registry=SimpleNamespace(
        list=lambda **_kw: [{'device_id': 'mine'}],
        key_binding=lambda **_kw: {'public_key': 'key'},
        revoke=lambda key: revoked.append(key),
    ))
    route._session = lambda: {'username': 'alice'}
    route._json_body = lambda _limit: {'device_id': 'mine'}
    route._device_revoke()
    assert responses[-1] == 503
    assert revoked == []


def test_enrollment_disables_record_if_keycloak_grant_fails(monkeypatch):
    responses, revoked = [], []
    monkeypatch.setattr(device_routes, 'json_response', lambda _h, payload, status=200, **_kw: responses.append(status))
    def fail(**_kw):
        raise RuntimeError('unavailable')
    monkeypatch.setattr('server.identity.keycloak_device.register_device', fail)
    route = device_routes.DeviceNetworkRoutesMixin()
    route.state = SimpleNamespace(server_id='public', public_server=False, device_registry=SimpleNamespace(
        enroll=lambda **_kw: {'device_id': 'mine'}, revoke=lambda key: revoked.append(key),
        key_binding=lambda **_kw: None,
    ))
    route._session = lambda: {'username': 'alice'}
    route._has_secure_ui_transport = lambda: True
    route._device_request_metadata = lambda: {}
    route._json_body = lambda _limit: {'device_id': 'mine', 'public_key': 'key'}
    route._device_enroll()
    assert responses[-1] == 503
    assert revoked == ['mine']


def test_failed_enrollment_can_be_retried_explicitly(monkeypatch):
    responses, calls = [], []
    monkeypatch.setattr(device_routes, 'json_response', lambda _h, payload, status=200, **_kw: responses.append(status))
    monkeypatch.setattr('server.identity.keycloak_device.register_device', lambda **kw: calls.append(kw))
    route = device_routes.DeviceNetworkRoutesMixin()
    route.state = SimpleNamespace(server_id='public', public_server=False, device_registry=SimpleNamespace(
        key_binding=lambda **kw: {'enabled': False},
        retry_enrollment=lambda **kw: {'device_id': kw['device_id']},
        backend_status=lambda: {},
    ))
    route._session = lambda: {'username': 'alice'}
    route._has_secure_ui_transport = lambda: True
    route._device_request_metadata = lambda: {}
    route._json_body = lambda _limit: {'device_id': 'mine', 'public_key': 'key'}
    route._device_enroll()
    assert responses[-1] == 201
    assert calls[0]['device_id'] == 'mine'
