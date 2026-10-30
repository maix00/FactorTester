"""Administrative scope must reflect current Keycloak grants, not old claims."""

from server.manager.http import account_admin_routes
from server.manager.http.federation.admin import FederationAdminRoutesMixin
from server.manager.http.account_admin_routes import AccountAdministrationRoutesMixin


def test_manager_admin_scope_and_directory_fail_closed_after_revocation(monkeypatch):
    group = "/traderesearch/admin-scopes/organizations/org-x/organization-admins"
    identity = {"username": "admin", "keycloak_roles": ("admin_console:manage",),
                "keycloak_groups": (group,)}
    current = {"super": True, "groups": (group,)}
    monkeypatch.setattr("server.identity.server_admission.current_manager_role",
                        lambda _session, _role: current["super"])
    monkeypatch.setattr("server.identity.server_admission.current_administrative_groups",
                        lambda _session: current["groups"])
    replies = []
    monkeypatch.setattr(account_admin_routes, "json_response",
                        lambda _handler, payload, status=200, **_kwargs: replies.append((payload, status)))
    seen = []
    monkeypatch.setattr("server.identity.keycloak_directory.users_in_admin_scope",
                        lambda **kwargs: seen.append(kwargs) or
                        {"users": [], "total": 0, "offset": 0, "limit": 100, "has_more": False})

    class Handler(FederationAdminRoutesMixin, AccountAdministrationRoutesMixin):
        path = "/api/admin/users"

        def _session(self):
            return identity

        def _has_secure_ui_transport(self):
            return True

    handler = Handler()
    handler._admin_identity_users(None)
    assert replies[-1][1] == 200
    assert "admin_console:manage" in seen[-1]["roles"]

    # The still-present token claim must not override a revoked realm role.
    current["super"] = False
    handler._admin_identity_users(None)
    assert replies[-1][1] == 200
    assert "admin_console:manage" not in seen[-1]["roles"]
    assert seen[-1]["groups"] == (group,)

    current["groups"] = ()
    handler._admin_identity_users(None)
    assert replies[-1][1] == 403
    assert len(seen) == 2

    # An unavailable Keycloak provider also fails closed.
    current["groups"] = None
    handler._admin_identity_users(None)
    assert replies[-1][1] == 403
    assert len(seen) == 2
