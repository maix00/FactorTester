from __future__ import annotations

from types import SimpleNamespace

import pytest

from server.identity.realm_groups import (
    component,
    level_admin_group_path,
    level_group_path,
    organization_admin_group_path,
    organization_group_path,
)
from server.manager.http import device_admin_routes


class _AdminAdapter:
    def __init__(self, group_paths: dict[str, list[str]]) -> None:
        self.group_paths = group_paths

    def user_id(self, username: str) -> str:
        if username not in self.group_paths:
            raise LookupError(username)
        return username

    def user_group_paths(self, user_id: str, *, page_size: int, max_groups: int):
        assert page_size == 100
        assert max_groups == 2000
        return self.group_paths[user_id]


class _Route(device_admin_routes.DeviceAdministrationRoutesMixin):
    def __init__(self, session, group_paths):
        self.response = None
        self.session = session
        self.path = "/api/admin/devices?username=alice"
        rows = [{"device_id": "device-1234567890", "username": "alice", "enabled": True}]
        self.revoked = []
        self.state = SimpleNamespace(server_id='manager', device_registry=SimpleNamespace(
            list=lambda *, username, include_disabled: (
                rows if username == "alice" and include_disabled else []
            ),
            public_device_total_count=lambda *, username: 1 if username == "alice" else 0,
            revoke=lambda device_id, **_kw: self.revoked.append(device_id) or rows[0],
            key_binding=lambda **kw: {'public_key': 'key'},
            backend_status=lambda: {"backend": "control-db"},
        ))
        self.adapter = _AdminAdapter(group_paths)

    def _session(self):
        return self.session

    def _has_secure_ui_transport(self):
        return True

    def _json_body(self, _limit):
        return {"username": "alice", "device_id": "device-1234567890"}


@pytest.fixture
def responses(monkeypatch):
    values = []
    monkeypatch.setattr(
        device_admin_routes, "json_response",
        lambda _handler, payload, status=200, **kwargs: values.append((status, payload, kwargs)),
    )
    monkeypatch.setattr('server.identity.keycloak_research.resolve_keycloak_research_member',
                        lambda username: {'subject': username, 'identity_id': 'stable-' + username})
    monkeypatch.setattr('server.identity.keycloak_device.revoke_device_for_owner', lambda **kw: True)
    return values


def test_admin_revoke_keeps_record_if_keycloak_unavailable(monkeypatch, responses):
    admin = _Route({'username': 'root'}, {'alice': []})
    monkeypatch.setattr(device_admin_routes, 'current_manager_role', lambda *_: True)
    monkeypatch.setattr(device_admin_routes, 'current_administrative_groups', lambda *_: ())
    def fail(**_kw):
        raise RuntimeError('unavailable')
    monkeypatch.setattr('server.identity.keycloak_device.revoke_device_for_owner', fail)
    admin._admin_device_revoke()
    assert responses[-1][0] == 503
    assert admin.revoked == []


def test_admin_cannot_revoke_another_managers_device(monkeypatch, responses, tmp_path):
    from server.manager.domain.devices import DeviceRegistry

    admin = _Route({'username': 'root'}, {'alice': []})
    registry = DeviceRegistry(tmp_path / 'devices.json', server_id='manager')
    registry.apply_snapshot(source_server_id='remote', generation=1, devices=[{
        'device_id': 'device-1234567890', 'username': 'alice', 'enabled': True,
        'public_key': {'kty': 'EC', 'crv': 'P-256', 'x': 'A' * 43, 'y': 'A' * 43},
    }])
    admin.state.device_registry = registry
    monkeypatch.setattr(device_admin_routes, 'current_manager_role', lambda *_: True)
    monkeypatch.setattr(device_admin_routes, 'current_administrative_groups', lambda *_: ())
    called = []
    monkeypatch.setattr('server.identity.keycloak_device.revoke_device_for_owner',
                        lambda **kw: called.append(kw))
    admin._admin_device_revoke()
    assert responses[-1][0] == 403
    assert not called and registry.list(username='alice')[0]['enabled'] is True


