"""Device grants must be bound to a stable user, Manager and actual key."""
from server.identity import keycloak_device
from server.manager.domain.devices import device_public_key_digest
import pytest


KEY = {"kty": "EC", "crv": "P-256", "x": "A" * 43, "y": "A" * 43}
OTHER_KEY = {**KEY, "x": "B" * 42 + "A"}
DEVICE = "device-1234567890123456"
SESSION = {"keycloak_subject": "subject-1", "keycloak_issuer": "https://id.example/realms/tr",
           "tr_identity_id": "stable-1", "username": "alice"}


@pytest.fixture(autouse=True)
def _issuer(monkeypatch):
    monkeypatch.setattr(keycloak_device, "oidc_settings", lambda: {"issuer": SESSION["keycloak_issuer"]})


def _ref(**changes):
    return keycloak_device.device_resource_ref(**({"server_id": "manager-1", "identity_id": "stable-1",
                                                   "device_id": DEVICE, "public_key": KEY} | changes))


def test_device_identity_includes_full_key_manager_and_stable_user():
    base = _ref()
    assert device_public_key_digest(KEY) in base
    assert len({base, _ref(server_id="manager-2"), _ref(identity_id="stable-2"),
                _ref(public_key=OTHER_KEY)}) == 4
    # Extra JWK metadata never changes the key identity.
    assert _ref(public_key={**KEY, "untrusted": "ignored"}) == base
    with pytest.raises(ValueError):
        _ref(identity_id="")


def test_grant_check_is_fresh_and_never_registers(monkeypatch):
    calls = []
    monkeypatch.setattr(keycloak_device, "ensure_keycloak_resource",
                        lambda **kwargs: calls.append(("register", kwargs)) or "resource")
    granted = {"value": True}
    def authorized(token, **kwargs):
        calls.append(("check", kwargs))
        return {kwargs["refs"][0][1]} if granted["value"] else set()
    monkeypatch.setattr(keycloak_device, "keycloak_authorized_objects", authorized)
    assert keycloak_device.may_use_device(token="verified", session=SESSION,
        server_id="manager-1", device_id=DEVICE, public_key=KEY)
    granted["value"] = False
    assert not keycloak_device.may_use_device(token="verified", session=SESSION,
        server_id="manager-1", device_id=DEVICE, public_key=KEY)
    assert all(kind == "check" and kwargs["use_cache"] is False for kind, kwargs in calls)
    with pytest.raises(PermissionError):
        keycloak_device.may_use_device(token="verified", session={**SESSION, "keycloak_issuer": "https://other"},
            server_id="manager-1", device_id=DEVICE, public_key=KEY)


def test_only_explicit_enrollment_registers_and_revocation_uses_owner(monkeypatch):
    calls = []
    monkeypatch.setattr(keycloak_device, "ensure_keycloak_resource",
                        lambda **kwargs: calls.append(kwargs) or "resource")
    monkeypatch.setattr(keycloak_device, "delete_keycloak_resource",
                        lambda **kwargs: calls.append(kwargs) or True)
    assert keycloak_device.register_device(session=SESSION, server_id="manager-1", device_id=DEVICE, public_key=KEY) == "resource"
    assert keycloak_device.revoke_device(session=SESSION, server_id="manager-1", device_id=DEVICE, public_key=KEY)
    assert calls[0]["owner_scopes"] == ("use",)
    assert calls[0]["resource_ref"] == calls[1]["resource_ref"]
    assert calls[1]["owner_subject"] == "subject-1"
    with pytest.raises(ValueError):
        keycloak_device.revoke_device_for_owner(owner_subject="", identity_id="stable-1",
            server_id="manager-1", device_id=DEVICE, public_key=KEY)


def test_batch_device_check_is_owner_scoped_and_never_uses_cached_grants(monkeypatch):
    calls = []
    def authorized(token, **kwargs):
        calls.append((token, kwargs))
        return {kwargs['refs'][0][1]}
    monkeypatch.setattr(keycloak_device, 'keycloak_authorized_objects', authorized)
    rows = [{'device_id': DEVICE, 'username': 'alice', 'public_key': KEY, 'enabled': True, 'source_server_id': 'manager-1'},
            {'device_id': 'device-1234567890123457', 'username': 'alice', 'public_key': OTHER_KEY, 'enabled': False, 'source_server_id': 'manager-1'}]
    assert keycloak_device.may_use_devices(token='verified', session=SESSION, server_id='manager-1', records=rows) == {DEVICE}
    assert len(calls) == 1 and len(calls[0][1]['refs']) == 1 and calls[0][1]['use_cache'] is False
    with pytest.raises(ValueError):
        keycloak_device.may_use_devices(token='verified', session=SESSION, server_id='manager-1', records=[{**rows[0], 'username': 'bob'}])
    with pytest.raises(ValueError):
        keycloak_device.may_use_devices(token='verified', session=SESSION, server_id='manager-1', records=[rows[0], rows[0]])
    with pytest.raises(ValueError):
        keycloak_device.may_use_devices(token='verified', session=SESSION, server_id='manager-1', records=[{**rows[0], 'source_server_id': 'manager-2'}])
