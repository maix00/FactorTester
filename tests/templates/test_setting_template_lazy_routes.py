from flask import Flask

from server.modules.templates import setting_snapshot_routes as routes
from server.modules.templates.backend_settings_migration import migrate_snapshot_backend_settings


def test_template_list_returns_metadata_without_snapshot(monkeypatch):
    monkeypatch.setattr(routes, "require_user", lambda: "alice")
    monkeypatch.setattr(
        routes,
        "list_user_template_metadata",
        lambda *args, **kwargs: [
            {"id": "tpl-1", "name": "模板1", "ff_alias": "MmRet", "updated_at": 1.0}
        ],
    )
    app = Flask(__name__)

    with app.test_request_context("/api/single_factor_setting_templates/MmRet"):
        response = routes.list_single_factor_setting_templates.__wrapped__("MmRet")

    payload = response.get_json()
    assert payload == {
        "success": True,
        "templates": [
            {
                "id": "tpl-1",
                "name": "模板1",
                "ff_alias": "MmRet",
                "factor_family_alias": "MmRet",
            }
        ],
    }
    assert "snapshot" not in payload["templates"][0]
    assert "summary" not in payload["templates"][0]


def test_template_detail_loads_only_requested_template(monkeypatch):
    calls = []
    template = {"id": "tpl-2", "name": "模板2", "snapshot": {"params_list": [{"N": 2}]}}
    monkeypatch.setattr(routes, "require_user", lambda: "alice")

    def load_one(*args, **kwargs):
        calls.append((args, kwargs))
        return template

    monkeypatch.setattr(routes, "load_user_template", load_one)
    monkeypatch.setattr(routes, "load_product_groups", lambda username: [])
    monkeypatch.setattr(routes, "refresh_template_product_group_paths", lambda value, groups: value)
    app = Flask(__name__)

    with app.test_request_context("/api/single_factor_setting_templates/MmRet/tpl-2"):
        response = routes.get_single_factor_setting_template.__wrapped__("MmRet", "tpl-2")

    assert response.get_json() == {"success": True, "template": template}
    assert len(calls) == 1
    assert calls[0][0][2] == "tpl-2"


def test_snapshot_migration_moves_legacy_time_to_flat_local_settings():
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
    assert "initialCapital" not in snapshot["local_settings"]
    assert "calendarFreq" not in snapshot["local_settings"]
    assert "backendBacktestSettings" not in snapshot["local_settings"]
    assert snapshot["local_settings"] == {
        "start_date": "2024-01-02",
        "start_time": "09:00",
        "end_date": "2026-05-31",
        "end_time": "15:00",
    }
