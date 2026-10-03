from __future__ import annotations

import json
import hashlib

import pytest
from flask import Flask

import server.modules.shared.submission_helpers  # noqa: F401 - injects product resolver
import settings as Settings
from server.jobs.models import SchedulingEntitlement
from server.jobs.repository import JobRepository
from server.modules.single_factor_test import research_jobs, sft_bp
from server.services import (
    factor_registry,
    research_configuration_snapshots,
    research_configurations,
    research_runs,
    research_workspaces,
)
from server.services.factor_revisions import _load_revision_definition
from tests.server.trial_plan_fixtures import trial_plan
from tools.data.sqlite.db import connect_sqlite
from tools.factors.factor_set_identity import freeze_factor_set_identity
from tools.factors.alias_validator import factor_formula_identity
from tools.factors.formula_identity import freeze_factor_identity


def test_grouped_ic_http_run_lifecycle_preserves_typed_provenance_and_hash(
    client, monkeypatch, tmp_path,
) -> None:
    """The grouped IC contract stays immutable across preview, submit, and retry."""
    workspace = _create_workspace(client)
    payload = _payload(workspace)
    shared = payload["shared"]
    factor = _frozen_factor("MmRet|$F:5m")
    shared["factors"] = [factor]
    shared["temporary_objects"] = {
        "product_selections": [{
            "id": "product-scope:core8", "selected_paths": ["/canonical/products/core8"],
            "products": ["core8"],
        }],
    }
    payload["analyses"]["ic"] = {
        "schema_version": 2,
        "execution": {"settings": {}},
        "configuration_groups": [{
            "config_group_id": "cg-alpha",
            "product_scope_ref": "product-scope:core8",
            "factor_ref": factor["ref"],
            "horizon": {"sampling": "scale_aware"},
            "entry_delay_bars": 1,
            "methods": ["rank"],
            "return_price_basis": "next_open_to_open_adjusted",
        }],
    }
    _update(client, workspace, payload)
    request_payload = {
        "workspace_id": workspace["workspace_id"],
        "configuration_revision": workspace["configuration"]["revision"],
        "analyses": ["ic"],
        "retention_mode": "full",
    }
    preview = client.post("/api/runs/preview", json=request_payload)
    assert preview.status_code == 200, preview.get_data(as_text=True)
    preview_json = preview.get_json()
    submitted = client.post("/api/runs", json=request_payload)
    assert submitted.status_code == 202, submitted.get_data(as_text=True)
    submitted_json = submitted.get_json()
    assert submitted_json["run"]["run_spec_hash"] == preview_json["run_spec_hash"]
    assert len(submitted_json["jobs"]) == 1
    job = JobRepository().require(submitted_json["jobs"][0]["job_id"], owner="alice")
    typed = job.job_spec["run_spec"]["typed_ic"]
    assert typed["group_provenance"][0]["config_group_id"] == "cg-alpha"
    assert typed["group_provenance"][0]["core_ref"].startswith("ic-core-request:v1:")
    core_request = typed["authoring_core_tests"][0]
    frozen_horizons = typed["resolved_horizons_by_request"][
        core_request["request_ref"]
    ][core_request["factor_refs"][0]]
    assert len(frozen_horizons) > 1
    from server.modules.single_factor_test.process_runners import (
        _typed_ic_execution_payload,
    )
    projected = _typed_ic_execution_payload(job.job_spec)
    assert projected["forward_return_horizons"]["bases"] == [
        item["physical_frequency"] for item in frozen_horizons
    ]
    assert job.job_spec["product_selections"]["product-scope:core8"]["paths"] == [
        "/canonical/products/core8"
    ]
    assert job.job_spec["execution_plan"]["kind"] == "ic"

    called = []
    from server.modules.single_factor_test import ic
    monkeypatch.setattr(ic, "selection_from_request", lambda *a, **k: called.append(1))
    repository = JobRepository()
    repository.transition(job.job_id, "failed", expected="submitted", error={"code": "test"})
    retry = client.post(f"/api/jobs/{job.job_id}/retry")
    assert retry.status_code == 202, retry.get_data(as_text=True)
    retried = repository.require(retry.get_json()["job_id"], owner="alice")
    assert retried.job_spec["run_spec"]["typed_ic"] == typed
    assert called == []


def test_grouped_ic_scale_aware_horizon_uses_omitted_default_signal_frequency(
    client,
) -> None:
    workspace = _create_workspace(client)
    payload = _payload(workspace)
    factor = _frozen_factor("MmRet")
    payload["shared"]["factors"] = [factor]
    payload["shared"]["temporary_objects"] = {
        "product_selections": [{
            "id": "product-scope:daily",
            "selected_paths": ["/canonical/products/daily"],
            "products": ["daily"],
        }],
    }
    payload["analyses"]["ic"] = {
        "schema_version": 2,
        "execution": {"settings": {}},
        "configuration_groups": [{
            "config_group_id": "cg-daily",
            "product_scope_ref": "product-scope:daily",
            "factor_ref": factor["ref"],
            "horizon": {"sampling": "scale_aware"},
            "entry_delay_bars": 1,
            "methods": ["rank"],
            "return_price_basis": "next_open_to_open_adjusted",
        }],
    }
    _update(client, workspace, payload)

    response = client.post("/api/runs/preview", json={
        "workspace_id": workspace["workspace_id"],
        "configuration_revision": workspace["configuration"]["revision"],
        "analyses": ["ic"],
    })

    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.get_json()["run_spec_hash"]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # These lifecycle fixtures use synthetic product identities. Real category
    # expansion and membership drift are covered by test_product_scope_snapshot.
    monkeypatch.setattr(
        "server.modules.products.product_category_paths.resolve_product_scope_paths",
        lambda paths, **kwargs: sorted(set(paths)),
    )
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "research-jobs.sqlite")
    factor_sources = {
        family: f"""
from tools.data.types import DataColumn
from tools.factors import FactorFamily
from tools.factors.FactorExpr import ColumnRef

class {family}(FactorFamily):
    @staticmethod
    def factor_expr():
        return ColumnRef(DataColumn.CLOSE)
"""
        for family in ("MmRet", "MmMADevRat")
    }
    monkeypatch.setattr(
        factor_registry,
        "load_public_factor_source",
        lambda factor_id: factor_sources.get(str(factor_id)),
    )
    # These lifecycle tests exercise freezing, retention, and retry behavior.
    # Capability resolution has its own focused tests and needs a real product
    # catalog/date range, so keep this fixture's planner deterministic.
    monkeypatch.setattr(
        research_jobs,
        "_capability_plans",
        lambda prepared, owner: [
            {"kind": kind, "resolved": {"data_requirements": []}}
            for kind in prepared["analyses"]
        ],
    )
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = "alice"
    return client


def _create_workspace(client):
    aliases = [
        "MmRet|$F:1d",
        "MmMADevRat|$F:1d|$Rev",
    ]
    response = client.post("/api/test-authoring/workspaces", json={
        "title": "multi factor research",
        "factors": [_frozen_factor(alias) for alias in aliases],
    })
    assert response.status_code == 201
    return response.get_json()["workspace"]


