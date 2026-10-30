from server.identity.realm_groups import (
    organization_admin_group_path,
    organization_group_path,
)
from server.manager.http.federation import admin as federation_admin
from server.manager.http.federation.admin import FederationAdminRoutesMixin


class FakeState:
    server_id = "internal-gtht"
    server_role = "feat"
    public_server = False
    managed_organizations = ("GTHT",)

    def __init__(self):
        self.updated = []
        self.federation_registry = type(
            "Registry", (), {"servers": staticmethod(lambda **_kwargs: [])},
        )()

    def federation_config(self, *, public=False):
        return {"bootstrap_url": "http://10.0.0.2:17998/api/federation/register"}

    def federation_config_status(self):
        return {"enabled": True, "active": True}

    def update_federation_config(self, payload):
        self.updated.append(payload)
        return {
            "config": {"bootstrap_url": payload["bootstrap_url"]},
            "status": {"enabled": True, "active": True},
        }


class Handler(FederationAdminRoutesMixin):
    def __init__(self, *, state=None, groups=(), super_admin=False):
        self.state = state or FakeState()
        self._groups = groups
        self._super_admin = super_admin

    def _session(self):
        return {"keycloak_groups": list(self._groups)}

    def _has_secure_ui_transport(self):
        return True

    def _has_super_admin_session(self):
        return self._super_admin

    def _json_body(self, _limit):
        return {"bootstrap_url": "http://10.0.0.3:17998/api/federation/register"}


def _capture_responses(monkeypatch):
    replies = []
    monkeypatch.setattr(
        federation_admin, "json_response",
        lambda _handler, payload, status=200, **_kwargs: replies.append((payload, status)),
    )
    return replies


def test_internal_organization_admin_can_read_and_edit_public_manager_address(
    monkeypatch,
):
    replies = _capture_responses(monkeypatch)
    target_path = organization_group_path("GTHT")

    class FakeKeycloak:
        def group_representations(self):
            return [{"path": target_path, "name": "GTHT"}]

    monkeypatch.setattr(
        federation_admin, "manager_keycloak_admin_adapter", lambda: FakeKeycloak(),
    )
    handler = Handler(groups=[organization_admin_group_path("GTHT")])

    handler._admin_federation_settings()
    assert replies[-1][1] == 200
    assert replies[-1][0]["can_edit_connection"] is True
    assert [row["group_path"] for row in replies[-1][0]["organizations"]] == [target_path]

    handler._update_admin_federation_settings()
    assert replies[-1][1] == 200
    assert handler.state.updated == [{
        "bootstrap_url": "http://10.0.0.3:17998/api/federation/register",
    }]


def test_internal_organization_admin_cannot_edit_another_organizations_manager_address(
    monkeypatch,
):
    replies = _capture_responses(monkeypatch)
    handler = Handler(groups=[organization_admin_group_path("OtherOrg")])

    handler._update_admin_federation_settings()

    assert replies == [({
        "success": False,
        "error": "Keycloak federation administration permission required",
    }, 403)]
    assert handler.state.updated == []


def test_public_manager_hides_and_rejects_upstream_address_even_for_superadmin(
    monkeypatch,
):
    replies = _capture_responses(monkeypatch)
    state = FakeState()
    state.public_server = True
    state.managed_organizations = ()
    handler = Handler(state=state, super_admin=True)

    class FakeKeycloak:
        def group_representations(self):
            return []

    monkeypatch.setattr(
        federation_admin, "manager_keycloak_admin_adapter", lambda: FakeKeycloak(),
    )

    handler._admin_federation_settings()
    assert replies[-1][1] == 200
    assert replies[-1][0]["can_edit_connection"] is False

    handler._update_admin_federation_settings()
    assert replies[-1][1] == 403
    assert handler.state.updated == []
