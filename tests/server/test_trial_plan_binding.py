"""ResearchRun binding, JobAttempt inheritance, and retention tests."""

from __future__ import annotations

from dataclasses import replace

import orjson
from flask import Flask
import pytest

import settings as Settings
from server.jobs.repository import JobRepository
from server.jobs.states import JobStatus
from server.modules.single_factor_test import sft_bp
from server.services import research_runs
from server.services.research_graph.trial_plan import (
    canonical_trial_plan,
    trial_plan_hash,
    trial_plan_trace_retention,
)
from server.services.research_graph.trial_plan.sample_identity import (
    derive_sample_identity,
)
from tests.server.trial_plan_fixtures import (
    initialize_branch,
    job_record,
    run_spec,
    run_spec_with_dates,
    semantic_hash,
    trial_binding,
    trial_plan,
)
from tools.data.sqlite.db import connect_sqlite


def _staged_plan(
    run_spec_value: dict,
    *,
    version: int,
    role: str,
    sample_hash: str | None = None,
) -> dict:
    run_hash = semantic_hash(run_spec_value)
    plan = trial_plan(run_hash)
    identity = derive_sample_identity(run_spec_value)
    return {
        **plan,
        "schema_version": 2,
        "trial_plan_id": f"plan-{version}",
        "version": version,
        "sample_roles": [{
            "sample_ref": f"{role}-{version}",
            "sample_hash": sample_hash or identity["sample_hash"],
            "role": role,
            "run_spec_hashes": [run_hash],
        }],
        "comparisons": [{
            "comparison_id": f"comparison-{version}",
            "members": [{
                "run_spec_hash": run_hash,
                "trial_role": role,
            }],
        }],
    }


def _bind(plan: dict) -> dict:
    role = plan["sample_roles"][0]["role"]
    return {
        "instance_id": "instance-1",
        "branch_id": "branch-1",
        "trial_plan": plan,
        "trial_plan_hash": trial_plan_hash(plan),
        "trial_plan_version": plan["version"],
        "trial_role": role,
        "comparison_id": plan["comparisons"][0]["comparison_id"],
    }


def _sample_scope_run_spec(
    paths: list[str],
    *,
    start: str,
    end: str,
) -> dict:
    value = run_spec_with_dates(start, end)
    value["configuration"]["analyses"]["ic"]["paths"] = paths
    return value


def _activate_plan(path, plan: dict) -> None:
    with connect_sqlite(path) as conn:
        conn.execute(
            """
            UPDATE research_graph_branches
            SET current_trial_plan_hash=?
            WHERE branch_id='branch-1'
            """,
            (trial_plan_hash(plan),),
        )


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
        "trial_role": "selection",
        "trial_stage": "selection",
        "comparison_id": "main-comparison",
        "sample_ref": "selection-2020-2023",
        "sample_hash": "d" * 64,
        "sample_identity_hash": derive_sample_identity(
            run_spec_value
        )["sample_hash"],
        "sample_identity_assurance": "declared_legacy",
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
        "trial_stage",
        "comparison_id",
    }.isdisjoint(job_columns)


