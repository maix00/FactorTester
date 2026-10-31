from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from server.identity.keycloak_authorization import AuthorizationUnavailable
from server.identity.request_context import identity_request
from server.manager.http import page_assistance_routes as routes


def _snapshot(ref, revision, tab="tab"):
    return {"client_revision": revision, "active_tab_id": tab, "tabs": [{
        "tab_id": tab, "research_id": ref, "assistance": {"schema_version": 1,
            "page_kind": "research", "revision": 0,
            "navigation": {"schema_version": 1, "root_id": "root",
                           "nodes": {"root": {"id": "root", "kind": "page", "children": []}}},
            "document": {"research_id": ref}, "document_schema": {"type": "object"}}}]}


def test_workspace_leases_are_isolated_and_stale_operations_cannot_resurrect_tabs():
    store = routes.PageAssistanceStore()
    one, two = store.issue_workspace("owner", "self"), store.issue_workspace("owner", "self")
    assert one != two
    scope1, scope2 = (store.workspace_scope("owner", "self", value) for value in (one, two))
    store.publish_workspace("owner", scope1, _snapshot("r1", 1))
    store.publish_workspace("owner", scope2, _snapshot("r2", 1))
    old = store.workspace("owner", scope1)["_store_revision"]
    store.remove_page("owner", scope1, "tab", client_revision=2)
    with pytest.raises(routes.WorkspaceRevisionConflict):
        store.publish_workspace("owner", scope1, _snapshot("r1", 1))
    assert store.page("owner", scope1, "tab") is None
    assert store.page("owner", scope2, "tab")["assistance"]["document"]["research_id"] == "r2"
    assert not store.restrict_workspace("owner", scope1, expected_revision=old, allowed_tab_ids=set())
    with pytest.raises(PermissionError):
        store.workspace_scope("other-owner", "self", one)
    store.release_workspace("owner", "self", one)
    with pytest.raises(routes.WorkspaceLeaseExpired):
        store.publish_workspace("owner", scope1, _snapshot("r1", 3))
    assert store.page("owner", scope2, "tab") is not None


def test_self_workspace_rechecks_research_and_removes_only_its_own_tab(monkeypatch):
    from server.identity import keycloak_research
    store, responses = routes.PageAssistanceStore(), []
    allowed = {"r1", "r2"}
    offline = {"value": False}
    monkeypatch.setattr(routes, "_STORE", store)
    monkeypatch.setattr(routes, "json_response", lambda _self, data, status=200: responses.append((data, status)))
    monkeypatch.setattr(keycloak_research, "verified_research_request", lambda principal: object())
    class Auth:
        def research_access_many(self, *, viewer, researches):
            if offline["value"]:
                raise AuthorizationUnavailable("offline")
            return {ref: {"can_view": ref in allowed} for ref, _status in researches}
    monkeypatch.setattr(keycloak_research, "KeycloakResearchAuthorization", Auth)
    class Catalog:
        _profile_authorizer = None
        def research_statuses(self, refs):
            return {ref: "active" for ref in refs}
    class Handler(routes.PageAssistanceRoutesMixin):
        body = {}
        def _agent_app_profile(self, profile):
            return "owner", profile
        def _assistance_profile(self, profile, workspace_id):
            return "owner", profile, workspace_id
        def _json_body(self, _limit):
            return self.body
        def _research_catalog_service(self):
            return Catalog()
        def _agent_app_error(self, exc):
            raise exc
    handler = Handler()
    handler.body = {"profile_id": "self"}
    for _ in range(2):
        assert handler._post_page_assistance_routes(SimpleNamespace(path="/api/client/profile-agent/assistance/workspaces"))
    first, second = (item[0]["workspace_id"] for item in responses[-2:])
    for workspace_id, ref in ((first, "r1"), (second, "r2")):
        handler.body = {"profile_id": "self", "workspace_id": workspace_id, "tab_id": "tab",
                        "workspace": _snapshot(ref, 1)}
        handler._post_page_assistance_routes(SimpleNamespace(path="/api/client/profile-agent/assistance/publish"))
        assert responses[-1][1] == 200 and responses[-1][0]["page"] is not None
    allowed.remove("r1")
    handler._get_page_assistance_routes(SimpleNamespace(path="/api/client/profile-agent/assistance",
        query=urlencode({"profile_id": "self", "workspace_id": first})))
    assert responses[-1][0]["page"] is None
    assert store.page("owner", store.workspace_scope("owner", "self", second), "tab") is not None
    offline["value"] = True
    handler._get_page_assistance_routes(SimpleNamespace(path="/api/client/profile-agent/assistance",
        query=urlencode({"profile_id": "self", "workspace_id": second})))
    assert responses[-1][1] == 503


