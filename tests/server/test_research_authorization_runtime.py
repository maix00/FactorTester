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
