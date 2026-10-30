from copy import deepcopy
from uuid import uuid4

import pytest

from scripts.migrations.keycloak_parent_identity import apply, inspect


class Directory:
    def __init__(self, accounts):
        self.rows = {}
        self.writes = []
        for account in accounts:
            attrs = {"tr_identity_id": [account["tr_identity_id"]],
                     "legacy_username": [account["username"]]}
            if account.get("parent_username"):
                attrs["tr_parent_username"] = [account["parent_username"]]
            self.rows[account["tr_identity_id"]] = {"id": "subject-" + account["username"],
                                                     "attributes": attrs}

    def user_by_identity_id(self, identity):
        return deepcopy(self.rows.get(identity))

    def set_user_attributes(self, subject, attributes):
        row = next(row for row in self.rows.values() if row["id"] == subject)
        row["attributes"].update({key: [value] for key, value in attributes.items()})
        self.writes.append(subject)


def accounts():
    parent = {"username": "parent", "organization_id": "org", "tr_identity_id": str(uuid4())}
    child = {"username": "child", "organization_id": "org", "tr_identity_id": str(uuid4()),
             "parent_username": "parent"}
    return [parent, child]


def test_backfill_is_idempotent_and_preserves_existing_identity():
    source = accounts()
    directory = Directory(source)
    reviewed = inspect(source, directory)
    journal = []
    assert apply(reviewed, directory, record=journal.append) == 1
    assert journal == [source[1]["tr_identity_id"]]
    assert directory.rows[source[1]["tr_identity_id"]]["attributes"]["tr_parent_identity_id"] == [source[0]["tr_identity_id"]]
    assert apply(reviewed, directory, record=journal.append) == 0


def test_conflicting_parent_blocks_the_whole_plan():
    source = accounts()
    directory = Directory(source)
    directory.rows[source[1]["tr_identity_id"]]["attributes"]["tr_parent_identity_id"] = [str(uuid4())]
    reviewed = inspect(source, directory)
    assert reviewed["status"] == "blocked"
    with pytest.raises(ValueError, match="blocked"):
        apply(reviewed, directory, record=lambda _identity: None)
    assert not directory.writes


def test_legacy_parent_changed_after_review_is_not_overwritten():
    source = accounts()
    directory = Directory(source)
    reviewed = inspect(source, directory)
    directory.rows[source[1]["tr_identity_id"]]["attributes"]["tr_parent_username"] = ["other"]
    with pytest.raises(ValueError, match="changed after parent review"):
        apply(reviewed, directory, record=lambda _identity: None)
    assert not directory.writes
