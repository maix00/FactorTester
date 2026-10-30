import sqlite3

import pytest

from server.identity.keycloak_authorization import keycloak_resource_uri
from server.identity.keycloak_research import (
    KeycloakResearchAuthorization,
    KeycloakResearchGrantManager,
    ResearchRequestIdentity,
    legacy_authorization_snapshot_sha256,
    profile_resource_ref,
    resolve_keycloak_research_member,
    verified_research_request,
)


def _identity(viewer):
    if viewer != "alice":
        return None
    return ResearchRequestIdentity("verified-token", "https://issuer", "subject-a", "alice", "identity-a")


def test_member_lookup_requires_exact_effective_name_and_unique_stable_identity(monkeypatch):
    from server.identity import federation_identity_sync
    row = {"id": "subject-a", "username": "canonical", "enabled": True,
           "attributes": {"tr_identity_id": ["identity-a"], "legacy_username": ["Alice"]}}
    class Directory:
        def user_representation(self, _name):
            return None
        def _page(self, _path, *, max_items):
            return [row]
        def user_by_identity_id(self, _stable):
            return row
    monkeypatch.setattr(federation_identity_sync, "manager_keycloak_admin_adapter", Directory)
    assert resolve_keycloak_research_member("Alice") == {"identity_id": "identity-a", "subject": "subject-a"}
    with pytest.raises(LookupError, match="missing or ambiguous"):
        resolve_keycloak_research_member("Alic")
    class Duplicate(Directory):
        def _page(self, _path, *, max_items):
            return [row, {**row, "id": "other-subject"}]
    monkeypatch.setattr(federation_identity_sync, "manager_keycloak_admin_adapter", Duplicate)
    with pytest.raises(LookupError, match="missing or ambiguous"):
        resolve_keycloak_research_member("Alice")


def test_keycloak_decisions_have_no_owner_or_username_bypass():
    calls = []
    provider = KeycloakResearchAuthorization(identity_provider=_identity,
        authorize_many=lambda token, *, permissions: calls.append((token, permissions)) or {})
    assert not provider.research_access(research_id="r", status="active", viewer="mallory")["can_view"]
    assert calls == []
    assert not provider.research_access(research_id="r", status="active", viewer="alice")["can_manage"]
    assert calls[0][0] == "verified-token"


def test_research_and_report_scopes_preserve_inherited_download():
    research_uri = keycloak_resource_uri("research", "r")
    report_uri = keycloak_resource_uri("research_report", "p")
    def authorize(_token, *, permissions):
        allowed = {(research_uri, "read"), (research_uri, "use"), (report_uri, "read")}
        return {(uri, scope): (uri, scope) in allowed for uri, _name, scope in permissions}
    provider = KeycloakResearchAuthorization(identity_provider=_identity, authorize_many=authorize)
    research = provider.research_access(research_id="r", status="active", viewer="alice")
    assert research["can_view"] and research["can_download"] and not research["can_manage"]
    direct = provider.report_access(report_id="p", viewer="alice")
    assert direct["can_view"] and not direct["can_download"]
    inherited = provider.report_access(report_id="p", viewer="alice", inherited=research)
    assert inherited["can_view"] and inherited["can_download"]
    assert not provider.research_access(research_id="r", status="archived", viewer="alice")["can_view"]


def test_profile_writing_is_per_stable_identity_and_exact_profile():
    ref = profile_resource_ref("r", "identity-a", "work")
    uri = keycloak_resource_uri("research_profile", ref)
    provider = KeycloakResearchAuthorization(identity_provider=_identity,
        authorize_many=lambda _token, *, permissions: {(u, s): u == uri and s == "write" for u, _n, s in permissions})
    assert provider.may_write_profile(research_id="r", viewer="alice", profile_ref="work")
    assert not provider.may_write_profile(research_id="r", viewer="alice", profile_ref="other")
    assert not provider.may_write_profile(research_id="r", viewer="mallory", profile_ref="work")
    assert profile_resource_ref("r", "identity-a", "work") != profile_resource_ref("r", "identity-b", "work")


