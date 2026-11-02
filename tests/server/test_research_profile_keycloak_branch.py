from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from server.identity.keycloak_authorization import AuthorizationUnavailable, keycloak_resource_uri
from server.identity.keycloak_research import KeycloakResearchAuthorization, ResearchRequestIdentity, profile_resource_ref
from server.identity.request_context import bind_verified_identity, identity_request
from scripts.test.historical_research_catalog import HistoricalResearchCatalog as ResearchCatalog


def test_branch_profile_uses_verified_keycloak_decision_and_rechecks_each_write(tmp_path):
    path = tmp_path / "research.sqlite"
    legacy = ResearchCatalog(path)
    research_id = legacy.create_research(owner_ref="alice", title="Research")["research_id"]
    legacy.register_report(research_id, actor="alice", report_id="report", profile_ref="self")
    legacy.add_membership(research_id, actor="alice", principal_ref="bob", profile_ref="self", role="editor")
    legacy.create_workspace(research_id, actor="alice", principal_ref="bob", profile_ref="self")
    uri = keycloak_resource_uri("research_profile", profile_resource_ref(research_id, "bob-id", "self"))
    allowed = {("bob-token", uri, "write")}

    def authorize(token, *, permissions):
        # Network authorization must happen before the SQLite write lock.
        with sqlite3.connect(path, timeout=0.1) as db:
            db.execute("BEGIN IMMEDIATE")
            db.rollback()
        return {(resource, scope): (token, resource, scope) in allowed
                for resource, _name, scope in permissions}

    auth = KeycloakResearchAuthorization(authorize_many=authorize)
    catalog = ResearchCatalog(path, profile_authorizer=auth)
    bob = {"username": "bob", "keycloak_subject": "bob-subject", "tr_identity_id": "bob-id",
           "keycloak_issuer": "https://identity.example/realms/trade"}

    # Local role data is only a migration artifact after the Profile switch.
    with sqlite3.connect(path) as db:
        db.execute("UPDATE research_catalog_memberships SET role='viewer' WHERE principal_ref='bob'")
    with pytest.raises(PermissionError, match="exact Profile"):
        catalog.reserve_report_branch("report", actor="bob", profile_ref="self", branch_id="review")
    with identity_request():
        bind_verified_identity("bob-token", bob)
        value = catalog.reserve_report_branch("report", actor="bob", profile_ref="self", branch_id="review")
        assert value["principal_ref"] == "bob"
        # Keycloak revocation takes effect on the next decision even though
        # the local membership/workspace still exist.
        allowed.clear()
        with pytest.raises(PermissionError, match="exact Profile"):
            catalog.publish_report_branch("report", "review", actor="bob", profile_ref="self",
                expected_generation=0, expected_revision="", generation=1, revision="a" * 64,
                publication_id="p" * 24, storage_server_id="server")


def test_branch_profile_authorization_outage_is_not_converted_to_grant_or_denial(tmp_path):
    path = tmp_path / "research.sqlite"
    catalog = ResearchCatalog(path)
    research_id = catalog.create_research(owner_ref="alice", title="Research")["research_id"]
    catalog.register_report(research_id, actor="alice", report_id="report", profile_ref="self")
    class Unavailable:
        def may_write_profile(self, **_kwargs):
            raise AuthorizationUnavailable("Keycloak unavailable")
    catalog = ResearchCatalog(path, profile_authorizer=Unavailable())
    with pytest.raises(AuthorizationUnavailable):
        catalog.reserve_report_branch("report", actor="alice", profile_ref="self", branch_id="main")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM research_catalog_branches").fetchone()[0] == 0


