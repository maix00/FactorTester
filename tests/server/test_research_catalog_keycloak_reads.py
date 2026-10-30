from types import SimpleNamespace

import pytest

from server.identity.keycloak_authorization import AuthorizationUnavailable, keycloak_resource_uri
from server.identity.keycloak_research import KeycloakResearchAuthorization
from server.manager.services.research_catalog import ResearchCatalog


class NoProfileGrants:
    def profile_membership_access_many(self, *, viewer, profiles):
        return {pair: {"can_view": False, "can_download": False} for pair in profiles}


def _fixture(tmp_path):
    path = tmp_path / "research.sqlite"
    legacy = ResearchCatalog(path)
    public = legacy.create_research(owner_ref="alice", title="Public", visibility="public")
    private = legacy.create_research(owner_ref="alice", title="Private", visibility="private")
    legacy.register_report(public["research_id"], actor="alice", report_id="public-report", visibility="public")
    legacy.register_report(private["research_id"], actor="alice", report_id="private-report")
    legacy.link_evidence(public["research_id"], actor="alice", evidence_owner_ref="alice",
        evidence_ref="evidence:job:sha256:" + "a" * 64, report_id="public-report")
    permissions, calls = set(), []
    def authorize(token, *, permissions, **_kwargs):
        calls.append((token, len(permissions)))
        if ("offline", "offline") in permissions_state:
            raise AuthorizationUnavailable("offline")
        return {(uri, scope): (uri, scope) in permissions_state for uri, _name, scope in permissions}
    permissions_state = permissions
    auth = KeycloakResearchAuthorization(
        identity_provider=lambda viewer: SimpleNamespace(token="verified", subject="subject", identity_id="stable") if viewer else None,
        authorize_many=authorize)
    catalog = ResearchCatalog(path, research_authorizer=auth, profile_authorizer=NoProfileGrants())
    return catalog, public["research_id"], private["research_id"], permissions, calls


def _grant(permissions, kind, ref, *scopes):
    uri = keycloak_resource_uri(kind, ref)
    permissions.update((uri, scope) for scope in scopes)


def test_strict_catalog_never_uses_legacy_public_or_same_name_owner(tmp_path):
    catalog, public, _private, permissions, _calls = _fixture(tmp_path)
    assert catalog.list_researches(viewer="alice") == []
    assert catalog.list_researches(viewer="bob") == []
    assert catalog.list_reports_for_scope(viewer="bob") == []
    with pytest.raises(PermissionError):
        catalog.get_research(public, viewer="alice")
    _grant(permissions, "research", public, "read", "use", "manage")
    result = catalog.list_researches(viewer="bob")
    assert [item["research_id"] for item in result] == [public]
    assert result[0]["authorized_users"] == []
    permissions.clear()
    assert catalog.list_researches(viewer="bob") == []


def test_strict_catalog_batches_research_and_report_scopes_and_propagates_outage(tmp_path):
    catalog, public, _private, permissions, calls = _fixture(tmp_path)
    _grant(permissions, "research", public, "read", "use")
    _grant(permissions, "research_report", "private-report", "read")
    rows = catalog.list_reports_for_scope(viewer="bob")
    assert {row["report_id"] for row in rows} == {"public-report", "private-report"}
    assert next(row for row in rows if row["report_id"] == "private-report")["access"]["can_download"] is False
    assert calls == [("verified", 6), ("verified", 6)]
    permissions.add(("offline", "offline"))
    with pytest.raises(AuthorizationUnavailable):
        catalog.list_researches(viewer="bob")


def test_strict_catalog_does_not_write_legacy_share_grants(tmp_path):
    catalog, public, _private, permissions, _calls = _fixture(tmp_path)
    _grant(permissions, "research", public, "read", "manage")
    with pytest.raises(RuntimeError, match="Keycloak grant migration"):
        catalog.create_share_link(target_kind="research", research_id=public, actor="alice")
    with pytest.raises(RuntimeError, match="Keycloak grant migration"):
        catalog.redeem_share_link("old-token", actor="alice")


