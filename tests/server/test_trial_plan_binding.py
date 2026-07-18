"""ResearchRun binding, JobAttempt inheritance, and retention tests."""

from __future__ import annotations

from dataclasses import replace

import orjson
from flask import Flask
import pytest

import settings as Settings
from server.jobs.repository import JobRepository
from server.modules.single_factor_test import sft_bp
from server.services import research_runs
from server.services.research_graph.trial_plan import (
    canonical_trial_plan,
    trial_plan_hash,
    trial_plan_trace_retention,
)
from tests.server.trial_plan_fixtures import (
    initialize_branch,
    job_record,
    run_spec,
    semantic_hash,
    trial_binding,
    trial_plan,
)
from tools.data.sqlite.db import connect_sqlite


def test_research_run_binds_plan_and_jobs_inherit_through_run(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "trial-plan.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    run_spec_value = run_spec()
    plan = trial_plan(semantic_hash(run_spec_value))
    plan_hash = trial_plan_hash(plan)
    initialize_branch(path, plan_hash)

    run = research_runs.create_run(
        owner="alice",
        workspace_id="workspace-1",
        configuration_id="configuration-1",
        configuration_revision=1,
        run_spec=run_spec_value,
        trial_binding=trial_binding(plan),
    )
    repository = JobRepository(path)
    first = repository.create(job_record(run["run_id"], run_spec_value))
    retry = repository.create(replace(
        job_record(run["run_id"], run_spec_value, job_id="job-2"),
        retry_of=first.job_id,
        attempt=2,
    ))

    expected = {
        "trial_plan_id": "plan-1",
        "trial_plan_hash": plan_hash,
        "trial_plan_version": 1,
        "trial_role": "main-only",
        "comparison_id": "main-comparison",
    }
    assert {key: run[key] for key in expected} == expected
    assert research_runs.load_job_trial_binding(
        job_id=first.job_id,
        owner="alice",
    ) == expected
    assert research_runs.load_job_trial_binding(
        job_id=retry.job_id,
        owner="alice",
    ) == expected
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = "alice"
    response = client.get(f"/api/jobs/{first.job_id}")
    assert response.status_code == 200
    assert response.get_json()["evidence"]["trial_binding"] == expected
    with connect_sqlite(path) as conn:
        job_columns = {
            str(row["name"])
            for row in conn.execute(
                "PRAGMA table_info(research_jobs)"
            ).fetchall()
        }
    assert {
        "trial_plan_id",
        "trial_plan_hash",
        "trial_plan_version",
        "trial_role",
        "comparison_id",
    }.isdisjoint(job_columns)


def test_unbound_research_run_remains_readable_without_trial_projection(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "unbound-run.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    run_spec_value = run_spec()

    created = research_runs.create_run(
        owner="alice",
        workspace_id="workspace-1",
        configuration_id="configuration-1",
        configuration_revision=1,
        run_spec=run_spec_value,
    )
    repository = JobRepository(path)
    job = repository.create(job_record(created["run_id"], run_spec_value))

    loaded = research_runs.load_run(
        run_id=created["run_id"],
        owner="alice",
    )
    assert loaded is not None
    assert loaded["run_id"] == created["run_id"]
    assert loaded["trial_plan_hash"] == ""
    assert research_runs.load_job_trial_binding(
        job_id=job.job_id,
        owner="alice",
    ) is None


def test_run_binding_rejects_stale_branch_and_unplanned_member(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "stale-binding.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    run_spec_value = run_spec()
    plan = trial_plan(semantic_hash(run_spec_value))
    initialize_branch(path, "b" * 64)

    with pytest.raises(ValueError, match="not the current plan"):
        research_runs.create_run(
            owner="alice",
            workspace_id="workspace-1",
            configuration_id="configuration-1",
            configuration_revision=1,
            run_spec=run_spec_value,
            trial_binding=trial_binding(plan),
        )
    invalid = trial_binding(plan)
    invalid["trial_role"] = "aux-only"
    with pytest.raises(ValueError, match="not a planned comparison member"):
        research_runs.create_run(
            owner="alice",
            workspace_id="workspace-1",
            configuration_id="configuration-1",
            configuration_revision=1,
            run_spec=run_spec_value,
            trial_binding=invalid,
        )


def test_bound_run_creation_has_one_read_one_write_and_no_trace_scan(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "run-sql.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    run_spec_value = run_spec()
    plan = trial_plan(semantic_hash(run_spec_value))
    initialize_branch(path, trial_plan_hash(plan))
    research_runs.ensure_schema()
    statements: list[str] = []

    def traced_connect(*args, **kwargs):
        connection = connect_sqlite(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(research_runs, "connect_sqlite", traced_connect)
    research_runs.create_run(
        owner="alice",
        workspace_id="workspace-1",
        configuration_id="configuration-1",
        configuration_revision=1,
        run_spec=run_spec_value,
        trial_binding=trial_binding(plan),
    )

    normalized = [" ".join(item.upper().split()) for item in statements]
    reads = [item for item in normalized if item.startswith("SELECT")]
    writes = [item for item in normalized if item.startswith("INSERT")]
    assert len(reads) == 1
    assert len(writes) == 1
    assert "RESEARCH_GRAPH_TRACE" not in reads[0]
    assert "INSERT INTO RESEARCH_RUNS" in writes[0]
    assert not any(
        item.startswith(("CREATE", "ALTER", "DROP", "PRAGMA"))
        for item in normalized
    )


def test_trial_plan_trace_is_retention_pinned_by_branch_run_and_job(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "retention.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    run_spec_value = run_spec()
    plan = trial_plan(semantic_hash(run_spec_value))
    plan_hash = trial_plan_hash(plan)
    initialize_branch(path, plan_hash)
    run = research_runs.create_run(
        owner="alice",
        workspace_id="workspace-1",
        configuration_id="configuration-1",
        configuration_revision=1,
        run_spec=run_spec_value,
        trial_binding=trial_binding(plan),
    )
    JobRepository(path).create(job_record(run["run_id"], run_spec_value))
    with connect_sqlite(path) as conn:
        conn.execute(
            """
            INSERT INTO research_graph_trace (
                trace_id, instance_id, branch_id, edge_id,
                from_node, to_node, evidence_json, actor, created_at
            ) VALUES (
                'trace-plan', 'instance-1', 'branch-1', 'freeze-plan',
                'validation_design', 'diagnostics', ?, 'alice', 2
            )
            """,
            (orjson.dumps({
                "trial_plan": canonical_trial_plan(plan),
                "trial_plan_hash": plan_hash,
            }).decode(),),
        )
        status = trial_plan_trace_retention(
            conn,
            trace_id="trace-plan",
        )

    assert status == {
        "trace_id": "trace-plan",
        "trial_plan_hash": plan_hash,
        "pinned": True,
        "branch_references": 1,
        "run_references": 1,
        "job_references": 1,
    }