def _payload(workspace, *, n: str = "10d"):
    shared = dict(workspace["configuration"]["payload"]["shared"])
    shared["user_defined_shared_setting"] = {"enabled": True, "threshold": 1.25}
    return {
        "schema_version": 3,
        "shared": shared,
        "analyses": {
            "ic": {
                "execution": {"settings": {}},
                "factor_configs": [{"N": n}], "product_paths": ["core8_path"],
            },
            "backtest": {
                "execution": {"settings": {"user_defined_local_setting": "kept"}},
                "groups": [{
                    "id": "A1", "name": "A1", "splitCount": 5, "groupIndex": 1,
                    "factorAlias": "MmRet|$F:1d",
                    "product_path_selection_id": "core8",
                    "user_defined_group_setting": {"mode": "custom"},
                }],
                "ls_configs": [{
                    "id": "LS1", "longGroupId": "A1", "shortGroupId": "A5",
                    "user_defined_ls_setting": [1, 2, 3],
                }],
                "product_selections": {"core8": {"id": "core8", "selected_paths": ["core8_path"]}},
            },
            "factor_evaluation": {
                "execution": {"settings": {}}, "factor_alias": "MmRet|$F:1d",
            },
            "factor_type_analysis": {
                "execution": {"settings": {}}, "factor_alias": "MmRet|$F:1d",
            },
        },
        "ui": {"selected_tab": "ic"},
    }


