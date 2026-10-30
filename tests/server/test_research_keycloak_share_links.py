from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import sqlite3
import threading

import pytest

from server.identity.keycloak_authorization import AuthorizationUnavailable
from server.identity.keycloak_research import KeycloakResearchGrantManager
from server.manager.services.research_catalog import ResearchCatalog


class NoProfileGrants:
    def profile_membership_access_many(self, *, viewer, profiles):
        return {pair: {"can_view": False, "can_download": False} for pair in profiles}


class ResearchAuthorization:
    def research_access(self, *, research_id, status, viewer):
        allowed = viewer == "alice" and status == "active"
        return {"can_view": allowed, "can_manage": allowed, "can_download": allowed}


class GrantManager:
    def __init__(self):
        self.users = {name: {"id": "sub-" + name, "username": name, "enabled": True,
            "attributes": {"tr_identity_id": ["stable-" + name]}} for name in ("alice", "bob", "carol")}
        self.issuer_authorized = True
        self.fail_grant = False
        self.fail_after_grant = False
        self.grants = {}
        self.lock = threading.Lock()

    def identity_provider(self, actor):
        user = self.users.get(actor)
        return (SimpleNamespace(identity_id="stable-" + actor, subject=user["id"], username=actor)
                if user and user["enabled"] else None)

    def user_by_identity(self, identity):
        return next((user for user in self.users.values()
                     if user["attributes"].get("tr_identity_id") == [identity]), None)

    def require_resource_share(self, *, actor, resource_type, resource_ref):
        if actor != "alice" or not self.issuer_authorized:
            raise PermissionError("share denied")

    def require_link_issuer_share(self, *, identity_id, subject, research_id, resource_type, resource_ref):
        if not self.issuer_authorized:
            raise PermissionError("issuer revoked")
        assert identity_id == "stable-alice" and subject == "sub-alice"

    def _reconcile_user_grant(self, *, resource_type, resource_ref, source, identity_id, subject, scopes):
        if self.fail_grant:
            raise AuthorizationUnavailable("Keycloak is offline")
        with self.lock:
            self.grants[(resource_type, resource_ref, source, identity_id)] = (subject, tuple(scopes))
        if self.fail_after_grant:
            raise AuthorizationUnavailable("Keycloak response was lost")


def fixture(tmp_path):
    database = tmp_path / "research.sqlite"
    legacy = ResearchCatalog(database)
    research = legacy.create_research(owner_ref="alice", title="Research")
    legacy.register_report(research["research_id"], actor="alice", report_id="report")
    manager = GrantManager()
    catalog = ResearchCatalog(database, research_authorizer=ResearchAuthorization(),
        profile_authorizer=NoProfileGrants(), profile_grant_manager=manager)
    return catalog, manager, research["research_id"]


@pytest.mark.parametrize("lost_response", [False, True])
def test_one_time_link_recovers_failed_grant_without_granting_another_identity(tmp_path, lost_response):
    catalog, manager, research = fixture(tmp_path)
    link = catalog.create_share_link(target_kind="research", research_id=research,
                                     actor="alice", mode="one_time")
    manager.fail_grant = not lost_response
    manager.fail_after_grant = lost_response
    with pytest.raises(AuthorizationUnavailable):
        catalog.redeem_share_link(link["token"], actor="bob")
    manager.fail_grant = False
    manager.fail_after_grant = False
    with pytest.raises(PermissionError, match="already been redeemed"):
        catalog.redeem_share_link(link["token"], actor="carol")
    result = catalog.redeem_share_link(link["token"], actor="bob")
    assert result["research_id"] == research
    assert list(manager.grants.values()) == [("sub-bob", ("read", "use"))]
    assert catalog.redeem_share_link(link["token"], actor="bob") == result
    with sqlite3.connect(catalog.db_path) as db:
        assert db.execute("SELECT authorized_users_json FROM research_catalog_researches").fetchone()[0] == "[]"
        assert db.execute("SELECT status FROM research_share_link_claims").fetchone()[0] == "applied"
        assert link["token"] not in catalog.db_path.read_bytes().decode("utf-8", errors="ignore")


def test_concurrent_one_time_claims_cannot_grant_two_users(tmp_path):
    catalog, manager, research = fixture(tmp_path)
    link = catalog.create_share_link(target_kind="research", research_id=research,
                                     actor="alice", mode="one_time")
    def redeem(actor):
        try:
            catalog.redeem_share_link(link["token"], actor=actor)
            return actor
        except PermissionError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        winners = [value for value in pool.map(redeem, ("bob", "carol")) if value]
    assert len(winners) == 1
    assert len(manager.grants) == 1


def test_link_revocation_issuer_revocation_and_report_scopes_are_enforced(tmp_path):
    catalog, manager, research = fixture(tmp_path)
    link = catalog.create_share_link(target_kind="report", research_id=research,
                                     report_id="report", actor="alice")
    manager.issuer_authorized = False
    with pytest.raises(PermissionError, match="issuer revoked"):
        catalog.redeem_share_link(link["token"], actor="bob")
    assert not manager.grants
    manager.issuer_authorized = True
    catalog.redeem_share_link(link["token"], actor="bob")
    assert list(manager.grants.values()) == [("sub-bob", ("read",))]
    catalog.revoke_share_link(research, link["link_id"], actor="alice")
    with pytest.raises(KeyError):
        catalog.redeem_share_link(link["token"], actor="carol")
    assert len(manager.grants) == 1  # Link revocation does not revoke earlier grants.