def test_profile_membership_is_batched_and_cannot_use_another_users_profile():
    calls = []
    first = keycloak_resource_uri("research_profile", profile_resource_ref("r", "identity-a", "one"))
    def authorize(_token, *, permissions):
        calls.append(len(permissions))
        return {(uri, scope): uri == first for uri, _name, scope in permissions}
    provider = KeycloakResearchAuthorization(identity_provider=_identity, authorize_many=authorize)
    profiles = [("r", "one"), ("r", "two"), *(("r", str(i)) for i in range(128))]
    result = provider.profile_membership_access_many(viewer="alice", profiles=profiles)
    assert result[("r", "one")] == {"can_view": True, "can_download": True}
    assert result[("r", "two")] == {"can_view": False, "can_download": False}
    assert calls == [256, 4]
    assert not provider.profile_membership_access_many(viewer="mallory", profiles=[("r", "one")])[("r", "one")]["can_view"]


def test_checks_are_batched_and_authorization_outage_is_not_a_denial():
    calls = []
    def authorize(_token, *, permissions):
        calls.append(len(permissions))
        return {(u, s): True for u, _n, s in permissions}
    provider = KeycloakResearchAuthorization(identity_provider=_identity, authorize_many=authorize)
    assert len(provider.decisions("alice", [("research", str(i), ("read",)) for i in range(600)])) == 600
    assert calls == [256, 256, 88]
    calls.clear()
    listed = provider.research_access_many(viewer="alice", researches=[(str(i), "active") for i in range(100)])
    assert len(listed) == 100 and all(item["can_view"] for item in listed.values())
    assert calls == [256, 44]
    def unavailable(*_args, **_kwargs):
        raise ConnectionError("identity service unavailable")
    provider = KeycloakResearchAuthorization(identity_provider=_identity, authorize_many=unavailable)
    with pytest.raises(ConnectionError):
        provider.research_access(research_id="r", status="active", viewer="alice")


