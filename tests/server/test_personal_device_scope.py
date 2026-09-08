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
        public_device_total_count=lambda **kw: len(listing(include_disabled=False, **kw)),
        backend_status=lambda: {'backend': 'postgresql'},
        revoke=lambda device_id: revoked.append(device_id) or records[0],
    )
    route = device_routes.DeviceNetworkRoutesMixin()
    route.state = SimpleNamespace(device_registry=registry, server_id='public')
    route._session = lambda: {'username': 'alice', 'role': role}
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
