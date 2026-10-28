from __future__ import annotations

import json

import settings as Settings

from server.manager.storage.account_domain.local import LocalAccountDomainStore
from tools.data.sqlite.account_manager.product_group import save_product_groups


def test_product_group_definition_revisions_are_immutable_and_ignore_reordering(
    tmp_path, monkeypatch,
):
    database = tmp_path / "groups.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", str(database))
    groups = [
        {
            "id": "pg_a",
            "name": "A",
            "paths": ["CN/Futures/T"],
            "selection_paths": ["CN/Futures/T"],
            "category_ids": ["debt-futures"],
            "updated_at": "ignored-in-version",
        },
        {
            "id": "pg_b",
            "name": "B",
            "paths": ["CN/Futures/TL"],
            "selection_paths": ["CN/Futures/TL"],
            "category_ids": [],
        },
    ]
    save_product_groups("alice", groups)
    mirror = LocalAccountDomainStore(database)
    revisions = mirror.list_entities(
        principal="alice", entity_type="versioned_object_revision",
    )
    assert len(revisions) == 2
    first = next(row for row in revisions if row["payload"]["revision_manifest"]["object_ref"] == "product-group:pg_a")
    definition = first["payload"]["object_definition"]
    assert definition == {
        "id": "pg_a", "name": "A", "selection_paths": ["CN/Futures/T"],
        "category_ids": ["debt-futures"],
    }

    save_product_groups("alice", list(reversed(groups)))
    assert len(mirror.list_entities(
        principal="alice", entity_type="versioned_object_revision",
    )) == 2

    changed = [dict(item) for item in groups]
    changed[0] = {
        **changed[0], "paths": ["CN/Futures/TF"],
        "selection_paths": ["CN/Futures/TF"],
    }
    save_product_groups("alice", changed)
    after_edit = mirror.list_entities(
        principal="alice", entity_type="versioned_object_revision",
    )
    assert len(after_edit) == 3
    assert len({row["entity_id"] for row in after_edit}) == 3

    save_product_groups("alice", [changed[1]])
    assert len(mirror.list_entities(
        principal="alice", entity_type="versioned_object_revision",
    )) == 3
    assert mirror.get_entity("alice", "product_group", "pg_a")["deleted"] is True
    assert "source_code" not in json.dumps(after_edit)
