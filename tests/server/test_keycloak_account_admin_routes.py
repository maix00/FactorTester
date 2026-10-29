from server.manager.http import account_admin_routes
from server.identity.realm_groups import organization_group_path


def test_keycloak_account_directory_links_to_keycloak_without_reading_local_store(
    monkeypatch,
):
    replies = []

    class Handler(account_admin_routes.AccountAdministrationRoutesMixin):
        state = object()

        def _require_super_admin_session(self):
            return True

        def _session(self):
            return {"username": "admin"}

    monkeypatch.setenv("TRADERESEARCH_AUTH_MODE", "keycloak")
    monkeypatch.setattr(
        "server.identity.manager_oidc.admin_console_url",
        lambda: "https://id.example/admin/research/console/",
    )
    monkeypatch.setattr(
        account_admin_routes, "json_response",
        lambda _handler, payload, status=200, **_kwargs: replies.append((payload, status)),
    )
    handler = Handler()
    handler._admin_account_directory()

    assert replies == [({
        "success": True,
        "identity_provider": "keycloak",
        "managed_externally": True,
            "admin_scope": "realm",
        "message": "Users, organizations, groups, and role assignments are managed in Keycloak.",
        "admin_console_url": "https://id.example/admin/research/console/",
    }, 200)]


def test_local_user_creation_is_retired_and_points_to_keycloak(monkeypatch):
    replies = []

    class Handler(account_admin_routes.AccountAdministrationRoutesMixin):
        def _require_super_admin_session(self):
            return True

        def _session(self):
            return {"username": "admin"}

    monkeypatch.setenv("TRADERESEARCH_AUTH_MODE", "keycloak")
    monkeypatch.setattr(
        "server.identity.manager_oidc.admin_console_url",
        lambda: "https://id.example/admin/research/console/",
    )
    monkeypatch.setattr(
        account_admin_routes, "json_response",
        lambda _handler, payload, status=200, **_kwargs: replies.append((payload, status)),
    )
    Handler()._admin_create_user()

    assert replies[0][0]["identity_provider"] == "keycloak"
    assert replies[0][0]["managed_externally"] is True
    assert replies[0][0]["code"] == "keycloak_managed_identity"
    assert replies[0][1] == 410


def test_scoped_organization_admin_receives_scoped_keycloak_console_link(monkeypatch):
    replies = []

    class Handler(account_admin_routes.AccountAdministrationRoutesMixin):
        def _identity_sync_admin_context(self):
            return ({"username": "org-admin"}, False, {organization_group_path("GTHT")})

    monkeypatch.setenv("TRADERESEARCH_AUTH_MODE", "keycloak")
    monkeypatch.setattr(
        "server.identity.manager_oidc.admin_console_url",
        lambda: "https://id.example/admin/research/console/",
    )
    monkeypatch.setattr(
        account_admin_routes, "json_response",
        lambda _handler, payload, status=200, **_kwargs: replies.append((payload, status)),
    )

    Handler()._admin_account_directory()

    assert replies[0][1] == 200
    assert replies[0][0]["admin_scope"] == "organization"
    assert replies[0][0]["admin_console_url"] == "https://id.example/admin/research/console/"


def test_keycloak_mode_retires_old_admin_hierarchy_api(monkeypatch):
    from server import admin
    from flask import Flask

    monkeypatch.setenv("TRADERESEARCH_AUTH_MODE", "keycloak")
    app = Flask(__name__)
    app.register_blueprint(admin.admin_bp)
    client = app.test_client()

    response = client.post("/admin/api/users", json={"alias": "intruder"})
    assert response.status_code == 410
    assert response.get_json()["code"] == "keycloak_managed_identity"