def test_membership_read_and_authoring_follow_keycloak_not_local_role_or_status(tmp_path):
    path = tmp_path / "research.sqlite"
    legacy = ResearchCatalog(path)
    research_id = legacy.create_research(owner_ref="alice", title="Research")["research_id"]
    legacy.register_report(research_id, actor="alice", report_id="report", profile_ref="self")
    legacy.add_membership(research_id, actor="alice", principal_ref="bob", profile_ref="work", role="editor")
    uri = keycloak_resource_uri("research_profile", profile_resource_ref(research_id, "bob-id", "work"))
    permissions = {(uri, scope) for scope in ("read", "use", "write")}
    requests = []
    def authorize(_token, *, permissions: list):
        requests.append(permissions)
        return {(resource, scope): (resource, scope) in allowed for resource, _name, scope in permissions}
    allowed = set(permissions)
    auth = KeycloakResearchAuthorization(authorize_many=authorize)
    catalog = ResearchCatalog(path, profile_authorizer=auth)
    bob = {"username": "bob", "keycloak_subject": "bob-subject", "tr_identity_id": "bob-id",
           "keycloak_issuer": "https://identity.example/realms/trade"}
    record = {"report_id": "report", "owner_ref": "alice"}
    with identity_request():
        bind_verified_identity("bob-token", bob)
        assert [item["research_id"] for item in catalog.list_researches(viewer="bob")] == [research_id]
        assert len(requests) == 1  # batched by request, not one call per Research
        assert catalog.get_research_summary(research_id, viewer="bob")["access"]["can_download"]
        assert catalog.can_read_authoring_publication(record, "bob")
        allowed.clear()
        assert catalog.list_researches(viewer="bob") == []
        assert not catalog.can_read_authoring_publication(record, "bob")
        # Even a locally revoked association cannot grant access. Keycloak
        # decides independently if a subsequent policy change grants it.
        with sqlite3.connect(path) as db:
            db.execute("UPDATE research_catalog_memberships SET status='revoked', role='viewer' WHERE principal_ref='bob'")
        allowed.update(permissions)
        assert len(catalog.list_researches(viewer="bob")) == 1
        assert catalog.can_read_authoring_publication(record, "bob")
        workspace = catalog.create_workspace(research_id, actor="bob", principal_ref="bob", profile_ref="work")
        assert workspace["principal_ref"] == "bob"
        allowed.remove((uri, "write"))
        with pytest.raises(PermissionError, match="workspace"):
            catalog.create_workspace(research_id, actor="bob", principal_ref="bob", profile_ref="work")


def _configured_member_catalog(tmp_path):
    path = tmp_path / "research.sqlite"
    legacy = ResearchCatalog(path)
    research_id = legacy.create_research(owner_ref="alice", title="Research")["research_id"]
    legacy.register_report(research_id, actor="alice", report_id="report", profile_ref="self")
    legacy.add_membership(research_id, actor="alice", principal_ref="bob", profile_ref="work", role="editor")
    legacy.create_workspace(research_id, actor="alice", principal_ref="bob", profile_ref="work")
    uri = keycloak_resource_uri("research_profile", profile_resource_ref(research_id, "bob-id", "work"))
    allowed = {(uri, scope) for scope in ("read", "use", "write")}
    auth = KeycloakResearchAuthorization(authorize_many=lambda _t, *, permissions: {
        (resource, scope): (resource, scope) in allowed for resource, _name, scope in permissions
    })
    class Grants:
        fail_after_update = False
        manager_allowed = True
        def require_membership_manager(self, *, actor, research_id):
            if actor != "alice" or not self.manager_allowed:
                raise PermissionError("Keycloak sharing denied")
        def set_profile_membership(self, *, role, status, **_kwargs):
            allowed.clear()
            if status == "active":
                allowed.update((uri, scope) for scope in ("read", "use"))
                if role != "viewer":
                    allowed.add((uri, "write"))
            if self.fail_after_update:
                raise AuthorizationUnavailable("response lost after policy update")
    grants = Grants()
    catalog = ResearchCatalog(path, profile_authorizer=auth, profile_grant_manager=grants,
        profile_identity_resolver=lambda username: {"identity_id": "bob-id", "subject": "bob-subject"}
        if username == "bob" else None)
    return catalog, research_id, uri, allowed, grants


