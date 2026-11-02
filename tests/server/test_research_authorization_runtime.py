from __future__ import annotations

from types import SimpleNamespace

from server.manager.services import research_authorization_runtime as runtime


def test_runtime_catalog_factory_injects_one_keycloak_authority(tmp_path, monkeypatch):
    from server.identity import keycloak_research

    authority = object()
    grants = object()
    resolver = lambda principal: {"identity_id": principal, "subject": principal}
    monkeypatch.setattr(keycloak_research, "KeycloakResearchAuthorization", lambda: authority)
    monkeypatch.setattr(keycloak_research, "KeycloakResearchGrantManager", lambda: grants)
    monkeypatch.setattr(keycloak_research, "resolve_keycloak_research_member", resolver)

    catalog = runtime.create_keycloak_research_catalog(tmp_path / "manager.sqlite")

    assert catalog._research_authorizer is authority
    assert catalog._profile_authorizer is authority
    assert catalog._profile_grant_manager is grants
    assert catalog._profile_identity_resolver is resolver


def test_transfer_authorizer_reuses_the_manager_catalog(monkeypatch, tmp_path):
    from server.identity import keycloak_research_transfer

    catalog = SimpleNamespace(_profile_authorizer=object())
    constructed = []

    class TransferAuthorization:
        def __init__(self, value):
            constructed.append(value)
            self.catalog = value

    monkeypatch.setattr(keycloak_research_transfer, "KeycloakResearchTransferAuthorization", TransferAuthorization)
    authorization = runtime.create_keycloak_research_transfer_authorizer(
        tmp_path / "unused.sqlite", catalog=catalog,
    )

    assert authorization.catalog is catalog
    assert constructed == [catalog]


def test_unconfigured_production_catalog_never_uses_historical_acl(tmp_path):
    import sqlite3
    import pytest
    from scripts.test.historical_research_catalog import HistoricalResearchCatalog
    from server.identity.keycloak_authorization import AuthorizationUnavailable
    from server.manager.services.research_catalog import ResearchCatalog, KeycloakResearchCreationUnavailable
    path = tmp_path / "research.sqlite"
    old = HistoricalResearchCatalog(path)
    row = old.create_research(owner_ref="alice", title="Old", visibility="public", authorized_users=["bob"])
    old.register_report(row["research_id"], actor="alice", report_id="old-report", visibility="public")
    old.add_membership(row["research_id"], actor="alice", principal_ref="bob", profile_ref="self")
    catalog = ResearchCatalog(path)
    for viewer in ("alice", "bob", "stranger", None):
        with pytest.raises(AuthorizationUnavailable):
            catalog.list_researches(viewer=viewer)
        with pytest.raises(AuthorizationUnavailable):
            catalog.get_research_summary(row["research_id"], viewer=viewer)
        with pytest.raises(AuthorizationUnavailable):
            catalog._report_access(catalog._report_row("old-report"), viewer)
    with sqlite3.connect(path) as db:
        before = db.execute("SELECT count(*) FROM research_catalog_researches").fetchone()[0]
    with pytest.raises(KeycloakResearchCreationUnavailable):
        catalog.create_research(owner_ref="alice", title="Must not write")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM research_catalog_researches").fetchone()[0] == before