def _update(client, workspace, payload):
    response = client.put(
        f"/api/test-authoring/workspaces/{workspace['workspace_id']}/configuration",
        json={
            "expected_revision": workspace["configuration"]["revision"],
            "payload": payload,
        },
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    workspace["configuration"] = response.get_json()["configuration"]
    return workspace


def _frozen_factor(alias: str) -> dict:
    family_alias = alias.split("|", 1)[0]
    definition = _load_revision_definition(
        family_ref=f"public:{family_alias}",
        factor_aliases=[alias],
        owner="alice",
    )
    resolved = definition["resolved_factors"][0]
    return freeze_factor_identity(
        owner_ref="public",
        family_alias=family_alias,
        factor_alias=alias,
        family_formula_fingerprint=definition["family_formula_fingerprint"],
        self_formula_fingerprint=resolved["self_formula_fingerprint"],
        params=resolved["params"],
    )


@pytest.mark.parametrize("route", ["/api/runs/preview", "/api/runs"])
def test_mounted_time_tab_rejects_blank_window_before_run_creation(
    client, route,
) -> None:
    workspace = _create_workspace(client)
    payload = _payload(workspace)
    payload["ui"]["ic"] = {"mounted_tabs": ["test_template", "time"]}
    payload["analyses"]["ic"]["execution"]["settings"].update({
        "start_date": "",
        "end_date": "",
    })
    _update(client, workspace, payload)

    response = client.post(route, json={
        "workspace_id": workspace["workspace_id"],
        "configuration_revision": workspace["configuration"]["revision"],
        "analyses": ["ic"],
    })

    assert response.status_code == 422
    assert response.get_json()["code"] == "invalid_run_window"
    assert "start_date, end_date" in response.get_json()["error"]
    assert JobRepository().count_with_metadata(owner="alice") == 0


def _factor_set_descriptor(*aliases: str) -> dict:
    manifest = freeze_factor_set_identity(
        owner_ref="profile:maxa",
        set_id="run-subjects",
        alias="本次运行因子集合",
        members=[_frozen_factor(alias) for alias in aliases],
    )
    return {
        "target_ref": manifest["ref"],
        "manifest": manifest,
    }


def _inline_factor(tmp_path, source: str, alias: str) -> dict:
    source_file = tmp_path / f"{alias.split('|', 1)[0]}.py"
    source_file.write_text(source, encoding="utf-8")
    formula = factor_formula_identity(
        source_file=source_file,
        identity=alias,
        object_kind="factor",
        blob_hash=hashlib.sha256(source.encode()).hexdigest(),
    )
    return freeze_factor_identity(
        owner_ref="alice",
        family_alias=alias.split("|", 1)[0],
        factor_alias=formula["canonical_identity"],
        family_formula_fingerprint=formula["family_formula_fingerprint"],
        self_formula_fingerprint=formula["self_formula_fingerprint"],
        params=formula["params"],
    )


def test_workspace_has_one_mutable_configuration_not_revision_history(client) -> None:
    workspace = _create_workspace(client)
    _update(client, workspace, _payload(workspace))
    _update(client, workspace, _payload(workspace, n="20d"))

    reopened = client.get(f"/api/test-authoring/workspaces/{workspace['workspace_id']}").get_json()["workspace"]

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
        f"/api/test-authoring/workspaces/{workspace['workspace_id']}/configuration/templates",
        json={"name": "Core 8 template"},
    )
    template = saved.get_json()["template"]

    _update(client, workspace, _payload(workspace, n="20d"))
    loaded = client.post(
        f"/api/test-authoring/workspaces/{workspace['workspace_id']}/configuration/load-template",
        json={
            "configuration_id": template["configuration_id"],
            "expected_revision": workspace["configuration"]["revision"],
        },
    )
    value = loaded.get_json()["configuration"]

    assert saved.status_code == 201
    assert value["payload"] == template["payload"]
    assert value["payload"]["shared"]["user_defined_shared_setting"]["threshold"] == 1.25
    assert value["payload"]["analyses"]["backtest"]["execution"]["settings"]["user_defined_local_setting"] == "kept"
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
                "factor": "MmRet|$F:1d",
                "factor_candidates": [{"alias": "MmRet|$F:1d"}],
            "submissions": [{"id": "selection-1", "selected_paths": ["core8_path"]}],
            "group_settings": {"groups": [{
                "id": "A1", "testerId": "selection-1", "groupCount": 5,
                    "groupIndex": 0, "factorAlias": "MmRet|$F:1d",
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
    alias = "MmRet|$F:1d"
    assert "factor_families" not in templates[0]["payload"]["shared"]
    factor = templates[0]["payload"]["shared"]["factors"][0]
    assert factor["alias"] == alias
    assert factor["ref"].startswith("factor:v2:")
    assert templates[0]["payload"]["analyses"]["backtest"]["groups"][0]["splitCount"] == 5
    migrated_backtest = templates[0]["payload"]["analyses"]["backtest"]
    assert "factor" not in migrated_backtest and "factor_candidates" not in migrated_backtest
    assert "factor" not in migrated_backtest["execution"]["settings"]
    assert "factor_candidates" not in migrated_backtest["execution"]["settings"]
    assert migrated_backtest["groups"][0]["factor_candidate_refs"] == [
        factor["ref"],
    ]


def test_legacy_workspace_and_runs_require_then_apply_one_time_migration(client) -> None:
    draft = {
        "factor_alias": "MmRet|$F:1d",
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


def test_unsubmitted_workspace_can_be_deleted_without_touching_other_tabs(client) -> None:
    first = _create_workspace(client)
    second = _create_workspace(client)

    response = client.delete(f"/api/test-authoring/workspaces/{first['workspace_id']}")

    assert response.status_code == 200
    assert response.get_json()["deleted"] is True
    assert client.get(f"/api/test-authoring/workspaces/{first['workspace_id']}").status_code == 404
    assert client.get(f"/api/test-authoring/workspaces/{second['workspace_id']}").status_code == 200


def test_workspace_delete_preserves_immutable_snapshot_evidence(client) -> None:
    workspace = _create_workspace(client)
    configuration = workspace["configuration"]
    snapshot = client.post(
        f"/api/test-authoring/workspaces/{workspace['workspace_id']}/configuration-snapshots",
        json={
            "source_workspace_id": workspace["workspace_id"],
            "source_configuration_id": configuration["configuration_id"],
            "source_configuration_revision": configuration["revision"],
            "name": "frozen preview",
        },
    )
    assert snapshot.status_code == 201

    response = client.delete(f"/api/test-authoring/workspaces/{workspace['workspace_id']}")

    assert response.status_code == 200
    assert response.get_json() == {"success": True, "deleted": True}
    assert client.get(f"/api/test-authoring/workspaces/{workspace['workspace_id']}").status_code == 404
    snapshots = research_configuration_snapshots.list_snapshots(
        owner="alice", workspace_id=workspace["workspace_id"],
    )
    assert len(snapshots) == 1
    assert snapshots[0]["name"] == "frozen preview"


def test_run_preview_matches_submission_without_persisting(client, monkeypatch) -> None:
    workspace = _create_workspace(client)
    payload = _payload(workspace)
    payload["analyses"]["backtest"]["execution"]["settings"].update({
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
    })
    _update(client, workspace, payload)
    planned_hashes = []

    def plan(prepared, owner):
        planned_hashes.append(research_runs.hash_run_spec(prepared["run_spec"]))
        return [
            {"kind": kind, "resolved": {"data_requirements": []}}
            for kind in prepared["analyses"]
        ]

    monkeypatch.setattr(
        research_jobs,
        "_capability_plans",
        plan,
    )
    request_payload = {
        "workspace_id": workspace["workspace_id"],
        "configuration_revision": workspace["configuration"]["revision"],
        "analyses": ["ic", "backtest"],
        "retention_mode": "summary",
        "step_mode": False,
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
    }

    preview = client.post(
        "/api/runs/preview",
        json=request_payload,
    )

    assert preview.status_code == 200, preview.get_data(as_text=True)
    preview_payload = preview.get_json()
    assert preview_payload["success"] is True
    assert len(preview_payload["run_spec_hash"]) == 64
    assert preview_payload["run_spec_version"] == 4
    assert preview_payload["frozen_factors"]
    assert all(
        "source_code" not in manifest
        and "tree_repr" not in manifest
        and "math_expr" not in manifest
        for manifest in preview_payload["frozen_factors"]
    )
    assert JobRepository().list(owner="alice") == []
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        assert conn.execute(
            """
            SELECT COUNT(*) FROM sqlite_master
            WHERE type='table' AND name='research_runs'
            """
        ).fetchone()[0] == 0

    submitted = client.post("/api/runs", json=request_payload)

    assert submitted.status_code == 202, submitted.get_data(as_text=True)
    run = submitted.get_json()["run"]
    assert preview_payload["run_spec_hash"] == run["run_spec_hash"]
    assert preview_payload["frozen_factors"] == (
        run["run_spec"]["configuration"]["shared"]["factors"]
    )
    assert preview_payload["configuration_fingerprint"] == (
        run["run_spec"]["configuration_fingerprint"]
    )
    assert planned_hashes == [
        preview_payload["run_spec_hash"], preview_payload["run_spec_hash"],
    ]
    jobs = JobRepository().list(owner="alice", run_id=run["run_id"])
    assert {job.kind for job in jobs} == {"ic", "backtest"}
    for job in jobs:
        assert job.run_spec_hash == run["run_spec_hash"]
        assert job.job_spec["run_spec"] == run["run_spec"]


def test_run_capability_preview_is_read_only(client, monkeypatch) -> None:
    workspace = _create_workspace(client)
    payload = _payload(workspace)
    payload["analyses"]["backtest"]["execution"]["settings"].update({
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
    })
    _update(client, workspace, payload)
    monkeypatch.setattr(
        research_jobs,
        "_capability_plans",
        lambda _prepared, owner: [{
            "kind": "backtest",
            "resolved": {
                "data_requirements": [{
                    "product": "AG.SHF",
                    "frequency": "DAY1",
                    "data_source": "Local",
                }],
            },
            "resolved_hash": "plan-hash",
            "notices": [],
        }],
    )
    response = client.post("/api/runs/capability-preview", json={
        "workspace_id": workspace["workspace_id"],
        "configuration_revision": workspace["configuration"]["revision"],
        "analyses": ["backtest"],
    })

    assert response.status_code == 200, response.get_data(as_text=True)
    value = response.get_json()
    assert value["success"] is True
    assert value["capability"] is True
    assert value["data_requirements"]
    assert value["plans"][0]["kind"] == "backtest"
    assert JobRepository().list(owner="alice") == []


def test_run_capability_preview_accepts_origin_manager_frozen_context(
    client, monkeypatch,
) -> None:
    workspace = _create_workspace(client)
    _update(client, workspace, _payload(workspace))
    request_payload = {
        "workspace_id": workspace["workspace_id"],
        "configuration_revision": workspace["configuration"]["revision"],
        "analyses": ["ic"],
    }
    context = research_jobs.prepare_manager_run_context(
        request_payload, owner="alice",
    )
    monkeypatch.setattr(
        research_configurations,
        "load_workspace_configuration",
        lambda **_values: pytest.fail(
            "the executor must not load the origin workspace database"
        ),
    )
    monkeypatch.setattr(
        research_jobs,
        "_capability_plans",
        lambda _prepared, owner: [{
            "kind": "ic",
            "resolved": {"data_requirements": []},
            "resolved_hash": "portable-plan",
            "notices": [],
        }],
    )

    response = client.post("/api/runs/capability-preview", json={
        **request_payload,
        research_jobs.MANAGER_RUN_CONTEXT_KEY: context,
    })

    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.get_json()["plans"][0]["resolved_hash"] == "portable-plan"
    assert JobRepository().list(owner="alice") == []


def test_frozen_manager_context_carries_canonical_factor_source_to_executor(
    client, monkeypatch,
) -> None:
    workspace = _create_workspace(client)
    _update(client, workspace, _payload(workspace))
    request_payload = {
        "workspace_id": workspace["workspace_id"],
        "configuration_revision": workspace["configuration"]["revision"],
        "analyses": ["ic"],
    }
    context = research_jobs.prepare_manager_run_context(
        request_payload, owner="alice",
    )

    # The executor deliberately has no local canonical source registry.  It
    # must use the exact source frozen by the origin Manager for this Run.
    monkeypatch.setattr(
        factor_registry,
        "load_public_factor_source",
        lambda _factor_id: None,
    )

    response = client.post("/api/runs/capability-preview", json={
        **request_payload,
        research_jobs.MANAGER_RUN_CONTEXT_KEY: context,
    })

    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.get_json()["capability"] is True


def test_frozen_manager_context_rejects_tampered_factor_source(client) -> None:
    workspace = _create_workspace(client)
    _update(client, workspace, _payload(workspace))
    request_payload = {
        "workspace_id": workspace["workspace_id"],
        "configuration_revision": workspace["configuration"]["revision"],
        "analyses": ["ic"],
    }
    context = research_jobs.prepare_manager_run_context(
        request_payload, owner="alice",
    )
    sources = context["prepared"]["portable_factor_sources"]
    assert sources
    sources[0]["source_code"] = sources[0]["source_code"].replace(
        "DataColumn.CLOSE", "DataColumn.OPEN",
    )

    response = client.post("/api/runs/capability-preview", json={
        **request_payload,
        research_jobs.MANAGER_RUN_CONTEXT_KEY: context,
    })

    assert response.status_code == 400
    assert response.get_json()["code"] == "invalid_manager_run_context"


def test_run_submission_accepts_origin_manager_frozen_context(
    client, monkeypatch,
) -> None:
    workspace = _create_workspace(client)
    _update(client, workspace, _payload(workspace))
    request_payload = {
        "workspace_id": workspace["workspace_id"],
        "configuration_revision": workspace["configuration"]["revision"],
        "analyses": ["ic"],
        "task_name": "federated IC smoke",
    }
    context = research_jobs.prepare_manager_run_context(
        request_payload, owner="alice",
    )
    monkeypatch.setattr(
        research_configurations,
        "load_workspace_configuration",
        lambda **_values: pytest.fail(
            "the executor must not load the origin workspace database"
        ),
    )

    response = client.post("/api/runs", json={
        **request_payload,
        research_jobs.MANAGER_RUN_CONTEXT_KEY: context,
    })

    assert response.status_code == 202, response.get_data(as_text=True)
    value = response.get_json()
    assert value["run"]["run_spec_hash"] == context["run_spec_hash"]
    jobs = JobRepository().list(owner="alice", run_id=value["run_id"])
    assert len(jobs) == 1
    assert jobs[0].summary()["task_name"] == "federated IC smoke"


def test_frozen_manager_context_persists_source_for_remote_execution(
    client, monkeypatch,
) -> None:
    workspace = _create_workspace(client)
    _update(client, workspace, _payload(workspace))
    request_payload = {
        "workspace_id": workspace["workspace_id"],
        "configuration_revision": workspace["configuration"]["revision"],
        "analyses": ["ic"],
        "task_name": "portable source IC",
    }
    context = research_jobs.prepare_manager_run_context(
        request_payload, owner="alice",
    )
    monkeypatch.setattr(
        factor_registry,
        "load_public_factor_source",
        lambda _factor_id: None,
    )

    response = client.post("/api/runs", json={
        **request_payload,
        research_jobs.MANAGER_RUN_CONTEXT_KEY: context,
    })

    assert response.status_code == 202, response.get_data(as_text=True)
    job = JobRepository().list(
        owner="alice", run_id=response.get_json()["run_id"],
    )[0]
    assert job.summary()["factor_source_policy"]["scope_status"] == "available"
    scope_id = str(job.job_spec["transient_factor_source_scope_id"])
    with factor_registry.transient_factor_source_scope(
        scope_id, owner="alice",
    ):
        source = factor_registry.resolve_factor_family_source(
            "public:MmRet", username="alice",
        )
    assert source["canonical_family_ref"] == "public:MmRet"
    assert "class MmRet" in source["source_code"]
    retained = [
        item for item in JobRepository().list_artifacts(
            job_id=job.job_id, owner="alice",
        )
        if item["artifact_kind"] == "factor_source"
    ]
    assert len(retained) == 2

    repository = JobRepository()
    repository.transition(job.job_id, "planning")
    repository.transition(
        job.job_id,
        "failed",
        expected="planning",
        error={"code": "retry_portable_source", "message": "test retry"},
    )
    retry = client.post(f"/api/jobs/{job.job_id}/retry")
    assert retry.status_code == 202, retry.get_data(as_text=True)
    retried = repository.require(retry.get_json()["job_id"], owner="alice")
    with factor_registry.transient_factor_source_scope(
        str(retried.job_spec["transient_factor_source_scope_id"]),
        owner="alice",
    ):
        retried_source = factor_registry.resolve_factor_family_source(
            "public:MmRet", username="alice",
        )
    assert "class MmRet" in retried_source["source_code"]


def test_manager_run_context_rejects_tampered_runspec(client) -> None:
    workspace = _create_workspace(client)
    _update(client, workspace, _payload(workspace))
    request_payload = {
        "workspace_id": workspace["workspace_id"],
        "configuration_revision": workspace["configuration"]["revision"],
        "analyses": ["ic"],
    }
    context = research_jobs.prepare_manager_run_context(
        request_payload, owner="alice",
    )
    context["prepared"]["run_spec"]["workspace_id"] = "tampered"

    response = client.post("/api/runs/capability-preview", json={
        **request_payload,
        research_jobs.MANAGER_RUN_CONTEXT_KEY: context,
    })

    assert response.status_code == 400
    assert response.get_json()["code"] == "invalid_manager_run_context"


def test_explicit_empty_outputs_do_not_restore_ic_defaults(client) -> None:
    workspace = _create_workspace(client)
    _update(client, workspace, _payload(workspace))
    request_payload = {
        "workspace_id": workspace["workspace_id"],
        "configuration_revision": workspace["configuration"]["revision"],
        "analyses": ["ic"],
    }

    implicit = client.post("/api/runs/preview", json=request_payload)
    explicit = client.post("/api/runs/preview", json={
        **request_payload, "output_requests": [],
    })

    assert implicit.status_code == 200
    assert implicit.get_json()["output_requests"] == [
        "ic_series", "ic_statistics", "ic_holding_half_life",
    ]
    assert explicit.status_code == 200
    assert explicit.get_json()["output_requests"] == []


def test_performance_profile_is_job_telemetry_not_run_spec_identity(client) -> None:
    workspace = _create_workspace(client)
    _update(client, workspace, _payload(workspace))
    request_payload = {
        "workspace_id": workspace["workspace_id"],
        "configuration_revision": workspace["configuration"]["revision"],
        "analyses": ["ic", "backtest"],
    }
    base = client.post("/api/runs/preview", json=request_payload).get_json()
    profiled = client.post("/api/runs/preview", json={
        **request_payload,
        "performance_profile": {
            "kind": "cumulative_flow",
            "min_total_ms": 25,
        },
    }).get_json()

    assert profiled["run_spec_hash"] == base["run_spec_hash"]
    assert profiled["performance_profile"] == {
        "kind": "cumulative_flow",
        "min_total_ms": 25.0,
    }

    response = client.post("/api/runs", json={
        **request_payload,
        "performance_profile": profiled["performance_profile"],
    })
    assert response.status_code == 202, response.get_data(as_text=True)
    jobs = JobRepository().list(owner="alice")
    backtest = next(job for job in jobs if job.kind == "backtest")
    ic = next(job for job in jobs if job.kind == "ic")
    assert backtest.job_spec["performance_profile"] == profiled[
        "performance_profile"
    ]
    assert "performance_profile" not in ic.job_spec


def test_margin_execution_profile_is_opt_in_backtest_telemetry(client) -> None:
    workspace = _create_workspace(client)
    _update(client, workspace, _payload(workspace))
    request_payload = {
        "workspace_id": workspace["workspace_id"],
        "configuration_revision": workspace["configuration"]["revision"],
        "analyses": ["ic", "backtest"],
    }
    base = client.post("/api/runs/preview", json=request_payload).get_json()
    profiled = client.post("/api/runs/preview", json={
        **request_payload,
        "margin_execution_profile": {"kind": "cumulative"},
    }).get_json()

    assert profiled["run_spec_hash"] == base["run_spec_hash"]
    assert profiled["margin_execution_profile"] == {
        "kind": "cumulative",
        "min_total_ms": 0.0,
    }

    response = client.post("/api/runs", json={
        **request_payload,
        "margin_execution_profile": profiled["margin_execution_profile"],
    })
    assert response.status_code == 202, response.get_data(as_text=True)
    jobs = JobRepository().list(owner="alice")
    backtest = next(job for job in jobs if job.kind == "backtest")
    ic = next(job for job in jobs if job.kind == "ic")
    assert backtest.job_spec["margin_execution_profile"] == profiled[
        "margin_execution_profile"
    ]
    assert "margin_execution_profile" not in ic.job_spec


def test_registered_direct_trial_plan_submits_as_a_run_contract(client) -> None:
    workspace = _create_workspace(client)
    _update(client, workspace, _payload(workspace))
    request_payload = {
        "workspace_id": workspace["workspace_id"],
        "configuration_revision": workspace["configuration"]["revision"],
        "analyses": ["ic"],
    }
    preview = client.post("/api/runs/preview", json=request_payload).get_json()
    frozen = client.post("/api/trial-plans/direct", json={
        "trial_plan": trial_plan(preview["run_spec_hash"]),
        "run_spec_hash": preview["run_spec_hash"],
        "trial_role": "selection",
        "comparison_id": "main-comparison",
    })
    assert frozen.status_code == 200, frozen.get_data(as_text=True)

    submitted = client.post("/api/runs", json={
        **request_payload,
        "trial_binding": frozen.get_json()["trial_binding"],
    })

    assert submitted.status_code == 202, submitted.get_data(as_text=True)
    run = submitted.get_json()["run"]
    assert run["trial_plan_hash"] == frozen.get_json()["trial_binding"][
        "trial_plan_hash"
    ]
    assert not any("graph" in key for key in run)


def test_run_spec_freezes_one_exact_multi_factor_set_subject(client) -> None:
    workspace = _create_workspace(client)
    _update(client, workspace, _payload(workspace))
    descriptor = _factor_set_descriptor(
        "MmRet|$F:1d",
        "MmMADevRat|$F:1d|$Rev",
    )

    response = client.post("/api/runs/preview", json={
        "workspace_id": workspace["workspace_id"],
        "configuration_revision": workspace["configuration"]["revision"],
        "analyses": ["ic", "backtest"],
        "factor_subject_descriptors": [descriptor],
    })

    assert response.status_code == 200, response.get_data(as_text=True)
    payload = response.get_json()
    assert payload["factor_subject_descriptors"] == [{
        "target_ref": descriptor["target_ref"],
        "member_fingerprint": descriptor["manifest"]["identity"][
            "member_fingerprint"
        ],
        "member_count": 2,
        "authority": "formula_manifest",
    }]


def test_preview_freezes_transient_profile_screen_without_shared_registration(
    client, monkeypatch, tmp_path,
) -> None:
    workspace = _create_workspace(client)
    payload = _payload(workspace)
    source = '''
from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam

class ProfileScreen(FactorFamily):
    source_freq = "1m"

    @staticmethod
    def factor_expr():
        return DataColumnParam("TO", default_value="TO").rolling_mean(
            WindowParam("N", default_value="20d")
        ).cs_ordinal_rank(ascending=False)
'''
    factor = _inline_factor(tmp_path, source, "ProfileScreen|N:20d")
    payload["analyses"]["backtest"]["execution"]["settings"].update({
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
    })
    payload["shared"]["factors"].append(factor)
    payload["analyses"]["backtest"]["groups"][0]["factor_candidate_refs"] = [
        factor["ref"]
    ]
    payload["analyses"]["backtest"]["groups"][0]["factorRoleBindings"] = {
        "screen": factor["ref"],
    }
    payload["analyses"]["backtest"]["groups"][0]["screen_rule"] = "lte"
    payload["analyses"]["backtest"]["groups"][0]["screen_upper"] = 12
    _update(client, workspace, payload)
    monkeypatch.setattr(
        research_jobs,
        "_capability_plans",
        lambda prepared, owner: [
            {"kind": kind, "resolved": {"data_requirements": []}}
            for kind in prepared["analyses"]
        ],
    )
    response = client.post("/api/runs/preview", json={
        "workspace_id": workspace["workspace_id"],
        "configuration_revision": workspace["configuration"]["revision"],
        "analyses": ["backtest"],
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
        "transient_factor_sources": [{
            "path": "custom_factors/ProfileScreen.py",
            "source_code": source,
        }],
    })

    assert response.status_code == 200, response.get_data(as_text=True)
    preview = response.get_json()
    policy = preview["factor_source_policy"]
    assert policy["mode"] == "transient_run_source"
    assert policy["files"][0]["factor_id"] == "ProfileScreen"
    assert len(policy["files"][0]["source_sha256"]) == 64
    assert "source_code" not in policy["files"][0]
    assert source not in json.dumps(preview)
    configuration = client.get(
        f"/api/test-authoring/workspaces/{workspace['workspace_id']}/configuration"
    ).get_json()["configuration"]["payload"]
    assert any(
        item.get("ref") == factor["ref"]
        for item in configuration["shared"]["factors"]
    )


def test_submitted_transient_factor_source_is_retained_as_job_input_artifact(
    client,
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("GTHT_JOB_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    source = '''
from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam

class ProfileScreen(FactorFamily):
    desc = "临时筛选因子"
    source_freq = "1m"

    @staticmethod
    def factor_expr():
        return DataColumnParam("TO", default_value="TO").rolling_mean(
            WindowParam("N", default_value="20d")
        ).cs_ordinal_rank(ascending=False)
'''
    factor = _inline_factor(tmp_path, source, "ProfileScreen|N:20d")
    created = client.post("/api/test-authoring/workspaces", json={
        "title": "transient factor inputs",
        "factor_families": [{"alias": "ProfileScreen"}],
        "factors": [factor],
    })
    assert created.status_code == 201
    workspace = created.get_json()["workspace"]
    payload = _payload(workspace)
    payload["analyses"]["backtest"]["groups"][0]["factor_candidate_refs"] = [
        factor["ref"]
    ]
    payload["analyses"]["backtest"]["groups"][0]["factorRoleBindings"] = {
        "screen": factor["ref"],
    }
    payload["analyses"]["backtest"]["groups"][0]["screen_rule"] = "lte"
    payload["analyses"]["backtest"]["groups"][0]["screen_upper"] = 12
    _update(client, workspace, payload)
    response = client.post("/api/runs", json={
        "workspace_id": workspace["workspace_id"],
        "configuration_revision": workspace["configuration"]["revision"],
        "analyses": ["backtest"],
        "transient_factor_sources": [{
            "path": "custom_factors/ProfileScreen.py",
            "source_code": source,
        }],
    })

    assert response.status_code == 202, response.get_data(as_text=True)
    job = JobRepository().list(
        owner="alice", run_id=response.get_json()["run_id"],
    )[0]
    source_artifact = JobRepository().load_artifact(
        job_id=job.job_id,
        name="factor_source__ProfileScreen",
        owner="alice",
    )
    assert source_artifact is not None
    assert source_artifact["content_type"] == "text/x-python"
    assert source_artifact["state"] == "active"
    assert (
        tmp_path / "artifacts" / source_artifact["relative_path"]
    ).read_text(encoding="utf-8") == source

    repository = JobRepository()
    assert job.summary()["factor_source_policy"]["scope_status"] == "available"
    repository.transition(job.job_id, "planning")
    repository.transition(
        job.job_id,
        "failed",
        expected="planning",
        error={"code": "test_failure", "message": "terminal cleanup"},
    )
    terminal = repository.require(job.job_id, owner="alice")
    assert terminal.summary()["factor_source_policy"]["scope_status"] == "cleaned"

    detail = client.get(f"/api/jobs/{job.job_id}")
    assert detail.status_code == 200
    task_detail = detail.get_json()["task_detail"]
    assert {item["artifact_kind"] for item in task_detail["input_artifacts"]} == {"factor_source", "product_scope"}
    retained_input = next(item for item in task_detail["input_artifacts"] if item["artifact_kind"] == "factor_source")
    assert retained_input["name"] == "factor_source__ProfileScreen"
    assert retained_input["role"] == "input"
    assert retained_input["artifact_kind"] == "factor_source"
    assert retained_input["file_name"] == "ProfileScreen.py"
    assert retained_input["title_zh"] == "临时因子源码：ProfileScreen"
    old_byte_route = client.get(
        f"/api/jobs/{job.job_id}/artifacts/factor_source__ProfileScreen"
    )
    assert old_byte_route.status_code == 404

    cleared = client.delete(f"/api/jobs/{job.job_id}/artifacts")
    assert cleared.status_code == 200
    assert cleared.get_json()["deleted_files"] == 2
    assert not (
        tmp_path / "artifacts" / source_artifact["relative_path"]
    ).exists()


def test_retry_rebuilds_transient_factor_scope_from_retained_job_input(
    client,
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("GTHT_JOB_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    source = '''
from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam

class ProfileScreen(FactorFamily):
    desc = "临时筛选因子"
    source_freq = "1m"

    @staticmethod
    def factor_expr():
        return DataColumnParam("TO", default_value="TO").rolling_mean(
            WindowParam("N", default_value="20d")
        ).cs_ordinal_rank(ascending=False)
'''
    factor = _inline_factor(tmp_path, source, "ProfileScreen|N:20d")
    created = client.post("/api/test-authoring/workspaces", json={
        "title": "retry retained source",
        "factor_families": [{"alias": "ProfileScreen"}],
        "factors": [factor],
    })
    workspace = created.get_json()["workspace"]
    payload = _payload(workspace)
    group = payload["analyses"]["backtest"]["groups"][0]
    group["factor_candidate_refs"] = [factor["ref"]]
    group["factorRoleBindings"] = {"screen": factor["ref"]}
    group["screen_rule"] = "lte"
    group["screen_upper"] = 12
    _update(client, workspace, payload)
    submitted = client.post("/api/runs", json={
        "workspace_id": workspace["workspace_id"],
        "configuration_revision": workspace["configuration"]["revision"],
        "analyses": ["backtest"],
        "transient_factor_sources": [{
            "path": "custom_factors/ProfileScreen.py",
            "source_code": source,
        }],
    })
    original = JobRepository().list(
        owner="alice", run_id=submitted.get_json()["run_id"],
    )[0]
    repository = JobRepository()
    original_scope = str(
        original.job_spec["transient_factor_source_scope_id"]
    )
    repository.transition(original.job_id, "planning")
    repository.transition(
        original.job_id,
        "failed",
        expected="planning",
        error={"code": "retry_test", "message": "retry retained input"},
    )
    assert original.summary()["factor_source_policy"]["scope_status"] == "cleaned"

    response = client.post(f"/api/jobs/{original.job_id}/retry")

    assert response.status_code == 202, response.get_data(as_text=True)
    retried = repository.require(response.get_json()["job_id"], owner="alice")
    retry_scope = str(retried.job_spec["transient_factor_source_scope_id"])
    assert retry_scope and retry_scope != original_scope
    assert retried.summary()["factor_source_policy"]["scope_status"] == "available"
    artifact = repository.load_artifact(
        job_id=retried.job_id,
        name="factor_source__ProfileScreen",
        owner="alice",
    )
    assert artifact is not None
    assert artifact["artifact_role"] == "input"
    assert artifact["artifact_kind"] == "factor_source"
    assert artifact["content_hash"] == hashlib.sha256(
        source.encode("utf-8")
    ).hexdigest()


def test_retry_input_copy_failure_terminalizes_new_attempt(
    client,
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("GTHT_JOB_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    source = '''
from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam

class ProfileScreen(FactorFamily):
    source_freq = "1m"

    @staticmethod
    def factor_expr():
        return DataColumnParam("TO", default_value="TO").rolling_mean(
            WindowParam("N", default_value="20d")
        )
'''
    factor = _inline_factor(tmp_path, source, "ProfileScreen|N:20d")
    created = client.post("/api/test-authoring/workspaces", json={
        "title": "retry input copy failure",
        "factor_families": [{"alias": "ProfileScreen"}],
        "factors": [factor],
    })
    workspace = created.get_json()["workspace"]
    payload = _payload(workspace)
    payload["analyses"]["backtest"]["groups"][0]["factorAlias"] = (
        "ProfileScreen|N:20d"
    )
    _update(client, workspace, payload)
    submitted = client.post("/api/runs", json={
        "workspace_id": workspace["workspace_id"],
        "configuration_revision": workspace["configuration"]["revision"],
        "analyses": ["backtest"],
        "transient_factor_sources": [{
            "path": "custom_factors/ProfileScreen.py",
            "source_code": source,
        }],
    })
    repository = JobRepository()
    original = repository.list(
        owner="alice", run_id=submitted.get_json()["run_id"],
    )[0]
    repository.transition(original.job_id, "planning")
    repository.transition(
        original.job_id,
        "failed",
        expected="planning",
        error={"code": "retry_test", "message": "force a retry"},
    )

    def fail_copy(*_args, **_kwargs):
        raise OSError("simulated retained input write failure")

    monkeypatch.setattr(
        "server.modules.single_factor_test.backtest_jobs.retain_factor_sources",
        fail_copy,
    )
    client.application.config["PROPAGATE_EXCEPTIONS"] = False
    response = client.post(f"/api/jobs/{original.job_id}/retry")

    assert response.status_code == 500
    attempts = [
        item for item in repository.list(owner="alice", run_id=original.run_id)
        if item.retry_of == original.job_id
    ]
    assert len(attempts) == 1
    failed = attempts[0]
    assert failed.status.value == "failed"
    assert failed.error == {
        "code": "job_input_retention_failed",
        "message": "simulated retained input write failure",
    }
    assert failed.summary()["factor_source_policy"]["scope_status"] == "cleaned"


def test_submitted_strategy_hook_is_retained_and_exposed_as_job_input(
    client,
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("GTHT_JOB_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    factor_source = '''
from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam

class ProfileScreen(FactorFamily):
    source_freq = "1m"

    @staticmethod
    def factor_expr():
        return DataColumnParam("TO", default_value="TO").rolling_mean(
            WindowParam("N", default_value="20d")
        )
'''
    factor = _inline_factor(
        tmp_path, factor_source, "ProfileScreen|N:20d",
    )
    created = client.post("/api/test-authoring/workspaces", json={
        "title": "strategy hook inputs",
        "factor_families": [{"alias": "ProfileScreen"}],
        "factors": [factor],
    })
    workspace = created.get_json()["workspace"]
    payload = _payload(workspace)
    payload["shared"] = dict(workspace["configuration"]["payload"]["shared"])
    payload["analyses"]["backtest"]["groups"][0]["factorAlias"] = (
        "ProfileScreen|N:20d"
    )
    _update(client, workspace, payload)
    source = """\
class IntradayGate:
    def on_bar(self, context):
        return None
"""

    response = client.post("/api/runs", json={
        "workspace_id": workspace["workspace_id"],
        "configuration_revision": workspace["configuration"]["revision"],
        "analyses": ["backtest"],
        "strategy_specs": [{
            "source": "profile:strategies/hooks/intraday_gate.py",
            "strategy_id": "intraday_gate",
            "entrypoint": "IntradayGate",
        }],
        "transient_strategy_sources": [{
            "path": "strategies/hooks/intraday_gate.py",
            "source_code": source,
        }],
        "transient_factor_sources": [{
            "path": "custom_factors/ProfileScreen.py",
            "source_code": factor_source,
        }],
    })

    assert response.status_code == 202, response.get_data(as_text=True)
    job = JobRepository().list(
        owner="alice", run_id=response.get_json()["run_id"],
    )[0]
    detail = client.get(f"/api/jobs/{job.job_id}")
    assert detail.status_code == 200
    inputs = detail.get_json()["task_detail"]["input_artifacts"]
    retained = next(
        item for item in inputs if item["artifact_kind"] == "strategy_source"
    )
    assert retained["role"] == "input"
    assert retained["artifact_kind"] == "strategy_source"
    assert retained["file_name"] == "intraday_gate.py"
    assert retained["logical_path"] == "strategies/hooks/intraday_gate.py"
    assert retained["title_zh"] == (
        "临时策略源码：strategies/hooks/intraday_gate.py"
    )
    old_byte_route = client.get(
        f"/api/jobs/{job.job_id}/artifacts/{retained['name']}"
    )
    assert old_byte_route.status_code == 404
    spec = next(
        item for item in inputs if item["artifact_kind"] == "strategy_spec"
    )
    assert spec["role"] == "input"
    assert spec["file_name"] == "intraday_gate.strategy.json"
    assert spec["title_zh"] == "运行策略配置：intraday_gate"
    assert client.get(
        f"/api/jobs/{job.job_id}/artifacts/{spec['name']}"
    ).status_code == 404


def test_run_dependency_is_frozen_retained_and_copied_on_retry(
    client,
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("GTHT_JOB_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    workspace = _create_workspace(client)
    _update(client, workspace, _payload(workspace))
    dependency = {
        "path": "strategy-configs/dynamic-hold.yaml",
        "content": "target_leverage: 0.4\nmax_leverage: 0.5\n",
        "content_type": "application/yaml",
        "title_zh": "动态持仓参数",
        "purpose": "strategy_configuration",
        "analyses": ["backtest"],
    }
    submitted = client.post("/api/runs", json={
        "workspace_id": workspace["workspace_id"],
        "configuration_revision": workspace["configuration"]["revision"],
        "analyses": ["backtest"],
        "output_requests": ["group_research_detail"],
        "run_input_dependencies": [dependency],
    })

    assert submitted.status_code == 202, submitted.get_data(as_text=True)
    repository = JobRepository()
    original = repository.list(
        owner="alice", run_id=submitted.get_json()["run_id"],
    )[0]
    assert original.job_spec["retention_mode"] == "summary"
    # #298 changed this viewer to the compact strategy_analysis_source
    # artifact, so it no longer forces full replay retention.
    assert original.job_spec["result_retention_mode"] == "summary"
    assert original.retention_mode == "summary"
    policy = original.job_spec["run_spec"]["run_input_dependency_policy"]
    assert policy["mode"] == "retained_job_input"
    assert policy["files"][0]["path"] == dependency["path"]
    assert "content" not in policy["files"][0]

    detail = client.get(f"/api/jobs/{original.job_id}")
    task_detail = detail.get_json()["task_detail"]
    inputs = task_detail["input_artifacts"]
    assert task_detail["run_input_dependency_policy"] == policy
    retained = next(
        item for item in inputs if item["artifact_kind"] == "run_dependency"
    )
    assert retained["file_name"] == "dynamic-hold.yaml"
    assert retained["logical_path"] == dependency["path"]
    assert retained["title_zh"] == dependency["title_zh"]
    old_byte_route = client.get(
        f"/api/jobs/{original.job_id}/artifacts/{retained['name']}"
    )
    assert old_byte_route.status_code == 404

    repository.transition(original.job_id, "planning")
    repository.transition(
        original.job_id,
        "failed",
        expected="planning",
        error={"code": "retry_test", "message": "copy dependencies"},
    )
    retry = client.post(f"/api/jobs/{original.job_id}/retry")
    assert retry.status_code == 202, retry.get_data(as_text=True)
    copied = repository.list_artifacts(
        job_id=retry.get_json()["job_id"], owner="alice",
    )
    copied_dependency = next(
        item for item in copied if item["artifact_kind"] == "run_dependency"
    )
    assert copied_dependency["content_hash"] == retained["content_hash"]
    assert copied_dependency["file_name"] == retained["file_name"]

    cleared = client.delete(f"/api/jobs/{original.job_id}/artifacts")
    assert cleared.status_code == 200
    assert cleared.get_json()["deleted_files"] == 2
    assert repository.load_artifact(
        job_id=original.job_id,
        name=retained["name"],
        owner="alice",
    )["state"] == "deleted"
    assert repository.load_artifact(
        job_id=retry.get_json()["job_id"],
        name=copied_dependency["name"],
        owner="alice",
    )["state"] == "active"


def test_configuration_snapshot_preview_and_submit_freeze_same_runspec(
    client,
) -> None:
    workspace = _create_workspace(client)
    _update(client, workspace, _payload(workspace, n="10d"))
    source = workspace["configuration"]
    response = client.post(
        f"/api/test-authoring/workspaces/{workspace['workspace_id']}/"
        "configuration-snapshots",
        json={
            "source_workspace_id": workspace["workspace_id"],
            "source_configuration_id": source["configuration_id"],
            "source_configuration_revision": source["revision"],
            "name": "day-session",
        },
    )
    assert response.status_code == 201
    snapshot = response.get_json()["snapshot"]
    _update(client, workspace, _payload(workspace, n="20d"))
    request_payload = {
        "workspace_id": workspace["workspace_id"],
        "configuration_snapshot_id": snapshot["snapshot_id"],
        "configuration_snapshot_revision": snapshot["snapshot_revision"],
        "analyses": ["ic"],
        "retention_mode": "summary",
        "step_mode": False,
    }

    preview = client.post("/api/runs/preview", json=request_payload)
    assert preview.status_code == 200, preview.get_data(as_text=True)
    preview_value = preview.get_json()
    assert preview_value["configuration_snapshot"] == {
        "snapshot_id": snapshot["snapshot_id"],
        "snapshot_revision": 1,
        "fingerprint": snapshot["fingerprint"],
        "source_provenance": snapshot["source_provenance"],
    }

    submitted = client.post("/api/runs", json=request_payload)
    assert submitted.status_code == 202, submitted.get_data(as_text=True)
    run = submitted.get_json()["run"]
    assert run["run_spec_hash"] == preview_value["run_spec_hash"]
    assert run["configuration_id"] == snapshot["snapshot_id"]
    assert run["configuration_revision"] == 1
    assert run["run_spec"]["configuration"]["analyses"]["ic"][
        "factor_configs"
    ] == [{"N": "10d"}]


def test_configuration_snapshot_rejects_wrong_scope_stale_or_deleted(
    client,
) -> None:
    workspace = _create_workspace(client)
    _update(client, workspace, _payload(workspace))
    source = workspace["configuration"]
    snapshot = client.post(
        f"/api/test-authoring/workspaces/{workspace['workspace_id']}/"
        "configuration-snapshots",
        json={
            "source_configuration_id": source["configuration_id"],
            "source_configuration_revision": source["revision"],
            "name": "frozen",
        },
    ).get_json()["snapshot"]
    other = _create_workspace(client)
    base = {
        "configuration_snapshot_id": snapshot["snapshot_id"],
        "configuration_snapshot_revision": 1,
        "analyses": ["ic"],
    }
    assert client.post("/api/runs/preview", json={
        **base,
        "workspace_id": other["workspace_id"],
    }).status_code == 404
    assert client.post("/api/runs/preview", json={
        **base,
        "workspace_id": workspace["workspace_id"],
        "configuration_snapshot_revision": 2,
    }).status_code == 409

    with client.session_transaction() as session:
        session["username"] = "bob"
    assert client.post("/api/runs/preview", json={
        **base,
        "workspace_id": workspace["workspace_id"],
    }).status_code == 404
    with client.session_transaction() as session:
        session["username"] = "alice"
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        conn.execute(
            "UPDATE research_configuration_snapshots "
            "SET deleted_at=1 WHERE snapshot_id=?",
            (snapshot["snapshot_id"],),
        )
    assert client.post("/api/runs/preview", json={
        **base,
        "workspace_id": workspace["workspace_id"],
    }).status_code == 404


def test_configuration_snapshot_selection_adds_one_select(
    client,
    monkeypatch,
) -> None:
    workspace = _create_workspace(client)
    source = workspace["configuration"]
    snapshot = client.post(
        f"/api/test-authoring/workspaces/{workspace['workspace_id']}/"
        "configuration-snapshots",
        json={
            "source_configuration_id": source["configuration_id"],
            "source_configuration_revision": source["revision"],
            "name": "one-read",
        },
    ).get_json()["snapshot"]
    statements: list[str] = []
    real_connect = research_configuration_snapshots.connect_sqlite

    def traced_connect(path):
        conn = real_connect(path)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(
        research_configuration_snapshots,
        "connect_sqlite",
        traced_connect,
    )
    loaded = research_configuration_snapshots.load_snapshot(
        owner="alice",
        workspace_id=workspace["workspace_id"],
        snapshot_id=snapshot["snapshot_id"],
        expected_revision=1,
    )
    assert loaded["snapshot_id"] == snapshot["snapshot_id"]
    statements = [
        statement for statement in statements
        if statement.lstrip().upper().startswith(
            ("SELECT", "INSERT", "UPDATE", "DELETE", "CREATE")
        )
    ]
    assert len(statements) == 1
    assert statements[0].lstrip().upper().startswith("SELECT")


def test_configuration_snapshot_copies_owned_source_into_target_workspace(
    client,
) -> None:
    source_workspace = _create_workspace(client)
    _update(
        client,
        source_workspace,
        _payload(source_workspace, n="30d"),
    )
    target_workspace = _create_workspace(client)
    source = source_workspace["configuration"]
    response = client.post(
        f"/api/test-authoring/workspaces/{target_workspace['workspace_id']}/"
        "configuration-snapshots",
        json={
            "source_workspace_id": source_workspace["workspace_id"],
            "source_configuration_id": source["configuration_id"],
            "source_configuration_revision": source["revision"],
            "name": "night-session",
        },
    )
    assert response.status_code == 201
    snapshot = response.get_json()["snapshot"]
    assert snapshot["workspace_id"] == target_workspace["workspace_id"]
    assert snapshot["source_provenance"]["workspace_id"] == (
        source_workspace["workspace_id"]
    )
    assert snapshot["payload"]["analyses"]["ic"]["factor_configs"] == [
        {"N": "30d"}
    ]
    listed = client.get(
        f"/api/test-authoring/workspaces/{target_workspace['workspace_id']}/"
        "configuration-snapshots"
    ).get_json()["snapshots"]
    assert [item["snapshot_id"] for item in listed] == [
        snapshot["snapshot_id"]
    ]
    preview = client.post("/api/runs/preview", json={
        "workspace_id": target_workspace["workspace_id"],
        "configuration_snapshot_id": snapshot["snapshot_id"],
        "configuration_snapshot_revision": 1,
        "analyses": ["ic"],
    })
    assert preview.status_code == 200, preview.get_data(as_text=True)
    run_spec = preview.get_json()["report_projection"]["run_spec"][
        "complete_parameters"
    ]
    assert run_spec["workspace_id"] == target_workspace["workspace_id"]
    assert run_spec["configuration_snapshot"]["source_provenance"][
        "workspace_id"
    ] == source_workspace["workspace_id"]


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
    from server.modules.single_factor_test.planning import _artifact_plan_rows

    assert _artifact_plan_rows(job.job_spec) == [{
        "artifact_id": "academic_mom:abc",
        "manifest_sha256": "manifest-hash",
        "factor_sha256": "factor-hash",
    }]


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
    assert backtest["factor"] == "MmRet|P:CA|N:10d|$F:1d"
    assert backtest["execution"]["settings"] == {"start_date": "2024-01-01"}
    assert "local_settings" not in backtest


def test_configuration_schema_migration_replaces_legacy_settings_atomically(client) -> None:
    workspace = _create_workspace(client)
    legacy = workspace["configuration"]["payload"]
    legacy["schema_version"] = 2
    legacy["analyses"]["backtest"] = {
        "local_settings": {"start_date": "2024-01-01"},
        "groups": [],
    }
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        conn.execute(
            "UPDATE research_configurations SET schema_version=2, payload_json=? "
            "WHERE configuration_id=?",
            (json.dumps(legacy), workspace["configuration"]["configuration_id"]),
        )

    report = research_configurations.migrate_legacy_workspaces_and_runs(apply=True)
    migrated = research_configurations.load_workspace_configuration(
        workspace_id=workspace["workspace_id"], owner="alice",
    )

    assert report["configuration_schema_upgrades"] == 1
    assert migrated["schema_version"] == 3
    backtest = migrated["payload"]["analyses"]["backtest"]
    assert backtest["execution"]["settings"] == {"start_date": "2024-01-01"}
    assert "local_settings" not in backtest


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
    assert all(
        job.run_spec_hash == response.get_json()["run"]["run_spec_hash"]
        for job in jobs
    )


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


def test_submission_payload_cannot_write_terminal_assurance(client) -> None:
    workspace = _create_workspace(client)
    _update(client, workspace, _payload(workspace))

    response = client.post("/api/runs", json={
        "workspace_id": workspace["workspace_id"],
        "configuration_revision": workspace["configuration"]["revision"],
        "analyses": ["ic"],
        "terminal_assurance": {
            "disposition": "trusted",
            "policy_hash": "forged",
        },
    })

    assert response.status_code == 202
    job = JobRepository().list(
        owner="alice",
        run_id=response.get_json()["run_id"],
    )[0]
    assert job.terminal_assurance is None
    assert job.summary()["has_terminal_assurance"] is False
    assert "terminal_assurance" not in job.summary()


def test_retry_attests_current_backend_revision_without_changing_frozen_run(
    client,
    monkeypatch,
) -> None:
    monkeypatch.setenv("GTHT_SOURCE_REVISION", "old-backend-revision")
    workspace = _create_workspace(client)
    _update(client, workspace, _payload(workspace))
    response = client.post(
        "/api/runs",
        json={
            "workspace_id": workspace["workspace_id"],
            "configuration_revision": workspace["configuration"]["revision"],
            "analyses": ["backtest"],
        },
        base_url="http://localhost:8141",
    )
    assert response.status_code == 202, response.get_data(as_text=True)
    original = JobRepository().list(
        owner="alice",
        run_id=response.get_json()["run_id"],
    )[0]
    repository = JobRepository()
    repository.transition(original.job_id, "planning")
    repository.transition(
        original.job_id,
        "failed",
        expected="planning",
        error={"code": "backend_regression", "message": "retry after deployment"},
    )

    monkeypatch.setenv("GTHT_SOURCE_REVISION", "new-backend-revision")
    retried_response = client.post(
        f"/api/jobs/{original.job_id}/retry",
        json={
            "performance_profile": {
                "kind": "cumulative_flow",
                "min_total_ms": 25,
            },
        },
        base_url="http://localhost:8176",
    )

    assert retried_response.status_code == 202, retried_response.get_data(as_text=True)
    retried = repository.require(retried_response.get_json()["job_id"])
    assert retried.source_revision == "new-backend-revision"
    assert original.service_port == 8141
    assert retried.service_port == 8176
    assert retried.run_spec_hash == original.run_spec_hash
    assert {
        key: value for key, value in retried.job_spec.items()
        if key != "performance_profile"
    } == original.job_spec
    assert retried.job_spec["performance_profile"] == {
        "kind": "cumulative_flow",
        "min_total_ms": 25.0,
    }
    assert retried.retry_of == original.job_id


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
    assert frozen["paths"] == ["core8_path"]
    assert "selected_paths" not in frozen
    assert frozen["product_group_template_id"] == "owner-group"
    run = response.get_json()["run"]
    assert run["run_spec"]["configuration"]["shared"]["product_selections"]["owner-group"] == frozen
    assert "product_selections" not in run["run_spec"]["configuration"]["analyses"]["backtest"]


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
