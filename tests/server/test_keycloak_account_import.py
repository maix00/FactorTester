from scripts.migrations.keycloak_import_accounts import import_accounts
from uuid import uuid4


def _account(username="alice", identity_id=None):
    return {
        "username": username,
        "tr_identity_id": identity_id or str(uuid4()),
        "organization_id": "org-1",
        "level_id": "level-1",
        "role": "user",
    }


class Fake:
    def __init__(self):
        self.users = {}

    def user_by_identity_id(self, identity_id):
        return next((row for row in self.users.values()
                     if identity_id in row["attributes"].get("tr_identity_id", ())), None)

    def user(self, username):
        return self.users.get(username)

    def user_representation(self, username):
        return self.users.get(username)

    def create_user(self, **kwargs):
        assert kwargs["username"]
        user_id = "id-" + kwargs["username"]
        self.users[kwargs["username"]] = {
            "id": user_id,
            "username": kwargs["username"],
            "attributes": kwargs["attributes"],
        }
        return user_id

    def update_migrated_user(self, user_id, **kwargs):
        row = next(row for row in self.users.values() if row["id"] == user_id)
        row["attributes"].update(kwargs["attributes"])


def test_import_defaults_to_a_read_only_plan():
    accounts = [_account("alice"), _account("bob")]
    result = import_accounts(accounts, None)

    assert result["status"] == "planned"
    assert result["planned"] == 2
    assert result["created"] == result["updated"] == 0


def test_import_requires_stable_identity_and_organization_before_any_write():
    accounts = [_account("alice"), {"username": "bob"}]
    adapter = Fake()

    result = import_accounts(accounts, adapter, dry_run=False)

    assert result["status"] == "blocked"
    assert result["created"] == 0
    assert not adapter.users
    assert {row["reason"] for row in result["blockers"]} >= {
        "missing_stable_identity", "missing_organization",
    }


def test_import_is_idempotent_by_stable_identity_and_never_copies_credentials():
    account = _account("alice")
    adapter = Fake()

    first = import_accounts([account], adapter, dry_run=False)
    second = import_accounts([account], adapter, dry_run=False)

    assert first["created"] == 1
    assert second["created"] == 0
    assert second["updated"] == 1
    imported = adapter.users["alice"]
    assert imported["attributes"]["tr_identity_id"] == (account["tr_identity_id"],)
    assert not {"password", "password_hash", "salt", "hash"} & imported.keys()


def test_same_username_with_different_stable_identity_is_blocked():
    adapter = Fake()
    first = _account("alice")
    import_accounts([first], adapter, dry_run=False)

    second = _account("alice")
    result = import_accounts([second], adapter, dry_run=False)

    assert result["status"] == "blocked"
    assert result["conflicts"] == [{
        "username": "alice", "reason": "username_owned_by_other_identity",
    }]


def test_late_destination_conflict_prevents_all_batch_writes():
    adapter = Fake()
    adapter.users["bob"] = {
        "id": "existing-bob", "username": "bob",
        "attributes": {"tr_identity_id": (str(uuid4()),)},
    }
    accounts = [_account("alice"), _account("bob")]

    result = import_accounts(accounts, adapter, dry_run=False)

    assert result["status"] == "blocked"
    assert result["created"] == result["updated"] == 0
    assert "alice" not in adapter.users
    assert "bob" in adapter.users


def test_import_accepts_keycloak_lowercase_normalization_by_same_identity():
    class LowercaseKeycloak(Fake):
        def create_user(self, **kwargs):
            kwargs["username"] = kwargs["username"].lower()
            return super().create_user(**kwargs)

        def user_representation(self, username):
            return self.users.get(username.lower())

    adapter = LowercaseKeycloak()
    account = _account("MixedCase")
    assert import_accounts([account], adapter, dry_run=False)["created"] == 1
    assert import_accounts([account], adapter, dry_run=False)["updated"] == 1
    assert adapter.users["mixedcase"]["attributes"]["legacy_username"] == ("MixedCase",)
