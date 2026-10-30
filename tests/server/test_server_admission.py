from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import unquote

import pytest

from server.identity import server_admission as admission
from server.identity.realm_groups import organization_group_path


ISSUER = "https://identity.example/realms/traderesearch"
ORG = "org-a"
SERVER = "internal-server-a"


class Keycloak:
    def __init__(self):
        self.group_attrs = {
            organization_group_path(ORG): {"tr_internal_manager_id": [SERVER]},
            admission.manager_binding_group_path(SERVER): {
                "tr_internal_manager_id": [SERVER], "tr_organization_id": [ORG],
            },
        }
        self.user = {"id": "subject", "enabled": True,
                     "attributes": {"tr_organization_id": [ORG]}}
        self.groups = {organization_group_path(ORG) + "/levels/a"}
        self.roles = [{"name": "public_server:login"}]
        self.calls = []
        self.unavailable = False

    def _get(self, path):
        self.calls.append(path)
        if self.unavailable:
            raise ConnectionError("offline")
        if path.startswith("group-by-path/"):
            group_path = "/" + unquote(path.removeprefix("group-by-path/"))
            attrs = self.group_attrs.get(group_path)
            return None if attrs is None else {"id": "group", "path": group_path, "attributes": attrs}
        if path.startswith("clients?"):
            return [{"id": "client-uuid", "clientId": "tr-manager", "enabled": True}]
        if path.endswith("/composite"):
            return self.roles
        if path == "users/subject":
            return self.user
        raise AssertionError(path)

    def user_group_paths(self, subject):
        self.calls.append("user_groups")
        assert subject == "subject"
        if self.unavailable:
            raise ConnectionError("offline")
        return self.groups


@pytest.fixture
def auth(monkeypatch):
    provider = Keycloak()
    admission.clear_server_admission_cache()
    monkeypatch.setattr(admission, "oidc_settings", lambda: {
        "issuer": ISSUER, "roles_client_id": "tr-manager", "client_id": "tr-manager",
    })
    monkeypatch.setattr("server.identity.federation_identity_sync.manager_keycloak_admin_adapter",
                        lambda: provider)
    session = {"username": "alice", "keycloak_subject": "subject", "keycloak_issuer": ISSUER,
               "organization_id": ORG, "keycloak_groups": [organization_group_path(ORG) + "/levels/a"],
               "keycloak_roles": ["public_server:login"]}
    internal = SimpleNamespace(public_server=False, server_id=SERVER, managed_organizations=(ORG,))
    public = SimpleNamespace(public_server=True, server_id="public", managed_organizations=())
    yield provider, session, internal, public
    admission.clear_server_admission_cache()


def test_internal_admission_requires_reciprocal_binding_and_current_membership(auth):
    provider, session, internal, _ = auth
    assert admission.server_admission(session, state=internal) == (True, "")
    first = len(provider.calls)
    assert admission.server_admission(session, state=internal) == (True, "")
    assert len(provider.calls) == first  # independent requests share bounded projections
    provider.groups.clear()
    admission.clear_server_admission_cache()
    assert admission.server_admission(session, state=internal) == (False, "organization_login_denied")


@pytest.mark.parametrize("change", [
    lambda p: p.group_attrs[organization_group_path(ORG)].update(tr_internal_manager_id=["other"]),
    lambda p: p.group_attrs[organization_group_path(ORG)].update(tr_internal_manager_id=[SERVER, "other"]),
    lambda p: p.group_attrs[admission.manager_binding_group_path(SERVER)].update(tr_organization_id=["other"]),
    lambda p: p.group_attrs[admission.manager_binding_group_path(SERVER)].update(tr_internal_manager_id=["other"]),
])
def test_inconsistent_keycloak_binding_fails_closed_even_for_super_admin(auth, change):
    provider, session, internal, _ = auth
    session["keycloak_roles"].append("admin_console:manage")
    change(provider)
    assert admission.server_admission(session, state=internal) == (False, "server_organization_conflict")