def test_revoke_waits_for_inflight_grant_and_blocks_later_redemptions(tmp_path):
    catalog, manager, research = fixture(tmp_path)
    link = catalog.create_share_link(target_kind="research", research_id=research, actor="alice")
    entered, resume, revoke_started = threading.Event(), threading.Event(), threading.Event()
    original = manager._reconcile_user_grant
    def delayed_grant(**kwargs):
        entered.set()
        assert resume.wait(3)
        return original(**kwargs)
    manager._reconcile_user_grant = delayed_grant
    def revoke():
        revoke_started.set()
        return catalog.revoke_share_link(research, link["link_id"], actor="alice")
    with ThreadPoolExecutor(max_workers=2) as pool:
        redemption = pool.submit(catalog.redeem_share_link, link["token"], actor="bob")
        assert entered.wait(3)
        revocation = pool.submit(revoke)
        assert revoke_started.wait(3)
        assert not revocation.done()
        resume.set()
        assert redemption.result(timeout=3)["research_id"] == research
        assert revocation.result(timeout=3)["revoked_at"] > 0
    with pytest.raises(KeyError):
        catalog.redeem_share_link(link["token"], actor="carol")
    assert len(manager.grants) == 1


def test_old_link_without_reviewed_issuer_and_invalid_expiry_are_blocked(tmp_path):
    catalog, _manager, research = fixture(tmp_path)
    with pytest.raises(ValueError, match="expiry"):
        catalog.create_share_link(target_kind="research", research_id=research,
                                  actor="alice", expires_at=float("nan"))
    link = catalog.create_share_link(target_kind="research", research_id=research, actor="alice")
    with sqlite3.connect(catalog.db_path) as db:
        db.execute("DELETE FROM research_share_link_issuers WHERE link_id=?", (link["link_id"],))
    with pytest.raises(RuntimeError, match="needs identity migration"):
        catalog.redeem_share_link(link["token"], actor="bob")
    legacy = catalog.create_share_link(target_kind="research", research_id=research,
                                       actor="alice", mode="one_time")
    with sqlite3.connect(catalog.db_path) as db:
        db.execute("UPDATE research_catalog_share_links SET redeemed_by='old-user' WHERE link_id=?",
                   (legacy["link_id"],))
    with pytest.raises(RuntimeError, match="needs redemption migration"):
        catalog.redeem_share_link(legacy["token"], actor="bob")


def test_share_routes_return_authorization_errors_and_do_not_use_legacy_acl(tmp_path, monkeypatch):
    from server.manager.http import research_catalog_routes as routes
    catalog, manager, research = fixture(tmp_path)
    responses = []
    class Handler(routes.ResearchCatalogRoutesMixin):
        state = SimpleNamespace(research_catalog=catalog)
        actor, body = "alice", {"target_kind": "research"}
        def _session(self): return {"username": self.actor}
        def _json_body(self, _maximum): return self.body
    monkeypatch.setattr(routes, "json_response", lambda _self, data, status=200: responses.append((data, status)))
    handler = Handler()
    handler._post_research_catalog_routes(SimpleNamespace(path=f"/api/research/{research}/share-links"))
    assert responses[-1][1] == 201
    link = responses[-1][0]["share_link"]
    handler.actor, handler.body = "bob", {"token": link["token"]}
    manager.fail_grant = True
    handler._post_research_catalog_routes(SimpleNamespace(path="/api/research/share-links/redeem"))
    assert responses[-1][1] == 503 and not manager.grants
    manager.fail_grant = False
    handler._post_research_catalog_routes(SimpleNamespace(path="/api/research/share-links/redeem"))
    assert responses[-1][1] == 200
    with sqlite3.connect(catalog.db_path) as db:
        assert db.execute("SELECT authorized_users_json FROM research_catalog_researches").fetchone()[0] == "[]"


def test_link_issuer_requires_exact_enabled_subject_and_live_scope():
    user = {"id": "subject", "username": "alice", "enabled": True,
            "attributes": {"tr_identity_id": ["stable"]}}
    permitted = {"value": True}
    class Evaluator:
        def evaluate(self, identity_id, *, candidates):
            assert identity_id == "stable" and candidates == [
                ("research", "r", ("read", "manage")), ("research", "r", ("share",))]
            return {("research", "r", scope): permitted["value"] for scope in ("read", "manage", "share")}
    manager = KeycloakResearchGrantManager(user_by_identity=lambda _identity: user,
                                           link_policy_evaluator=Evaluator)
    manager.require_link_issuer_share(identity_id="stable", subject="subject", research_id="r",
                                      resource_type="research", resource_ref="r")
    permitted["value"] = False
    with pytest.raises(PermissionError, match="no longer authorizes"):
        manager.require_link_issuer_share(identity_id="stable", subject="subject", research_id="r",
                                          resource_type="research", resource_ref="r")
    user["id"] = "different-subject"
    with pytest.raises(PermissionError, match="identity is unavailable"):
        manager.require_link_issuer_share(identity_id="stable", subject="subject", research_id="r",
                                          resource_type="research", resource_ref="r")
