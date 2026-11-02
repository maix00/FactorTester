from types import SimpleNamespace

import pytest

from server.identity.keycloak_authorization import AuthorizationUnavailable, keycloak_resource_uri
from server.identity.keycloak_profile_directory import KeycloakProfileDirectoryAccess, profile_resource_ref


class Directory:
    def __init__(self):
        self.calls = []
    def user_by_identity_id(self, stable):
        self.calls.append(stable)
        if stable == "missing":
            return None
        return {"id": "subject", "username": "owner", "enabled": True,
                "attributes": {"tr_identity_id": [stable], "legacy_username": ["owner"]}}


def profile(profile_id="self", *, owner="owner", stable="owner-id", source="manager-a"):
    return {"profile_id": profile_id, "source_server_id": source,
            "session_binding": {"principal_ref": owner, "principal_identity_id": stable},
            # These legacy fields must never be treated as a current grant.
            "visibility": "public", "authorized_users": ["viewer"]}


def test_profile_scope_uses_source_and_frozen_stable_owner_not_legacy_acl():
    directory = Directory()
    allowed = {"read": True, "use": False}
    calls = []
    def authorize(token, *, permissions, use_cache):
        calls.append((token, permissions, use_cache))
        return {(uri, scope): allowed[scope] for uri, _name, scope in permissions}
    service = KeycloakProfileDirectoryAccess(manager_id="manager-a", adapter=directory,
        owner_identity=lambda owner, profile_id: "owner-id",
        identity=lambda: SimpleNamespace(username="viewer", token="verified"), authorize=authorize)
    key = ("manager-a", "owner", "self")
    assert service.access_many(viewer="viewer", profiles=[profile()])[key] == {
        "can_view": True, "can_view_conversations": False, "reason": "keycloak"}
    assert calls[0][0] == "verified" and calls[0][2] is False
    assert all(uri == keycloak_resource_uri("profile", profile_resource_ref("manager-a", "owner-id", "self"))
               for uri, _name, _scope in calls[0][1])
    allowed["read"] = False
    assert service.access_many(viewer="viewer", profiles=[profile()])[key]["can_view"] is False
    assert directory.calls == ["owner-id", "owner-id"]


def test_unmapped_owner_and_foreign_source_cannot_inherit_a_same_name_grant():
    directory = Directory()
    service = KeycloakProfileDirectoryAccess(manager_id="manager-a", adapter=directory,
        owner_identity=lambda owner, profile_id: {"self": "", "other": "missing"}.get(profile_id),
        identity=lambda: SimpleNamespace(username="viewer", token="verified"),
        authorize=lambda *_args, **_kwargs: pytest.fail("unmapped Profile must not be granted"))
    values = [profile(stable=""), profile("other", stable="missing"), profile("peer", source="manager-b")]
    result = service.access_many(viewer="viewer", profiles=values)
    assert result[("manager-a", "owner", "self")]["reason"] == "owner_identity_needs_repair"
    assert result[("manager-a", "owner", "other")]["reason"] == "owner_identity_needs_repair"
    assert result[("manager-b", "owner", "peer")]["reason"] == "foreign_source_requires_delegation"
    assert directory.calls == ["missing"]
    with pytest.raises(PermissionError):
        service.access_many(viewer="attacker", profiles=[profile()])


def test_profile_batch_deduplicates_owner_lookups_and_bounds_uma_requests():
    directory, batches = Directory(), []
    def authorize(_token, *, permissions, use_cache):
        batches.append(len(permissions))
        return {(uri, scope): True for uri, _name, scope in permissions}
    service = KeycloakProfileDirectoryAccess(manager_id="manager-a", adapter=directory,
        owner_identity=lambda owner, profile_id: "owner-id",
        identity=lambda: SimpleNamespace(username="viewer", token="verified"), authorize=authorize)
    result = service.access_many(viewer="viewer", profiles=[profile(str(i)) for i in range(130)])
    assert len(result) == 130 and all(row["can_view_conversations"] for row in result.values())
    assert batches == [256, 4] and directory.calls == ["owner-id"]


def test_keycloak_outage_is_not_interpreted_as_public_profile_access():
    class Offline:
        def user_by_identity_id(self, _stable):
            raise ConnectionError("offline")
    service = KeycloakProfileDirectoryAccess(manager_id="manager-a", adapter=Offline(),
        owner_identity=lambda owner, profile_id: "owner-id",
        identity=lambda: SimpleNamespace(username="viewer", token="verified"))
    with pytest.raises(AuthorizationUnavailable):
        service.access_many(viewer="viewer", profiles=[profile()])


def test_profile_document_cannot_choose_the_frozen_owner_identity():
    service = KeycloakProfileDirectoryAccess(manager_id="manager-a", adapter=Directory(),
        owner_identity=lambda owner, profile_id: None,
        identity=lambda: SimpleNamespace(username="viewer", token="verified"),
        authorize=lambda *_args, **_kwargs: pytest.fail("unregistered identity must not authorize"))
    forged = profile(stable="owner-id")
    forged["owner_identity_id"] = "owner-id"
    assert service.access_many(viewer="viewer", profiles=[forged])[("manager-a", "owner", "self")]["reason"] == "owner_identity_needs_repair"