def test_strict_catalog_does_not_grant_evidence_by_legacy_owner_name(tmp_path):
    catalog, public, _private, permissions, _calls = _fixture(tmp_path)
    ref = "evidence:job:sha256:" + "a" * 64
    assert catalog.resolve_evidence_access(evidence_ref=ref, viewer="alice")["can_view"] is False
    _grant(permissions, "research", public, "read", "use")
    access = catalog.resolve_evidence_access(evidence_ref=ref, viewer="alice")
    assert access["can_download"] is True and access["can_manage"] is False


def test_strict_catalog_cannot_disable_profile_membership_checks(tmp_path):
    with pytest.raises(ValueError, match="Profile membership"):
        ResearchCatalog(tmp_path / "invalid.sqlite", research_authorizer=object())


def test_explicit_grants_use_verified_keycloak_subject_and_never_write_legacy_acl(tmp_path):
    import sqlite3
    catalog, public, private, _permissions, _calls = _fixture(tmp_path)
    actions = []
    class Manager:
        allowed = True
        def require_resource_share(self, **kwargs):
            actions.append(("check", kwargs))
            if not self.allowed:
                raise PermissionError("denied")
        def set_user_grant(self, **kwargs):
            actions.append(("set", kwargs))
            return True
        def list_user_grants(self, **kwargs):
            actions.append(("list", kwargs))
            return [{"identity_id": "id-bob", "scopes": ["read"]}]
    manager = Manager()
    catalog._profile_grant_manager = manager
    catalog._profile_identity_resolver = lambda username: {"identity_id": "id-bob", "subject": "subject-bob"}
    result = catalog.set_explicit_grant(public, actor="alice", principal_ref="bob", scopes=["use", "read"])
    assert result["identity_id"] == "id-bob" and result["scopes"] == ["read", "use"]
    assert actions[-1][1]["subject"] == "subject-bob" and actions[-1][1]["source"] == "explicit"
    assert catalog.list_explicit_grants(public, actor="alice")[0]["identity_id"] == "id-bob"
    with sqlite3.connect(catalog.db_path) as db:
        assert db.execute("SELECT authorized_users_json FROM research_catalog_researches WHERE research_id=?",
                          (public,)).fetchone()[0] == "[]"
    with pytest.raises(ValueError, match="require read"):
        catalog.set_explicit_grant(public, actor="alice", principal_ref="bob", scopes=["write"])
    with pytest.raises(ValueError, match="does not belong"):
        catalog.set_explicit_grant(private, actor="alice", principal_ref="bob", scopes=["read"],
                                   target_kind="report", report_id="public-report")
    manager.allowed = False
    catalog._profile_identity_resolver = lambda _: pytest.fail("unauthorized identity enumeration")
    with pytest.raises(PermissionError):
        catalog.set_explicit_grant(public, actor="alice", principal_ref="bob", scopes=["read"])


def test_explicit_grants_route_uses_manager_session_and_reports_keycloak_outage(tmp_path, monkeypatch):
    from server.manager.http import research_catalog_routes as routes
    catalog, public, _private, _permissions, _calls = _fixture(tmp_path)
    recorded, responses = [], []
    class Manager:
        def require_resource_share(self, **kwargs):
            recorded.append(("check", kwargs))
        def set_user_grant(self, **kwargs):
            recorded.append(("set", kwargs))
            return True
        def list_user_grants(self, **_kwargs):
            raise AuthorizationUnavailable("identity offline")
    catalog._profile_grant_manager = Manager()
    catalog._profile_identity_resolver = lambda _name: {"identity_id": "stable-bob", "subject": "subject-bob"}
    class Handler(routes.ResearchCatalogRoutesMixin):
        state = SimpleNamespace(research_catalog=catalog)
        def _session(self):
            return {"username": "alice"}
        def _json_body(self, _maximum):
            return {"principal_ref": "bob", "scopes": ["read"]}
    monkeypatch.setattr(routes, "json_response", lambda _self, data, status=200: responses.append((data, status)))
    handler = Handler()
    path = f"/api/research/{public}/grants"
    assert handler._post_research_catalog_routes(SimpleNamespace(path=path, query=""))
    assert responses[-1][1] == 200 and recorded[-1][1]["actor"] == "alice"
    assert handler._get_research_catalog_routes(SimpleNamespace(path=path, query=""))
    assert responses[-1][1] == 503