def test_research_context_checks_nested_references_without_misreading_json_schema(monkeypatch):
    from server.identity import keycloak_research

    monkeypatch.setattr(keycloak_research, "verified_research_request", lambda _principal: object())

    class Auth:
        def research_access_many(self, *, viewer, researches):
            return {ref: {"can_view": ref == "r1"} for ref, _status in researches}

    class Catalog:
        _profile_authorizer = None
        def research_statuses(self, refs):
            return {ref: "active" for ref in refs}

    class Handler(routes.PageAssistanceRoutesMixin):
        def _research_catalog_service(self):
            return Catalog()

    monkeypatch.setattr(keycloak_research, "KeycloakResearchAuthorization", Auth)
    handler = Handler()
    snapshot = _snapshot("r1", 1)
    assistance = snapshot["tabs"][0]["assistance"]
    assistance["document_schema"] = {"type": "object", "properties": {
        "research_id": {"type": "string"},
    }}
    assert len(handler._assistance_visible_workspace("owner", "self", snapshot)["tabs"]) == 1

    assistance["document"]["nested"] = {"research_id": "r2"}
    assert not handler._assistance_visible_workspace("owner", "self", snapshot)["tabs"]
    assistance["document"]["nested"]["research_id"] = 42
    with pytest.raises(ValueError, match="Research reference is invalid"):
        handler._assistance_visible_workspace("owner", "self", snapshot)

    missing = _snapshot("", 2)
    with pytest.raises(ValueError, match="Research page requires"):
        handler._assistance_visible_workspace("owner", "self", missing)


def test_agent_capability_requires_live_user_and_uses_active_turn_workspace(monkeypatch):
    from server.identity import server_admission, user_session
    from server.identity.keycloak_authorization import keycloak_request_identity
    from server.permissions import agent_assistant
    token = "delegated-user-token"
    user = {"username": "owner", "keycloak_subject": "subject", "keycloak_issuer": "issuer",
            "tr_identity_id": "stable"}
    binding = {"workspace_id": "a" * 32, "token": token, "subject": "subject", "issuer": "issuer",
               "identity_id": "stable"}
    monkeypatch.setattr(user_session, "keycloak_session", lambda value, **kwargs: user if
                        value == token and kwargs == {"use_cache": False, "fail_on_unavailable": True} else None)
    monkeypatch.setattr(server_admission, "server_admission", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(agent_assistant, "can_use_agent_assistant", lambda session, *, public_server: session == user)
    class Handler(routes.PageAssistanceRoutesMixin):
        state = object()
        headers = {"X-FactorTester-Agent-Profile": "self"}
        def _session(self):
            return {"username": "owner", "authentication": "agent"}
        def _agent_principal(self, session):
            return session["username"]
        def _is_local_agent_request(self):
            return True
        def _agent_app_server(self):
            return SimpleNamespace(assistance_turn_binding=lambda *_: binding)
        def _profile_exists(self, *_):
            return True
        def _agent_service(self):
            return SimpleNamespace(require_local_server_runtime=lambda *_: None)
    handler = Handler()
    with identity_request():
        assert handler._assistance_profile("self", "") == ("owner", "self", "a" * 32)
        assert keycloak_request_identity().token == token
        with pytest.raises(PermissionError, match="another workspace"):
            handler._assistance_profile("self", "b" * 32)
    user["tr_identity_id"] = "replacement-user"
    with identity_request(), pytest.raises(PermissionError, match="no longer authorized"):
        handler._assistance_profile("self", "")


def test_rpc_binds_only_an_issued_workspace_to_the_verified_user(monkeypatch):
    from server.identity import keycloak_research
    from server.manager.http import agent_app_routes
    store, captured, responses = routes.PageAssistanceStore(), [], []
    workspace = store.issue_workspace("owner", "self")
    monkeypatch.setattr(routes, "_STORE", store)
    monkeypatch.setattr(agent_app_routes, "json_response", lambda _self, data, status=200: responses.append((data, status)))
    monkeypatch.setattr(keycloak_research, "verified_research_request", lambda _: SimpleNamespace(
        token="private-token", issuer="issuer", subject="subject", identity_id="stable"))
    class Handler(agent_app_routes.AgentAppServerRoutesMixin):
        body = {"profile_id": "self", "workspace_id": workspace, "method": "turn/start",
                "conversation_id": "conversation", "params": {"input": [{"type": "text", "text": "hello"}]}}
        def _json_body(self, _limit): return self.body
        def _agent_app_profile(self, _profile): return "owner", "self"
        def _agent_app_server(self):
            return SimpleNamespace(request=lambda *args, **kwargs: captured.append((args, kwargs)) or {})
    handler = Handler()
    assert handler._post_agent_app_routes(SimpleNamespace(path="/api/client/profile-agent/rpc"))
    assert responses[-1][1] == 200
    assert captured[-1][1]["assistance_context"]["workspace_id"] == workspace
    assert "private-token" not in str(captured[-1][0][3])
    handler.body = {**handler.body, "workspace_id": "x" * 32}
    handler._post_agent_app_routes(SimpleNamespace(path="/api/client/profile-agent/rpc"))
    assert responses[-1][1] == 403 and responses[-1][0]["code"] == "assistance_workspace_expired"
    assert len(captured) == 1
