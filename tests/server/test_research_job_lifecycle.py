from __future__ import annotations

import hashlib
import json

from flask import Flask
import pytest

import settings as Settings
from server.modules.single_factor_test import sft_bp
from server.jobs.models import SchedulingEntitlement
from server.jobs.repository import JobRepository
from server.services import research_configurations, research_runs, research_workspaces
from tools.data.sqlite.db import connect_sqlite


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "research-jobs.sqlite")
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = "alice"
    return client


def _create_workspace(client):
    response = client.post("/api/workspaces", json={
        "title": "multi factor research",
        "factor_families": [{"alias": "MmRet"}, {"alias": "MmMADevRat"}],
        "factors": [
            {"factor_family_alias": "MmRet", "alias": "MmRet|P:CA|N:10d|$F:1d"},
            {"factor_family_alias": "MmMADevRat", "alias": "MmMADevRat|P:CA|N:10d|$F:1d|$Rev"},
        ],
    })
    assert response.status_code == 201
    return response.get_json()["workspace"]


def _payload(workspace, *, n: str = "10d"):
    shared = dict(workspace["configuration"]["payload"]["shared"])
    shared["user_defined_shared_setting"] = {"enabled": True, "threshold": 1.25}
    return {
        "schema_version": 1,
        "shared": shared,
        "analyses": {
            "ic": {"factor_configs": [{"N": n}], "product_paths": ["core8_path"]},
            "backtest": {
                "local_settings": {"user_defined_local_setting": "kept"},
                "groups": [{
                    "id": "A1", "name": "A1", "splitCount": 5, "groupIndex": 1,
                    "factorAlias": "MmRet|P:CA|N:10d|$F:1d",
                    "product_path_selection_id": "core8",
                    "user_defined_group_setting": {"mode": "custom"},
                }],
                "ls_configs": [{
                    "id": "LS1", "longGroupId": "A1", "shortGroupId": "A5",
                    "user_defined_ls_setting": [1, 2, 3],
                }],
                "product_selections": {"core8": {"id": "core8", "selected_paths": ["core8_path"]}},
            },
            "factor_evaluation": {"factor_alias": "MmRet|P:CA|N:10d|$F:1d"},
            "factor_type_analysis": {"factor_alias": "MmRet|P:CA|N:10d|$F:1d"},
        },
        "ui": {"selected_tab": "ic"},
    }


def _update(client, workspace, payload):
    response = client.put(
        f"/api/workspaces/{workspace['workspace_id']}/configuration",
        json={
            "expected_revision": workspace["configuration"]["revision"],
            "payload": payload,
        },
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    workspace["configuration"] = response.get_json()["configuration"]
    return workspace


def test_workspace_has_one_mutable_configuration_not_revision_history(client) -> None:
    workspace = _create_workspace(client)
    _update(client, workspace, _payload(workspace))
    _update(client, workspace, _payload(workspace, n="20d"))

    reopened = client.get(f"/api/workspaces/{workspace['workspace_id']}").get_json()["workspace"]

    assert reopened["configuration"]["revision"] == 3
    assert reopened["configuration"]["payload"]["analyses"]["ic"]["factor_configs"] == [{"N": "20d"}]
    from tools.data.sqlite.db import connect_sqlite
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM research_configurations WHERE workspace_id=?",
            (workspace["workspace_id"],),
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_workspace_revisions'"
        ).fetchone() is None


def test_template_save_and_load_copy_the_same_configuration_schema(client) -> None:
    workspace = _create_workspace(client)
    _update(client, workspace, _payload(workspace))
    saved = client.post(
        f"/api/workspaces/{workspace['workspace_id']}/configuration/templates",
        json={"name": "Core 8 template"},
    )
    template = saved.get_json()["template"]

    _update(client, workspace, _payload(workspace, n="20d"))
    loaded = client.post(
        f"/api/workspaces/{workspace['workspace_id']}/configuration/load-template",
        json={
            "configuration_id": template["configuration_id"],
            "expected_revision": workspace["configuration"]["revision"],
        },
    )
    value = loaded.get_json()["configuration"]

    assert saved.status_code == 201
    assert value["payload"] == template["payload"]
    assert value["payload"]["shared"]["user_defined_shared_setting"]["threshold"] == 1.25
    assert value["payload"]["analyses"]["backtest"]["local_settings"]["user_defined_local_setting"] == "kept"
    assert value["payload"]["analyses"]["backtest"]["groups"][0]["user_defined_group_setting"] == {"mode": "custom"}
    assert value["payload"]["analyses"]["backtest"]["ls_configs"][0]["user_defined_ls_setting"] == [1, 2, 3]
    assert value["source_configuration_id"] == template["configuration_id"]
    assert value["revision"] == 4