def test_organization_admin_can_read_and_revoke_only_in_scope_user_devices(
    monkeypatch, responses,
):
    scope = organization_group_path("org-1")
    admin = _Route(
        {"username": "org-admin", "role": "org_admin", "keycloak_groups": [
            organization_admin_group_path("org-1"),
        ]},
        {"alice": [scope], "outside": [organization_group_path("org-2")]},
    )
    monkeypatch.setattr(
        "server.identity.federation_identity_sync.manager_keycloak_admin_adapter",
        lambda: admin.adapter,
    )
    monkeypatch.setattr(device_admin_routes, "current_manager_role", lambda *_: False)
    monkeypatch.setattr(device_admin_routes, "current_administrative_groups", lambda _: tuple(admin.session["keycloak_groups"]))

    admin._admin_device_list()
    assert responses[-1][0] == 200
    assert responses[-1][1]["username"] == "alice"
    assert responses[-1][1]["devices"][0]["device_id"] == "device-1234567890"

    admin.path = "/api/admin/devices?username=outside"
    admin._admin_device_list()
    assert responses[-1][0] == 403

    admin._admin_device_revoke()
    assert responses[-1][0] == 200
    assert admin.revoked == ["device-1234567890"]


def test_level_admin_scope_includes_child_levels_but_not_sibling_or_other_org(
    monkeypatch, responses,
):
    root = level_group_path("org-1", "root")
    child = f"{root}/levels/{component('level', 'child')}"
    admin = _Route(
        {"username": "level-admin", "role": "level_admin", "keycloak_groups": [
            level_admin_group_path("org-1", "root"),
        ]},
        {
            "alice": [child],
            "sibling": [level_group_path("org-1", "sibling")],
            "other-org": [level_group_path("org-2", "root")],
        },
    )
    monkeypatch.setattr(
        "server.identity.federation_identity_sync.manager_keycloak_admin_adapter",
        lambda: admin.adapter,
    )
    monkeypatch.setattr(device_admin_routes, "current_manager_role", lambda *_: False)
    monkeypatch.setattr(device_admin_routes, "current_administrative_groups", lambda _: tuple(admin.session["keycloak_groups"]))

    admin._admin_device_list()
    assert responses[-1][0] == 200

    for username in ("sibling", "other-org"):
        admin.path = f"/api/admin/devices?username={username}"
        admin._admin_device_list()
        assert responses[-1][0] == 403


def test_superadmin_uses_verified_keycloak_role_without_username_scope_lookup(
    monkeypatch, responses,
):
    admin = _Route(
        {"username": "root", "keycloak_roles": ["admin_console:manage"]},
        {},
    )
    monkeypatch.setattr(
        "server.identity.federation_identity_sync.manager_keycloak_admin_adapter",
        lambda: (_ for _ in ()).throw(AssertionError("superadmin needs no group lookup")),
    )
    monkeypatch.setattr(device_admin_routes, "current_manager_role", lambda *_: True)
    monkeypatch.setattr(device_admin_routes, "current_administrative_groups", lambda _: ())
    admin._admin_device_list()
    assert responses[-1][0] == 200
    assert responses[-1][1]["scope"] == "realm"


def test_revoked_admin_group_cannot_list_or_revoke_with_old_token(monkeypatch, responses):
    group = organization_admin_group_path("org-1")
    admin = _Route({"username": "admin", "keycloak_groups": [group]},
                   {"alice": [organization_group_path("org-1")]})
    current = {"groups": (group,)}
    monkeypatch.setattr(device_admin_routes, "current_manager_role", lambda *_: False)
    monkeypatch.setattr(device_admin_routes, "current_administrative_groups", lambda _: current["groups"])
    monkeypatch.setattr("server.identity.federation_identity_sync.manager_keycloak_admin_adapter", lambda: admin.adapter)
    admin._admin_device_list()
    assert responses[-1][0] == 200
    current["groups"] = ()
    admin._admin_device_list()
    assert responses[-1][0] == 403
    admin._admin_device_revoke()
    assert responses[-1][0] == 403 and admin.revoked == []
    current["groups"] = None
    admin._admin_device_list()
    assert responses[-1][0] == 503
