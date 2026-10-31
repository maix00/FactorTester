from types import SimpleNamespace

import pytest
from server.manager.http import device_routes


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
    ))
    route._session = lambda: {'username': 'alice'}
    route._has_secure_ui_transport = lambda: True
    route._device_request_metadata = lambda: {}
    route._json_body = lambda _limit: {'device_id': 'mine', 'public_key': 'key'}
    route._device_enroll()
    assert responses[-1] == 503
    assert revoked == ['mine']