def test_legacy_templates_are_migrated_once_and_removed(client) -> None:
    legacy_rows = [("global", "MmRet", "", {
        "id": "legacy-1",
        "name": "legacy",
        "ff_alias": "MmRet",
        "snapshot": {
            "factor": "MmRet|P:CA|N:10d|$F:1d",
            "factor_candidates": [{"alias": "MmRet|P:CA|N:10d|$F:1d"}],
            "submissions": [{"id": "selection-1", "selected_paths": ["core8_path"]}],
            "group_settings": {"groups": [{
                "id": "A1", "testerId": "selection-1", "groupCount": 5,
                "groupIndex": 0, "factorAlias": "MmRet|P:CA|N:10d|$F:1d",
            }]},
        },
    }), ("params", "", "MmRet", {
        "id": "legacy-params", "name": "__global_tpl_old__", "params_list": [{"N": "10d"}],
    }), ("time", "", "", {
        "id": "legacy-time", "name": "old time", "time_data": {"start_date": "2024-01-01"},
    })]
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE account_templates (
                username TEXT NOT NULL, kind TEXT NOT NULL, scope_key TEXT NOT NULL,
                ff_alias TEXT NOT NULL, template_id TEXT NOT NULL, sort_order INTEGER NOT NULL,
                name TEXT NOT NULL, item_ff_alias TEXT NOT NULL,
                payload_json TEXT NOT NULL, updated_at REAL NOT NULL,
                PRIMARY KEY (username, kind, scope_key, ff_alias, template_id)
            )
            """
        )
        for sort_order, (kind, scope_key, ff_alias, payload) in enumerate(legacy_rows):
            conn.execute(
                "INSERT INTO account_templates VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, 1.0)",
                (
                    "alice", kind, scope_key, ff_alias, payload["id"], sort_order,
                    payload["name"], json.dumps(payload),
                ),
            )

    dry_run = research_configurations.migrate_legacy_templates(apply=False)
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_configurations'"
        ).fetchone() is None
    applied = research_configurations.migrate_legacy_templates(apply=True)

    assert dry_run["scanned"] == 3 and dry_run["migrated"] == 1
    assert dry_run["retired_legacy_components"] == {"params": 1, "time": 1}
    assert applied["migrated"] == 1 and applied["errors"] == []
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='account_templates'"
        ).fetchone() is None
    templates = research_configurations.list_templates(owner="alice")
    assert templates[0]["legacy_template_id"] == "MmRet:legacy-1"
    assert templates[0]["payload"]["shared"]["factor_families"] == [{"alias": "MmRet"}]
    assert templates[0]["payload"]["shared"]["factors"] == [{
        "alias": "MmRet|P:CA|N:10d|$F:1d",
        "factor_family_alias": "MmRet",
    }]
    assert templates[0]["payload"]["analyses"]["backtest"]["groups"][0]["splitCount"] == 5
    migrated_backtest = templates[0]["payload"]["analyses"]["backtest"]
    assert "factor" not in migrated_backtest and "factor_candidates" not in migrated_backtest
    assert migrated_backtest["local_settings"]["factor"] == "MmRet|P:CA|N:10d|$F:1d"
    assert migrated_backtest["local_settings"]["factor_candidates"] == [{
        "alias": "MmRet|P:CA|N:10d|$F:1d",
    }]


def test_legacy_workspace_and_runs_require_then_apply_one_time_migration(client) -> None:
    draft = {
        "factor_alias": "MmRet|P:CA|N:10d|$F:1d",
        "group_settings": {"groups": []},
    }
    run_spec = {"workspace_id": "legacy-workspace", "workspace_revision": 3}
    run_raw = json.dumps(run_spec, sort_keys=True).encode()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        conn.executescript(
            """
            CREATE TABLE research_workspaces (
                workspace_id TEXT PRIMARY KEY, owner TEXT NOT NULL, kind TEXT NOT NULL,
                title TEXT NOT NULL, factor_family_alias TEXT NOT NULL DEFAULT '',
                current_revision INTEGER NOT NULL, created_at REAL NOT NULL,
                updated_at REAL NOT NULL, deleted_at REAL
            );
            CREATE TABLE research_workspace_revisions (
                workspace_id TEXT NOT NULL, revision INTEGER NOT NULL,
                schema_version INTEGER NOT NULL, draft_json TEXT NOT NULL,
                created_at REAL NOT NULL, PRIMARY KEY (workspace_id, revision)
            );
            CREATE TABLE research_runs (
                run_id TEXT PRIMARY KEY, owner TEXT NOT NULL, workspace_id TEXT NOT NULL,
                workspace_revision INTEGER NOT NULL, kind TEXT NOT NULL,
                lifecycle_policy TEXT NOT NULL, run_spec_version INTEGER NOT NULL,
                run_spec_hash TEXT NOT NULL, run_spec_json TEXT NOT NULL, created_at REAL NOT NULL
            );
            """
        )
        conn.execute(
            "INSERT INTO research_workspaces VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)",
            ("legacy-workspace", "alice", "single_factor", "Legacy", "MmRet", 3, 1.0, 2.0),
        )
        conn.execute(
            "INSERT INTO research_workspace_revisions VALUES (?, ?, ?, ?, ?)",
            ("legacy-workspace", 3, 1, json.dumps(draft), 2.0),
        )
        conn.execute(
            "INSERT INTO research_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "legacy-run", "alice", "legacy-workspace", 3, "single_factor", "durable", 1,
                hashlib.sha256(run_raw).hexdigest(), run_raw.decode(), 3.0,
            ),
        )

    with pytest.raises(RuntimeError, match="migrate_research_configurations"):
        research_workspaces.load_workspace(workspace_id="legacy-workspace", owner="alice")
    with pytest.raises(RuntimeError, match="migrate_research_configurations"):
        research_runs.load_run(run_id="legacy-run", owner="alice")

    dry_run = research_configurations.migrate_legacy_workspaces_and_runs(apply=False)
    applied = research_configurations.migrate_legacy_workspaces_and_runs(apply=True)

    assert dry_run["legacy_workspace_schema"] is True
    assert dry_run["legacy_run_schema"] is True
    assert applied["workspace_configurations_created"] == 1
    workspace = research_workspaces.load_workspace(workspace_id="legacy-workspace", owner="alice")
    run = research_runs.load_run(run_id="legacy-run", owner="alice")
    assert workspace is not None
    assert workspace["configuration"]["revision"] == 1
    assert workspace["configuration"]["payload"]["shared"]["factors"][0]["alias"] == draft["factor_alias"]
    assert run is not None
    assert run["configuration_id"] == workspace["configuration"]["configuration_id"]
    assert run["configuration_revision"] == 1
    assert run["run_spec"]["workspace_revision"] == 3
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_workspace_revisions'"
        ).fetchone() is None


def test_run_freezes_configuration_while_workspace_keeps_editing(client) -> None:
    workspace = _create_workspace(client)
    _update(client, workspace, _payload(workspace))

    submitted = client.post("/api/runs", json={
        "workspace_id": workspace["workspace_id"],
        "configuration_revision": workspace["configuration"]["revision"],
        "analyses": ["ic"],
    }).get_json()
    _update(client, workspace, _payload(workspace, n="20d"))

    frozen = client.get(f"/api/runs/{submitted['run_id']}").get_json()["run"]
    assert frozen["configuration_revision"] == 2
    assert frozen["run_spec"]["configuration"]["analyses"]["ic"]["factor_configs"] == [{"N": "10d"}]


def test_run_revalidates_and_freezes_external_factor_artifact(client, monkeypatch) -> None:
    workspace = _create_workspace(client)
    payload = _payload(workspace)
    payload["shared"]["external_factor_artifacts"] = [{
        "manifest_path": "/research/gtht_handoff.json",
        "artifact_id": "academic_mom:abc",
        "manifest_sha256": "manifest-hash",
        "factor_sha256": "factor-hash",
    }]
    _update(client, workspace, payload)
    frozen_artifact = {
        "artifact_id": "academic_mom:abc",
        "kind": "precomputed_factor_artifact",
        "alpha_id": "academic_mom",
        "manifest_path": "/research/gtht_handoff.json",
        "manifest_sha256": "manifest-hash",
        "factor_path": "/research/factor.parquet",
        "factor_sha256": "factor-hash",
        "information_time": "daily_bar_close",
        "execution": "next_bar",
        "research_status": "experimental_unvalidated",
        "rows": 3980,
        "products": 97,
        "finite_observations": 194316,
    }
    monkeypatch.setattr(
        "server.services.external_factor_artifacts.validate_and_freeze",
        lambda path: frozen_artifact,
    )

    response = client.post("/api/runs", json={
        "workspace_id": workspace["workspace_id"],
        "configuration_revision": workspace["configuration"]["revision"],
        "analyses": ["ic"],
    })

    assert response.status_code == 202, response.get_data(as_text=True)
    run = response.get_json()["run"]
    assert (
        run["run_spec"]["configuration"]["shared"]["external_factor_artifacts"]
        == [frozen_artifact]
    )
    job = JobRepository().list(owner="alice", run_id=run["run_id"])[0]
    assert job.job_spec["external_factor_artifacts"] == [frozen_artifact]


def test_run_rejects_external_factor_when_hash_changes(client, monkeypatch) -> None:
    workspace = _create_workspace(client)
    payload = _payload(workspace)
    payload["shared"]["external_factor_artifacts"] = [{
        "manifest_path": "/research/gtht_handoff.json",
        "factor_sha256": "old-hash",
    }]
    _update(client, workspace, payload)
    monkeypatch.setattr(
        "server.services.external_factor_artifacts.validate_and_freeze",
        lambda path: {
            "artifact_id": "academic_mom:new",
            "manifest_sha256": "manifest-hash",
            "factor_sha256": "new-hash",
        },
    )

    response = client.post("/api/runs", json={
        "workspace_id": workspace["workspace_id"],
        "configuration_revision": workspace["configuration"]["revision"],
        "analyses": ["ic"],
    })

    assert response.status_code == 400
    assert "factor_sha256 changed" in response.get_json()["error"]


def test_historical_run_can_be_cloned_into_a_new_editable_workspace(client) -> None:
    workspace = _create_workspace(client)
    _update(client, workspace, _payload(workspace))
    submitted = client.post("/api/runs", json={
        "workspace_id": workspace["workspace_id"],
        "configuration_revision": workspace["configuration"]["revision"],
        "analyses": ["ic"],
    }).get_json()
    _update(client, workspace, _payload(workspace, n="20d"))

    cloned = client.post(
        f"/api/runs/{submitted['run_id']}/clone-workspace",
        json={"title": "Historical IC clone"},
    )

    assert cloned.status_code == 201, cloned.get_data(as_text=True)
    value = cloned.get_json()["workspace"]
    assert value["workspace_id"] != workspace["workspace_id"]
    assert value["title"] == "Historical IC clone"
    assert value["configuration"]["revision"] == 1
    assert value["configuration"]["payload"]["analyses"]["ic"]["factor_configs"] == [{"N": "10d"}]


def test_migration_repairs_registered_settings_in_already_migrated_templates(client) -> None:
    workspace = _create_workspace(client)
    template = research_configurations.save_template(
        workspace_id=workspace["workspace_id"], owner="alice", name="pre-fix migration",
    )
    payload = template["payload"]
    payload["analyses"]["backtest"] = {
        "factor": "MmRet|P:CA|N:10d|$F:1d",
        "local_settings": {"start_date": "2024-01-01"},
        "groups": [],
    }
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        conn.execute(
            """
            UPDATE research_configurations
            SET payload_json=?, legacy_template_id='MmRet:legacy-before-fix'
            WHERE configuration_id=?
            """,
            (json.dumps(payload), template["configuration_id"]),
        )

    dry_run = research_configurations.migrate_legacy_templates(apply=False)
    applied = research_configurations.migrate_legacy_templates(apply=True)
    repaired = research_configurations.list_templates(owner="alice")[0]

    assert dry_run["canonical_templates_repaired"] == 1
    assert applied["canonical_templates_repaired"] == 1
    backtest = repaired["payload"]["analyses"]["backtest"]
    assert "factor" not in backtest
    assert backtest["local_settings"] == {
        "start_date": "2024-01-01",
        "factor": "MmRet|P:CA|N:10d|$F:1d",
    }


def test_all_analyses_dispatch_importable_process_runners(client) -> None:
    workspace = _create_workspace(client)
    _update(client, workspace, _payload(workspace))
    response = client.post("/api/runs", json={
        "workspace_id": workspace["workspace_id"],
        "configuration_revision": workspace["configuration"]["revision"],
        "analyses": ["ic", "factor_evaluation", "factor_type_analysis", "backtest"],
    })

    assert response.status_code == 202, response.get_data(as_text=True)
    jobs = JobRepository().list(owner="alice", run_id=response.get_json()["run_id"], limit=20)
    assert {job.kind for job in jobs} == {
        "ic", "factor_evaluation", "factor_type_analysis", "backtest",
    }
    assert all(":run_" in job.runner_path for job in jobs)
    assert all(job.summary()["execution_mode"] == "process" for job in jobs)
    assert all("page_uuid" not in job.job_spec and "view_uuid" not in job.job_spec for job in jobs)


def test_submission_snapshots_server_side_scheduling_entitlement(client, monkeypatch) -> None:
    workspace = _create_workspace(client)
    _update(client, workspace, _payload(workspace))
    monkeypatch.setattr(
        "server.modules.single_factor_test.research_jobs.entitlement_for_owner",
        lambda owner: SchedulingEntitlement(
            priority_class="high", weight=2.0,
            reserved_capacity_class="research-admin", max_concurrency=2,
        ),
    )

    response = client.post("/api/runs", json={
        "workspace_id": workspace["workspace_id"],
        "configuration_revision": workspace["configuration"]["revision"],
        "analyses": ["ic"],
        "entitlement": {"priority_class": "admin", "weight": 999},
    })

    assert response.status_code == 202
    job = JobRepository().list(owner="alice", run_id=response.get_json()["run_id"])[0]
    assert job.entitlement.priority_class == "high"
    assert job.entitlement.weight == 2.0
    assert job.entitlement.max_concurrency == 2


def test_run_freezes_owner_product_group_paths_before_worker_submit(client, monkeypatch) -> None:
    workspace = _create_workspace(client)
    payload = _payload(workspace)
    backtest = payload["analyses"]["backtest"]
    backtest["product_selections"] = {}
    backtest["groups"][0]["product_path_selection"] = {
        "product_path_selection_id": "owner-group",
    }
    _update(client, workspace, payload)
    monkeypatch.setattr(
        "server.modules.products.product_group_store.load_product_groups",
        lambda owner: [{"id": "owner-group", "name": "Owner group", "paths": ["core8_path"]}],
    )
    response = client.post("/api/runs", json={
        "workspace_id": workspace["workspace_id"],
        "configuration_revision": workspace["configuration"]["revision"],
        "analyses": ["backtest"],
    })

    assert response.status_code == 202, response.get_data(as_text=True)
    jobs = JobRepository().list(owner="alice", run_id=response.get_json()["run_id"])
    frozen = jobs[0].job_spec["product_selections"]["owner-group"]
    assert frozen["selected_paths"] == ["core8_path"]
    assert frozen["product_group_template_id"] == "owner-group"
    run = response.get_json()["run"]
    assert run["run_spec"]["configuration"]["analyses"]["backtest"]["product_selections"]["owner-group"] == frozen


def test_run_rejects_unresolvable_product_selection_before_creating_job(client, monkeypatch) -> None:
    workspace = _create_workspace(client)
    payload = _payload(workspace)
    backtest = payload["analyses"]["backtest"]
    backtest["product_selections"] = {}
    backtest["groups"][0]["product_path_selection"] = {
        "product_path_selection_id": "missing-group",
    }
    _update(client, workspace, payload)
    monkeypatch.setattr(
        "server.modules.products.product_group_store.load_product_groups", lambda owner: [],
    )

    response = client.post("/api/runs", json={
        "workspace_id": workspace["workspace_id"],
        "configuration_revision": workspace["configuration"]["revision"],
        "analyses": ["backtest"],
    })

    assert response.status_code == 400
    assert "missing-group" in response.get_json()["error"]
    assert JobRepository().list(owner="alice", workspace_id=workspace["workspace_id"]) == []


def test_view_lifecycle_is_not_a_research_job_api(client) -> None:
    workspace = _create_workspace(client)
    response = client.post("/api/view-leases", json={
        "view_uuid": "view-a", "workspace_id": workspace["workspace_id"],
    })
    assert response.status_code == 404