def test_legacy_snapshot_is_stable_and_detects_authorization_changes(tmp_path):
    path = tmp_path / "catalog.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript('''
        CREATE TABLE research_catalog_researches(research_id, owner_ref, status, visibility, authorized_users_json);
        CREATE TABLE research_catalog_reports(report_id, research_id, owner_ref, status, visibility, authorized_users_json);
        CREATE TABLE research_catalog_memberships(research_id, principal_ref, profile_ref, role, status);
        CREATE TABLE research_catalog_share_links(link_id, target_kind, research_id, report_id, owner_ref, token_hash, mode, expires_at, redeemed_by, redeemed_at, revoked_at);
        INSERT INTO research_catalog_researches VALUES ('r', 'a', 'active', 'private', '[]');
        ''')
    before = path.read_bytes()
    first = legacy_authorization_snapshot_sha256(path)
    assert first == legacy_authorization_snapshot_sha256(path)
    assert path.read_bytes() == before
    with sqlite3.connect(path) as db:
        db.execute("UPDATE research_catalog_researches SET authorized_users_json='[\"b\"]'")
    assert legacy_authorization_snapshot_sha256(path) != first


def test_independent_keycloak_grants_can_be_updated_and_revoked():
    from urllib.parse import parse_qs, urlsplit
    from server.identity.keycloak_authorization import keycloak_resource_name

    resource_name = keycloak_resource_name("research", "r")
    resource_uri = keycloak_resource_uri("research", "r")
    policies = {}
    next_id = 0
    def request(_settings, _token, method, path, payload=None):
        nonlocal next_id
        if path.startswith("resource_set?"):
            assert parse_qs(urlsplit(path).query)["name"] == [resource_name]
            return 200, [{"_id": "resource", "name": resource_name, "uris": [resource_uri]}], ""
        if path.startswith("uma-policy?"):
            return 200, list(policies.values()), ""
        if method == "POST" and path == "uma-policy/resource":
            next_id += 1
            policy_id = str(next_id)
            policies[policy_id] = {**payload, "id": policy_id}
            return 201, {}, ""
        policy_id = path.rsplit("/", 1)[1]
        if method == "PUT":
            policies[policy_id] = {**payload, "id": policy_id}
        elif method == "DELETE":
            del policies[policy_id]
        else:
            pytest.fail(f"unexpected call: {method} {path}")
        return 204, {}, ""
    invalidations = []
    manager = KeycloakResearchGrantManager(identity_provider=_identity,
        may_share=lambda token, **_: token == "verified-token",
        settings_provider=lambda: {}, token_provider=lambda _: "protection-token", request=request,
        user_provider=lambda subject: {"id": subject, "username": "bob", "enabled": True,
                                      "attributes": {"tr_identity_id": ["identity-b"]}},
        clear_cache=lambda: invalidations.append(True))
    common = {"actor": "alice", "resource_type": "research", "resource_ref": "r",
              "identity_id": "identity-b", "subject": "subject-b"}
    assert manager.set_user_grant(**common, source="explicit", scopes=["read"])
    assert manager.set_user_grant(**common, source="profile:work", scopes=["read", "use"])
    assert not manager.set_user_grant(**common, source="explicit", scopes=["read"])
    assert manager.set_user_grant(**common, source="explicit", scopes=["read", "use"])
    explicit = next(policy for policy in policies.values() if '"source":"explicit"' in policy["description"])
    explicit["roles"] = ["unrelated-role"]
    from server.identity.keycloak_authorization import AuthorizationUnavailable
    with pytest.raises(AuthorizationUnavailable, match="conflicts"):
        manager.set_user_grant(**common, source="explicit", scopes=[])
    del explicit["roles"]
    assert manager.set_user_grant(**common, source="explicit", scopes=[])
    assert len(policies) == 1
    assert sorted(next(iter(policies.values()))["scopes"]) == ["read", "use"]
    assert len(invalidations) == 10  # six fresh caller checks plus four changes


def test_user_grants_require_verified_share_permission_and_cannot_delegate_admin():
    calls = []
    manager = KeycloakResearchGrantManager(identity_provider=_identity,
        may_share=lambda *_args, **_kwargs: False,
        user_provider=lambda *_: calls.append("lookup"))
    common = {"actor": "alice", "resource_type": "research", "resource_ref": "r", "source": "explicit",
              "identity_id": "identity-b", "subject": "subject-b"}
    with pytest.raises(ValueError, match="cannot delegate"):
        manager.set_user_grant(**common, scopes=["manage"])
    with pytest.raises(PermissionError):
        manager.set_user_grant(**common, scopes=["read"])
    assert calls == []


def test_user_grant_rejects_mismatched_stable_identity_before_writing():
    calls = []
    manager = KeycloakResearchGrantManager(identity_provider=_identity,
        may_share=lambda *_args, **_kwargs: True,
        user_provider=lambda subject: {"id": subject, "username": "bob", "enabled": True,
                                      "attributes": {"tr_identity_id": ["another-identity"]}},
        request=lambda *_args, **_kwargs: calls.append("write"),
        clear_cache=lambda: None)
    with pytest.raises(LookupError):
        manager.set_user_grant(actor="alice", resource_type="research", resource_ref="r", source="explicit",
                               identity_id="identity-b", subject="subject-b", scopes=["read"])
    assert calls == []


def test_profile_resource_does_not_automatically_grant_its_owner_write():
    from server.identity.keycloak_authorization import keycloak_resource_name
    calls = []
    def request(_settings, _token, method, path, payload=None):
        assert method == "GET" and path.startswith("resource_set?")
        return 200, [{"_id": "r-id", "name": keycloak_resource_name("research", "r"),
                      "uris": [keycloak_resource_uri("research", "r")],
                      "attributes": {"traderesearch_owner_subject": ["subject-owner"]}}], ""
    manager = KeycloakResearchGrantManager(identity_provider=_identity,
        may_share=lambda *_args, **_kwargs: True, settings_provider=lambda: {},
        token_provider=lambda _: "pat", request=request,
        ensure_resource=lambda **kwargs: calls.append(kwargs) or "profile-id",
        clear_cache=lambda: None)
    assert manager.ensure_profile_resource(actor="alice", research_id="r", identity_id="identity-b",
                                           profile_ref="work") == "profile-id"
    assert calls == [{"resource_type": "research_profile",
                      "resource_ref": profile_resource_ref("r", "identity-b", "work"),
                      "owner_subject": "subject-owner", "owner_scopes": ("share",)}]


def test_research_identity_uses_only_the_verified_request_context():
    from server.identity.request_context import bind_verified_identity, identity_request
    identity = {"username": "alice", "keycloak_issuer": "https://issuer",
                "keycloak_subject": "subject-a", "tr_identity_id": "identity-a"}
    with identity_request():
        assert verified_research_request("alice") is None
        bind_verified_identity("real-token", identity)
        request = verified_research_request("alice")
        assert request and request.subject == "subject-a" and request.identity_id == "identity-a"
        assert "real-token" not in repr(request)
        assert verified_research_request("mallory") is None
    assert verified_research_request("alice") is None
