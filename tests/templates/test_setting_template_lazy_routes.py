from flask import Flask
import pytest

from server.modules.products import product_group_routes
from server.modules.templates.backend_settings_migration import migrate_snapshot_backend_settings


def test_product_group_resolve_returns_only_requested_ids(monkeypatch):
    monkeypatch.setattr(product_group_routes, "require_user", lambda: "alice")
    monkeypatch.setattr(
        product_group_routes,
        "load_product_groups",
        lambda username: [
            {"id": "pg-day", "name": "中国期货日盘", "paths": ["Day"]},
            {"id": "pg-night", "name": "中国期货夜盘", "paths": ["Night"]},
        ],
    )
    app = Flask(__name__)

    with app.test_request_context("/api/product-groups/resolve", method="POST", json={"ids": ["pg-day"]}):
        response = product_group_routes.resolve_product_groups.__wrapped__()

    payload = response.get_json()
    assert payload == {
        "success": True,
        "groups": [{"id": "pg-day", "name": "中国期货日盘", "paths": ["Day"]}],
    }


def test_product_group_subject_route_uses_product_group_owned_relation(monkeypatch):
    monkeypatch.setattr(product_group_routes, "require_user", lambda: "alice")
    calls = []
    validations = []

    monkeypatch.setattr(
        product_group_routes,
        "_validate_registered_subjects",
        lambda username, **values: validations.append((username, values)),
    )

    def change(username, product_group_ref, **values):
        calls.append((username, product_group_ref, values))
        return {
            "product_group_ref": product_group_ref,
            "factor_refs": values["factor_refs"],
            "factor_set_refs": values["factor_set_refs"],
        }

    monkeypatch.setattr(product_group_routes, "change_product_group_subjects", change)
    app = Flask(__name__)
    with app.test_request_context(
        "/api/product-groups/pg-day/subjects",
        method="POST",
        json={
            "action": "add",
            "factor_refs": ["factor:sha256:factor-a"],
            "factor_set_refs": ["factor-set:profile-alice:momentum"],
        },
    ):
        response = product_group_routes.product_group_subjects_view.__wrapped__(
            "pg-day"
        )

    assert response.get_json()["subjects"]["product_group_ref"] == (
        "product-group:pg-day"
    )
    assert calls == [("alice", "product-group:pg-day", {
        "action": "add",
        "factor_refs": ["factor:sha256:factor-a"],
        "factor_set_refs": ["factor-set:profile-alice:momentum"],
    })]
    assert validations == [("alice", {
        "factor_refs": ["factor:sha256:factor-a"],
        "factor_set_refs": ["factor-set:profile-alice:momentum"],
    })]


def test_product_group_binding_requires_separately_registered_subjects(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        product_group_routes,
        "build_factor_library_overview",
        lambda *_args, **_kwargs: {"factors": []},
    )
    monkeypatch.setattr(
        product_group_routes,
        "build_client_library_projection",
        lambda *_args, **_kwargs: {
            "factors": [{"factor_ref": "factor:sha256:registered"}],
        },
    )
    monkeypatch.setattr(
        product_group_routes,
        "factor_set_catalog",
        lambda _username: [{
            "set_ref": "factor-set:profile-alice:registered",
        }],
    )

    product_group_routes._validate_registered_subjects(
        "alice",
        factor_refs=["factor:sha256:registered"],
        factor_set_refs=["factor-set:profile-alice:registered"],
    )
    with pytest.raises(ValueError, match="先注册因子"):
        product_group_routes._validate_registered_subjects(
            "alice",
            factor_refs=["factor:sha256:missing"],
            factor_set_refs=[],
        )
    with pytest.raises(ValueError, match="先同步因子集合"):
        product_group_routes._validate_registered_subjects(
            "alice",
            factor_refs=[],
            factor_set_refs=["factor-set:profile-alice:missing"],
        )


def test_snapshot_migration_moves_legacy_time_to_execution_settings():
    snapshot, changed = migrate_snapshot_backend_settings({
        "time_data": {
            "start_date": "2024-01-02",
            "start_time": "09:00",
            "end_date": "2026-05-31",
            "end_time": "15:00",
            "timezone": "Asia/Shanghai",
            "time_precision": "exact",
        },
        "local_settings": {
            "initialCapital": {"initialCapital": 100000000},
            "calendarFreq": {"autoGroupCalendarFreq": True, "groupCalendarFreq": "1min"},
        },
    })

    assert changed is True
    assert "time_data" not in snapshot
    settings = snapshot["execution"]["settings"]
    assert "initialCapital" not in settings
    assert "calendarFreq" not in settings
    assert "backendBacktestSettings" not in settings
    assert settings == {
        "start_date": "2024-01-02",
        "start_time": "09:00",
        "end_date": "2026-05-31",
        "end_time": "15:00",
        "initial_capital": 100000000,
    }