def test_denied_manager_cannot_create_a_pending_record(tmp_path):
    catalog, research_id, _uri, _allowed, grants = _configured_member_catalog(tmp_path)
    grants.manager_allowed = False
    with pytest.raises(PermissionError, match="sharing denied"):
        catalog.remove_membership(research_id, actor="alice", profile_ref="work", principal_ref="bob")
    with sqlite3.connect(catalog.db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM research_profile_policy_pending").fetchone()[0] == 0


def test_member_policy_failure_stays_denied_and_same_request_recovers_idempotently(tmp_path):
    catalog, research_id, _uri, _allowed, grants = _configured_member_catalog(tmp_path)
    bob = {"username": "bob", "keycloak_subject": "bob-subject", "tr_identity_id": "bob-id",
           "keycloak_issuer": "https://identity.example/realms/trade"}
    grants.fail_after_update = True
    with pytest.raises(AuthorizationUnavailable):
        catalog.remove_membership(research_id, actor="alice", profile_ref="work", principal_ref="bob")
    with identity_request():
        bind_verified_identity("bob-token", bob)
        assert catalog.list_researches(viewer="bob") == []
        with pytest.raises(PermissionError, match="pending"):
            catalog.reserve_report_branch("report", actor="bob", profile_ref="work", branch_id="blocked")
    with pytest.raises(RuntimeError, match="another Profile"):
        catalog.add_membership(research_id, actor="alice", principal_ref="bob", profile_ref="work", role="viewer")
    grants.fail_after_update = False
    assert catalog.remove_membership(research_id, actor="alice", profile_ref="work", principal_ref="bob")["status"] == "revoked"
    assert catalog.remove_membership(research_id, actor="alice", profile_ref="work", principal_ref="bob")["status"] == "revoked"
    with sqlite3.connect(catalog.db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM research_profile_policy_pending").fetchone()[0] == 0
        assert db.execute("SELECT status FROM research_catalog_workspaces WHERE principal_ref='bob'").fetchone()[0] == "archived"


def test_member_changes_serialize_without_holding_sqlite_during_network_io(tmp_path):
    catalog, research_id, _uri, allowed, grants = _configured_member_catalog(tmp_path)
    entered, release, calls = threading.Event(), threading.Event(), []
    original = grants.set_profile_membership
    def delayed(*, role, status, **kwargs):
        calls.append(role)
        with sqlite3.connect(catalog.db_path, timeout=0.1) as db:
            db.execute("BEGIN IMMEDIATE")
            db.rollback()
        if role == "contributor":
            entered.set()
            assert release.wait(timeout=5)
        return original(role=role, status=status, **kwargs)
    grants.set_profile_membership = delayed
    def change(role):
        return catalog.add_membership(research_id, actor="alice", principal_ref="bob", profile_ref="work", role=role)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(change, "contributor")
        assert entered.wait(timeout=5)
        second = pool.submit(change, "viewer")
        assert calls == ["contributor"]
        release.set()
        assert first.result(timeout=5)["role"] == "contributor"
        assert second.result(timeout=5)["role"] == "viewer"
    assert calls == ["contributor", "viewer"]
    assert {scope for _uri, scope in allowed} == {"read", "use"}
    with sqlite3.connect(catalog.db_path) as db:
        assert db.execute("SELECT role FROM research_catalog_memberships WHERE principal_ref='bob'").fetchone()[0] == "viewer"
        assert db.execute("SELECT COUNT(*) FROM research_profile_policy_pending").fetchone()[0] == 0


def test_branch_rejects_keycloak_decision_if_membership_changed_before_sqlite_write(tmp_path):
    catalog, research_id, _uri, _allowed, _grants = _configured_member_catalog(tmp_path)
    class ChangedDuringAuthorization:
        def may_write_profile(self, **_kwargs):
            with sqlite3.connect(catalog.db_path) as db:
                db.execute("""INSERT INTO research_profile_policy_versions VALUES (?, 'bob', 'work', 1)
                    ON CONFLICT(research_id,principal_ref,profile_ref) DO UPDATE SET revision=revision+1""", (research_id,))
            return True
    catalog._profile_authorizer = ChangedDuringAuthorization()
    with pytest.raises(PermissionError, match="changed; retry"):
        catalog.reserve_report_branch("report", actor="bob", profile_ref="work", branch_id="stale")


def test_list_rejects_a_membership_decision_if_policy_changes_during_keycloak_request(tmp_path):
    catalog, research_id, _uri, _allowed, _grants = _configured_member_catalog(tmp_path)
    class ChangedDuringAuthorization:
        def profile_membership_access_many(self, *, profiles, **_kwargs):
            with sqlite3.connect(catalog.db_path) as db:
                db.execute("""INSERT INTO research_profile_policy_versions VALUES (?, 'bob', 'work', 1)
                    ON CONFLICT(research_id,principal_ref,profile_ref) DO UPDATE SET revision=revision+1""", (research_id,))
            return {pair: {"can_view": True, "can_download": True} for pair in profiles}
    catalog._profile_authorizer = ChangedDuringAuthorization()
    assert catalog.list_researches(viewer="bob") == []


def test_report_registration_checks_owners_exact_keycloak_profile(tmp_path):
    path = tmp_path / "research.sqlite"
    legacy = ResearchCatalog(path)
    research_id = legacy.create_research(owner_ref="alice", title="Research")["research_id"]
    uri = keycloak_resource_uri("research_profile", profile_resource_ref(research_id, "alice-id", "self"))
    allowed = {(uri, "write")}
    auth = KeycloakResearchAuthorization(authorize_many=lambda _t, *, permissions: {
        (resource, scope): (resource, scope) in allowed for resource, _name, scope in permissions
    })
    class Grants:
        def report_registration_identity(self, **_kwargs):
            return ResearchRequestIdentity("token", "issuer", "alice-subject", "alice", "alice-id")
        def ensure_new_report_resource(self, **_kwargs):
            pass
        def require_report_resource(self, **_kwargs):
            pass
    catalog = ResearchCatalog(path, profile_authorizer=auth, profile_grant_manager=Grants())
    alice = {"username": "alice", "keycloak_subject": "alice-subject", "tr_identity_id": "alice-id",
             "keycloak_issuer": "https://identity.example/realms/trade"}
    with identity_request():
        bind_verified_identity("alice-token", alice)
        assert catalog.register_report(research_id, actor="alice", report_id="a", profile_ref="self")["report_id"] == "a"
        allowed.clear()
        with pytest.raises(PermissionError, match="Profile write"):
            catalog.register_report(research_id, actor="alice", report_id="b", profile_ref="self")


def test_report_registration_recovers_remote_failure_without_adopting_or_deleting(tmp_path):
    path = tmp_path / "research.sqlite"
    old = ResearchCatalog(path)
    research_id = old.create_research(owner_ref="alice", title="Research")["research_id"]
    other_id = old.create_research(owner_ref="alice", title="Other")["research_id"]
    class Authorization:
        def profile_membership_access_many(self, **_kwargs):
            return {}
        def may_write_profile(self, **_kwargs):
            return True
    class Grants:
        def __init__(self):
            self.resource = None
            self.fail = True
            self.checked = []
        def report_registration_identity(self, **_kwargs):
            return ResearchRequestIdentity("token", "issuer", "alice-subject", "alice", "alice-id")
        def ensure_new_report_resource(self, *, report_id, creation_intent, **_kwargs):
            if self.resource is None:
                self.resource = (report_id, creation_intent)
            elif self.resource != (report_id, creation_intent):
                raise AuthorizationUnavailable("foreign creation intent")
            if self.fail:
                self.fail = False
                raise AuthorizationUnavailable("response lost after creation")
        def require_report_resource(self, *, report_id, **_kwargs):
            self.checked.append(report_id)
            if self.resource is None or self.resource[0] != report_id:
                raise AuthorizationUnavailable("Keycloak report is missing")
    grants = Grants()
    catalog = ResearchCatalog(path, profile_authorizer=Authorization(), profile_grant_manager=grants)
    def register(research=research_id, **kwargs):
        return catalog.register_report(research, actor="alice", report_id="report", profile_ref="self", **kwargs)
    with pytest.raises(AuthorizationUnavailable, match="response lost"):
        register()
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM research_catalog_reports WHERE report_id='report'").fetchone()[0] == 0
        pending = db.execute("SELECT research_id,creation_intent FROM research_report_policy_pending").fetchone()
    assert pending == (research_id, grants.resource[1])
    with pytest.raises(RuntimeError, match="another report registration"):
        register(other_id)
    assert register(title="Recovered")["title"] == "Recovered"
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM research_report_policy_pending").fetchone()[0] == 0
    assert register(title="Renamed")["title"] == "Renamed"
    assert grants.checked == ["report"]
    grants.resource = None
    with pytest.raises(AuthorizationUnavailable, match="missing"):
        register(title="Must not save")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT title FROM research_catalog_reports WHERE report_id='report'").fetchone()[0] == "Renamed"
    with pytest.raises(RuntimeError, match="sharing requires"):
        catalog.register_report(research_id, actor="alice", report_id="public", visibility="public")
    with pytest.raises(RuntimeError, match="sharing requires"):
        catalog.update_report(research_id, "report", actor="alice", authorized_users=["bob"])
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM research_report_policy_pending").fetchone()[0] == 0


def test_same_report_registration_serializes_and_does_not_lock_sqlite_during_keycloak(tmp_path):
    path = tmp_path / "research.sqlite"
    old = ResearchCatalog(path)
    research_id = old.create_research(owner_ref="alice", title="Research")["research_id"]
    entered, release = threading.Event(), threading.Event()
    class Authorization:
        def profile_membership_access_many(self, **_kwargs):
            return {}
    class Grants:
        creations, checks = 0, 0
        def report_registration_identity(self, **_kwargs):
            return ResearchRequestIdentity("token", "issuer", "alice-subject", "alice", "alice-id")
        def ensure_new_report_resource(self, **_kwargs):
            self.creations += 1
            with sqlite3.connect(path, timeout=0.1) as db:
                db.execute("BEGIN IMMEDIATE")
                db.rollback()
            entered.set()
            assert release.wait(timeout=5)
        def require_report_resource(self, **_kwargs):
            self.checks += 1
    grants = Grants()
    catalog = ResearchCatalog(path, profile_authorizer=Authorization(), profile_grant_manager=grants)
    def register(title):
        return catalog.register_report(research_id, actor="alice", report_id="same", title=title)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(register, "first")
        assert entered.wait(timeout=5)
        second = pool.submit(register, "second")
        assert grants.creations == 1
        release.set()
        assert first.result(timeout=5)["title"] == "first"
        assert second.result(timeout=5)["title"] == "second"
    assert (grants.creations, grants.checks) == (1, 1)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM research_report_policy_pending").fetchone()[0] == 0


def test_new_research_registers_owner_profiles_and_cleans_up_failed_registration(tmp_path):
    class Authorization:
        def profile_membership_access_many(self, **_kwargs):
            return {}
    class Grants:
        def __init__(self):
            self.events, self.fail = [], False
        def create_research_resource(self, *, actor, research_id):
            self.events.append(("create", research_id))
            if actor != "alice":
                raise PermissionError("verified identity required")
            return ResearchRequestIdentity("token", "issuer", "alice-subject", "alice", "alice-id")
        def set_profile_membership(self, *, research_id, profile_ref, role, status, **_kwargs):
            self.events.append(("profile", profile_ref))
            assert (role, status) == ("owner", "active")
            if self.fail and profile_ref == "work":
                raise AuthorizationUnavailable("Keycloak unavailable")
        def delete_resource(self, *, resource_type, resource_ref, owner_subject):
            assert owner_subject == "alice-subject"
            self.events.append(("delete", resource_type, resource_ref))
    grants = Grants()
    catalog = ResearchCatalog(tmp_path / "research.sqlite", profile_authorizer=Authorization(),
                              profile_grant_manager=grants)
    created = catalog.create_research(owner_ref="alice", title="Research", profile_ref="work")
    assert [event for event in grants.events if event[0] == "profile"] == [("profile", "self"), ("profile", "work")]
    with sqlite3.connect(catalog.db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM research_catalog_memberships WHERE research_id=?",
                          (created["research_id"],)).fetchone()[0] == 2
    grants.events.clear()
    grants.fail = True
    with pytest.raises(AuthorizationUnavailable):
        catalog.create_research(owner_ref="alice", title="Failed", profile_ref="work")
    assert [event[1] for event in grants.events if event[0] == "delete"] == [
        "research_profile", "research_profile", "research",
    ]
    with sqlite3.connect(catalog.db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM research_catalog_researches WHERE title='Failed'").fetchone()[0] == 0


def test_research_creation_keeps_keycloak_resources_after_database_commit(tmp_path, monkeypatch):
    from server.manager.storage.account_domain import research_sync
    class Authorization:
        def profile_membership_access_many(self, **_kwargs):
            return {}
    class Grants:
        def __init__(self):
            self.removed = []
        def create_research_resource(self, **_kwargs):
            return ResearchRequestIdentity("token", "issuer", "alice-subject", "alice", "alice-id")
        def set_profile_membership(self, **_kwargs):
            pass
        def delete_resource(self, **kwargs):
            self.removed.append(kwargs)
    grants = Grants()
    catalog = ResearchCatalog(tmp_path / "research.sqlite", profile_authorizer=Authorization(),
                              profile_grant_manager=grants)
    catalog._synchronizer = object()
    monkeypatch.setattr(research_sync, "publish_research", lambda *_args: "pending-operation")
    def failed_schedule(_owner):
        raise RuntimeError("sync scheduler failed after commit")
    catalog._schedule_refresh = failed_schedule
    with pytest.raises(RuntimeError, match="after commit"):
        catalog.create_research(owner_ref="alice", title="Committed")
    with sqlite3.connect(catalog.db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM research_catalog_researches WHERE title='Committed'").fetchone()[0] == 1
    assert grants.removed == []

    def failed_outbox(*_args):
        raise RuntimeError("outbox failed before commit")
    monkeypatch.setattr(research_sync, "publish_research", failed_outbox)
    with pytest.raises(RuntimeError, match="before commit"):
        catalog.create_research(owner_ref="alice", title="Rolled back")
    with sqlite3.connect(catalog.db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM research_catalog_researches WHERE title='Rolled back'").fetchone()[0] == 0
    assert [item["resource_type"] for item in grants.removed] == ["research_profile", "research"]