def test_one_server_has_exactly_one_configured_organization(auth):
    _, session, internal, _ = auth
    for organizations in ((), (ORG, "other")):
        internal.managed_organizations = organizations
        assert admission.server_admission(session, state=internal) == (False, "server_organization_unconfigured")


def test_super_admin_must_belong_to_internal_organization(auth):
    _, session, internal, _ = auth
    session["keycloak_roles"].append("admin_console:manage")
    session["organization_id"] = "other"
    assert admission.server_admission(session, state=internal) == (False, "organization_login_denied")


def test_mixed_or_stale_organization_groups_fail_closed(auth):
    provider, session, internal, _ = auth
    session["keycloak_groups"].append(organization_group_path("other") + "/levels/b")
    assert admission.server_admission(session, state=internal) == (False, "organization_login_denied")
    session["keycloak_groups"].pop()
    provider.groups.add(organization_group_path("other") + "/levels/b")
    assert admission.server_admission(session, state=internal) == (False, "organization_login_denied")


def test_public_requires_both_token_role_and_current_keycloak_role(auth):
    provider, session, _, public = auth
    assert admission.server_admission(session, state=public) == (True, "")
    provider.roles = []
    # The explicit bound is five seconds; invalidation simulates expiry.
    admission.clear_server_admission_cache()
    assert admission.server_admission(session, state=public) == (False, "public_login_denied")
    provider.roles = [{"name": "public_server:login"}]
    session["keycloak_roles"] = ["admin_console:manage"]
    admission.clear_server_admission_cache()
    assert admission.server_admission(session, state=public) == (False, "public_login_denied")


def test_unavailable_keycloak_fails_closed_after_cache_expiry(auth):
    provider, session, internal, _ = auth
    assert admission.server_admission(session, state=internal)[0]
    provider.unavailable = True
    admission.clear_server_admission_cache()
    assert admission.server_admission(session, state=internal) == (False, "server_authorization_unavailable")


def test_both_session_entry_points_use_the_same_policy(auth, monkeypatch):
    from server.manager.state.sessions import SessionStateMixin
    import server.identity.user_session as session_module
    from server.services import session_runtime
    from flask import Flask

    _, session, internal, _ = auth
    state = SessionStateMixin()
    state.public_server, state.server_id, state.managed_organizations = (
        internal.public_server, internal.server_id, internal.managed_organizations,
    )
    monkeypatch.setattr(session_module, "keycloak_session", lambda _: session)
    monkeypatch.setenv("FACTORTESTER_PUBLIC_SERVER", "0")
    monkeypatch.setenv("FACTORTESTER_SERVER_ID", SERVER)
    monkeypatch.setenv("FACTORTESTER_MANAGED_ORGANIZATIONS", ORG)
    app = Flask(__name__)
    app.secret_key = "fixture"
    with app.test_request_context("/", headers={"Authorization": "Bearer token"}):
        assert state.session("token")["username"] == "alice"
        assert session_runtime.current_user() == "alice"
    session["organization_id"] = "other"
    with app.test_request_context("/", headers={"Authorization": "Bearer token"}):
        assert state.session("token") is None
        assert session_runtime.current_user() is None


def test_gateway_capability_is_verified_for_each_request(monkeypatch):
    from flask import Flask
    from server.services.manager_gateway_auth import install_manager_gateway_auth
    from server.services.session_runtime import current_user
    monkeypatch.setenv("TRADERESEARCH_AUTH_MODE", "keycloak")
    monkeypatch.setenv("GTHT_MANAGER_CAPABILITY_TOKEN", "gateway-fixture")
    app = Flask(__name__)
    app.secret_key = "fixture"
    install_manager_gateway_auth(app)

    @app.get("/who")
    def who():
        return {"user": current_user()}

    client = app.test_client()
    assert client.get("/who", headers={"X-FactorTester-Principal": "alice",
                                      "X-FactorTester-Manager": "gateway-fixture"}).json["user"] == "alice"
    # The preceding response can set a Flask cookie; it is not authority.
    assert client.get("/who").json["user"] is None