def test_snapshot_migration_drops_deprecated_display_metadata_and_keeps_identity():
    deprecated_display_key = "short" + "Alias"
    snapshot, changed = migrate_snapshot_backend_settings({
        "group_settings": {
            "groups": [{
                "group_id": "strategy-1",
                "key": "旧显示名",
                deprecated_display_key: "A1",
                "factorAlias": "FactorA",
                "splitCount": 1,
                "groupIndex": 1,
                "unknown_ui_state": True,
            }],
        },
    })

    group = snapshot["group_settings"]["groups"][0]
    assert changed is True
    assert group["id"] == "strategy-1"
    assert group["name"] == "旧显示名"
    assert deprecated_display_key not in group
    assert "key" not in group
    assert "unknown_ui_state" not in group


def test_snapshot_migration_moves_submissions_to_product_path_selections_with_group_id_by_paths():
    snapshot, changed = migrate_snapshot_backend_settings(
        {
            "submissions": [{
                "id": "old-sub",
                "label": "Metals",
                "product_group": "Old Name",
                "selected_paths": ["B/Path", "A/Path"],
            }],
            "group_settings": {
                "groups": [{
                    "id": "g1",
                    "testerId": "old-sub",
                    "factorAlias": "F",
                    "splitCount": 5,
                    "groupIndex": 1,
                }]
            },
        },
        product_groups=[{
            "id": "pg-metals",
            "name": "Metals Template",
            "paths": ["A/Path", "B/Path"],
        }],
    )

    assert changed is True
    assert "submissions" not in snapshot
    assert "product_path_selections" not in snapshot
    assert snapshot["group_settings"]["groups"][0]["product_path_selection"] == {
        "product_path_selection_id": "pg-metals",
    }
    assert "testerId" not in snapshot["group_settings"]["groups"][0]


def test_snapshot_migration_does_not_fallback_unscoped_paths_to_local_settings():
    snapshot, changed = migrate_snapshot_backend_settings(
        {
            "submissions": [{
                "id": "plain-paths",
                "selected_paths": ["Only/Paths"],
            }],
        },
        product_groups=[],
    )

    assert changed is True
    assert "product_path_selections" not in snapshot
    assert "submissions" not in snapshot
    assert "local_settings" not in snapshot


def test_snapshot_migration_normalizes_existing_product_path_selection_fields():
    snapshot, changed = migrate_snapshot_backend_settings(
        {
            "local_settings": {
                "product_path_selection": {
                    "product_group_template_id": "pg-local",
                    "paths": ["B/Path", "A/Path"],
                }
            },
            "group_settings": {
                "groups": [{
                    "id": "g1",
                    "testerId": "sel-1",
                    "product_path_selection": {
                        "path_id": "pg-group",
                        "selected_paths": ["D/Path", "C/Path"],
                    },
                }]
            },
        },
        product_groups=[],
    )

    assert changed is True
    assert snapshot["execution"]["settings"]["product_path_selection"] == {
        "product_path_selection_id": "pg-local",
    }
    selection = snapshot["group_settings"]["groups"][0]["product_path_selection"]
    assert selection == {"product_path_selection_id": "pg-group"}


def test_snapshot_migration_relinks_existing_selection_to_matching_product_group():
    snapshot, changed = migrate_snapshot_backend_settings(
        {
            "group_settings": {
                "groups": [{
                    "id": "g1",
                    "product_path_selection": {
                        "id": "old-selection",
                        "product_path_selection_id": "old-selection",
                        "label": "中国期货日盘",
                        "paths": ["Futures/Day", "Futures/More"],
                    },
                }]
            },
        },
        product_groups=[{
            "id": "pg-day",
            "name": "中国期货日盘",
            "paths": ["Futures/More", "Futures/Day"],
        }],
    )

    assert changed is True
    selection = snapshot["group_settings"]["groups"][0]["product_path_selection"]
    assert selection == {"product_path_selection_id": "pg-day"}


def test_snapshot_migration_materializes_parent_product_path_selection_on_derived_groups():
    snapshot, changed = migrate_snapshot_backend_settings(
        {
            "group_settings": {
                "groups": [
                    {
                        "id": "parent",
                        "testerId": "sel-parent",
                        "product_path_selection": {
                            "product_path_selection_id": "sel-parent",
                            "product_group_template_id": "pg-parent",
                            "paths": ["Parent/Path"],
                        },
                    },
                    {
                        "id": "child",
                        "parentId": "parent",
                    },
                ]
            },
        },
        product_groups=[],
    )

    assert changed is True
    child = snapshot["group_settings"]["groups"][1]
    assert "testerId" not in child
    assert child["product_path_selection"] == {
        "product_path_selection_id": "pg-parent",
    }
