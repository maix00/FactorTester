from copy import deepcopy

import pytest

from scripts.migrations.keycloak_login_names import apply_login_names


class Adapter:
    def __init__(self):
        self.rows = {"id-a": {"id": "id-a", "username": "organization@alice@123",
                    "attributes": {"tr_identity_id": ["stable-a"],
                                   "legacy_username": ["organization@alice@123"]}}}
        self.writes = []

    def user_by_identity_id(self, identity):
        return next((deepcopy(r) for r in self.rows.values()
                     if r["attributes"]["tr_identity_id"] == [identity]), None)

    def user_representation(self, name):
        return next((r for r in self.rows.values() if r["username"].casefold() == name.casefold()), None)

    def _put(self, path, payload):
        assert set(payload) == {"username"}
        self.writes.append(path)
        self.rows[path.split("/")[1]].update(payload)


def test_rename_preserves_subject_owner_and_is_idempotent():
    adapter = Adapter()
    accounts = [{"login_username": "Alice", "tr_identity_id": "stable-a"}]
    assert apply_login_names(accounts, adapter)["changed"] == 1
    assert not adapter.writes
    assert apply_login_names(accounts, adapter, dry_run=False)["changed"] == 1
    assert adapter.rows["id-a"]["attributes"]["legacy_username"] == ["organization@alice@123"]
    assert apply_login_names(accounts, adapter, dry_run=False)["changed"] == 0


def test_later_collision_prevents_all_writes():
    adapter = Adapter()
    adapter.rows["id-b"] = {"id": "id-b", "username": "taken", "attributes": {"tr_identity_id": ["stable-b"]}}
    with pytest.raises(ValueError, match="another identity"):
        apply_login_names([
            {"login_username": "Alice", "tr_identity_id": "stable-a"},
            {"login_username": "taken", "tr_identity_id": "stable-a"},
        ], adapter, dry_run=False)
    assert not adapter.writes


def test_display_alias_is_not_a_login_mapping():
    with pytest.raises(ValueError, match="explicit"):
        apply_login_names([{"alias": "Alice", "tr_identity_id": "stable-a"}], Adapter())