def test_terminal_job_detail_projects_server_owned_research_evidence(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "job-evidence.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    run_spec_value = run_spec()
    run_hash = semantic_hash(run_spec_value)
    sample_hash = derive_sample_identity(run_spec_value)["sample_hash"]
    plan = {
        **trial_plan(run_hash),
        "schema_version": 3,
        "decision_contract_hash": "1" * 64,
        "methodology_hash": "2" * 64,
        "obligation_refs": ["obligation-job-evidence"],
    }
    plan["sample_roles"][0]["sample_hash"] = sample_hash
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
    job = repository.create(replace(
        job_record(run["run_id"], run_spec_value),
        source_revision="backend-revision-1",
    ))
    repository.transition(job.job_id, JobStatus.PLANNING)
    repository.set_execution_plan(
        job.job_id,
        plan={"runner": "test:ic", "steps": ["compute"]},
        notices=[],
        requires_confirmation=False,
    )
    repository.transition(job.job_id, JobStatus.RUNNING)
    repository.transition(
        job.job_id,
        JobStatus.SUCCEEDED,
        worker_exitcode=0,
        result_summary={"rank_ic": 0.04, "observations": 800},
    )
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = "alice"

    response = client.get(f"/api/jobs/{job.job_id}")
    envelope = response.get_json()["evidence"]["job_attempt"]
    result_response = client.get(f"/api/jobs/{job.job_id}/result")
    result_envelope = result_response.get_json()["evidence"]["job_attempt"]

    assert response.status_code == 200
    assert result_response.status_code == 200
    assert result_envelope["envelope_hash"] == envelope["envelope_hash"]
    assert envelope["schema_version"] == 2
    assert envelope["evidence_kind"] == "job_attempt"
    assert envelope["identity_refs"] == {
        "contract_hash": "1" * 64,
        "methodology_hash": "2" * 64,
        "trial_plan_hash": plan_hash,
        "run_spec_hash": run_hash,
    }
    assert envelope["source_refs"] == [
        f"research-job:{job.job_id}",
        f"research-run:{run['run_id']}",
    ]
    assert envelope["facts"]["status"] == "succeeded"
    assert envelope["facts"]["trial_stage"] == "selection"
    assert envelope["facts"]["assurance"]["disposition"] == "trusted"
    assert envelope["metric_refs"] == [
        "result-summary:sha256:"
        + repository.require(
            job.job_id,
            owner="alice",
        ).terminal_assurance.result_summary_hash
    ]
    assert envelope["artifact_refs"][0].startswith(
        "artifact-manifest:sha256:"
    )
    assert envelope["envelope_hash"]
    assert "result_summary" not in envelope
    assert "terminal_assurance" not in envelope


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


def test_sample_use_is_auditable_without_hardcoded_stage_order(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "sample-stage.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    product = "Product/Futures/CNFutures/_products/AP.CZC"
    selection_spec = _sample_scope_run_spec(
        [product], start="2020-01-01", end="2021-12-31",
    )
    selection = _staged_plan(
        selection_spec,
        version=1,
        role="selection",
    )
    initialize_branch(path, trial_plan_hash(selection))

    first = research_runs.create_run(
        owner="alice",
        workspace_id="workspace-1",
        configuration_id="configuration-1",
        configuration_revision=1,
        run_spec=selection_spec,
        trial_binding=_bind(selection),
    )
    assert first["graph_branch_id"] == "branch-1"
    assert first["sample_ref"] == "selection-1"
    assert first["sample_hash"] == derive_sample_identity(
        selection_spec
    )["sample_hash"]

    confirmation_spec = _sample_scope_run_spec(
        [product], start="2024-01-01", end="2024-12-31",
    )
    confirmation = _staged_plan(
        confirmation_spec,
        version=2,
        role="confirmation",
    )
    _activate_plan(path, confirmation)
    second = research_runs.create_run(
        owner="alice",
        workspace_id="workspace-1",
        configuration_id="configuration-2",
        configuration_revision=1,
        run_spec=confirmation_spec,
        trial_binding=_bind(confirmation),
    )
    assert second["trial_role"] == "confirmation"

    validation_spec = _sample_scope_run_spec(
        [product], start="2022-01-01", end="2023-12-31",
    )
    validation = _staged_plan(
        validation_spec,
        version=3,
        role="validation",
    )
    _activate_plan(path, validation)
    third = research_runs.create_run(
        owner="alice",
        workspace_id="workspace-1",
        configuration_id="configuration-3",
        configuration_revision=1,
        run_spec=validation_spec,
        trial_binding=_bind(validation),
    )
    assert third["trial_role"] == "validation"


def test_protected_sample_use_rejects_prior_exposure_and_role_relabeling(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "sample-stage-invalid.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    product = "Product/Futures/CNFutures/_products/AP.CZC"
    selection_spec = _sample_scope_run_spec(
        [product], start="2024-01-01", end="2024-12-31",
    )
    selection = _staged_plan(
        selection_spec,
        version=1,
        role="selection",
    )
    initialize_branch(path, trial_plan_hash(selection))
    research_runs.create_run(
        owner="alice",
        workspace_id="workspace-1",
        configuration_id="configuration-1",
        configuration_revision=1,
        run_spec=selection_spec,
        trial_binding=_bind(selection),
    )

    confirmation_spec = _sample_scope_run_spec(
        [product], start="2024-01-01", end="2024-12-31",
    )
    confirmation_spec.update(sample="confirmation", factor_revision=2)
    skipped = _staged_plan(
        confirmation_spec,
        version=2,
        role="confirmation",
    )
    _activate_plan(path, skipped)
    with pytest.raises(ValueError, match="already exposed"):
        research_runs.create_run(
            owner="alice",
            workspace_id="workspace-1",
            configuration_id="configuration-2",
            configuration_revision=1,
            run_spec=confirmation_spec,
            trial_binding=_bind(skipped),
        )

    validation_spec = _sample_scope_run_spec(
        [product], start="2024-01-01", end="2024-12-31",
    )
    validation_spec.update(sample="validation", factor_revision=3)
    reused = _staged_plan(
        validation_spec,
        version=2,
        role="validation",
    )
    _activate_plan(path, reused)
    with pytest.raises(ValueError, match="already exposed"):
        research_runs.create_run(
            owner="alice",
            workspace_id="workspace-1",
            configuration_id="configuration-2",
            configuration_revision=1,
            run_spec=validation_spec,
            trial_binding=_bind(reused),
        )


def test_first_bound_run_may_be_untouched_confirmation(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "first-confirmation.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    run_spec_value = _sample_scope_run_spec(
        ["Product/Futures/CNFutures/_products/AP.CZC"],
        start="2025-01-01", end="2025-12-31",
    )
    run_spec_value["sample"] = "confirmation"
    plan = _staged_plan(
        run_spec_value,
        version=1,
        role="confirmation",
    )
    initialize_branch(path, trial_plan_hash(plan))

    created = research_runs.create_run(
        owner="alice",
        workspace_id="workspace-1",
        configuration_id="configuration-1",
        configuration_revision=1,
        run_spec=run_spec_value,
        trial_binding=_bind(plan),
    )
    assert created["trial_role"] == "confirmation"


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
