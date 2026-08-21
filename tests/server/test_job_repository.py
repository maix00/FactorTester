from __future__ import annotations

import hashlib
import sqlite3
import time
from dataclasses import replace

import orjson
import pytest

from server.jobs.assurance import BackendAssuranceValidator
from server.jobs.models import JobRecord
from server.jobs.repository import JobRepository
from server.jobs.states import JobStatus
from server.services.research_run_schema import (
    ensure_schema as ensure_research_run_schema,
)
from tools.data.sqlite.db import connect_sqlite


def _record(
    job_id: str,
    *,
    owner: str = "alice",
    status: JobStatus = JobStatus.SUBMITTED,
    step_mode: bool = False,
) -> JobRecord:
    run_spec = {"workspace_id": "workspace-1", "products": ["A.DCE"]}
    return JobRecord(
        job_id=job_id,
        run_id="run-1",
        owner=owner,
        workspace_id="workspace-1",
        kind="backtest",
        status=status,
        step_mode=step_mode,
        deployment_id="issue-135",
        source_revision="abc123",
        runner_path="tests.server.long_lived_worker_fakes:cpu_runner",
        job_spec={
            "run_id": "run-1",
            "products": ["A.DCE"],
            "run_spec": run_spec,
        },
        run_spec_hash=hashlib.sha256(
            orjson.dumps(run_spec, option=orjson.OPT_SORT_KEYS)
        ).hexdigest(),
        created_at=time.time(),
    )


def test_repository_schema_contains_only_durable_job_facts(tmp_path) -> None:
    path = tmp_path / "jobs.sqlite"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE test_jobs(job_id TEXT PRIMARY KEY);
            CREATE TABLE test_job_events(job_id TEXT);
            CREATE TABLE test_job_process_slots(slot INTEGER);
            CREATE TABLE test_job_artifacts(job_id TEXT);
            CREATE TABLE research_view_leases(view_uuid TEXT);
            """
        )
    repository = JobRepository(path)
    repository.ensure_schema()

    with sqlite3.connect(path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(research_jobs)")
        }

    assert tables >= {
        "research_jobs",
        "user_job_pins",
        "user_storage_policies",
        "research_job_artifacts",
    }
    assert "test_job_events" not in tables
    assert "test_jobs" not in tables
    assert "test_job_process_slots" not in tables
    assert "test_job_artifacts" not in tables
    assert "research_view_leases" not in tables
    assert "latest_progress_json" not in columns
    assert "manifest_json" not in columns
    assert "initiator_page_uuid" not in columns
    assert "lifecycle_policy" not in columns
    assert {"job_spec_json", "job_spec_hash"} <= columns
    assert {"run_spec_hash", "terminal_assurance_json"} <= columns


def test_repository_rejects_bypassing_terminalization_on_create(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")

    with pytest.raises(ValueError, match="terminal jobs must use transition"):
        repository.create(_record("bypass", status=JobStatus.SUCCEEDED))


def test_supplemental_jobs_share_table_without_polluting_primary_lists(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    parent = repository.create(_record("parent"))
    supplemental = replace(
        _record("supplemental", status=JobStatus.QUEUED),
        job_role="supplemental",
        parent_job_id=parent.job_id,
        supplemental_kind="custom_python_analysis",
        supplemental_identity="identity-1",
        source_artifact_hash="source-1",
        execution_plan={"runner": "custom_python_analysis", "version": 1},
    )

    created, inserted = repository.create_or_load_supplemental(supplemental)
    reused, inserted_again = repository.create_or_load_supplemental(
        replace(supplemental, job_id="duplicate")
    )

    assert inserted is True
    assert inserted_again is False
    assert reused.job_id == created.job_id
    assert repository.list(owner="alice") == [parent]
    assert repository.list_supplemental(
        parent_job_id=parent.job_id, owner="alice",
    ) == [created]
    assert repository.has_run_attempts(owner="alice", run_id="run-1") is True


def test_terminal_supplemental_allows_a_new_attempt_with_same_identity(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    parent = repository.create(_record("parent"))
    first = replace(
        _record("supplemental-1", status=JobStatus.QUEUED),
        job_role="supplemental", parent_job_id=parent.job_id,
        supplemental_kind="backtest_strategy_analysis",
        supplemental_identity="tab-identity", source_artifact_hash="source-1",
        execution_plan={"runner": "strategy-analysis", "version": 1},
    )
    repository.create_or_load_supplemental(first)
    repository.transition(first.job_id, JobStatus.RUNNING)
    repository.transition(
        first.job_id, JobStatus.FAILED,
        error={"code": "analysis_failed", "message": "failed"},
    )

    second, inserted = repository.create_or_load_supplemental(
        replace(first, job_id="supplemental-2")
    )

    assert inserted is True
    assert second.job_id == "supplemental-2"


def test_custom_analysis_tabs_are_persistent_resources_not_job_history(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    parent = repository.create(_record("parent"))

    created = repository.create_custom_analysis(
        parent_job_id=parent.job_id, owner="alice",
        title="风险检查", source="result = {'ok': True}", tab_id="analysis-1",
    )
    renamed = repository.update_custom_analysis(
        parent_job_id=parent.job_id, owner="alice", tab_id="analysis-1",
        title="风险复核", source="result = {'ok': False}",
    )

    assert created["title"] == "风险检查"
    assert renamed["title"] == "风险复核"
    assert renamed["source"] == "result = {'ok': False}"
    assert repository.list_custom_analyses(
        parent_job_id=parent.job_id, owner="alice",
    ) == [renamed]

    deleted = repository.delete_custom_analysis(
        parent_job_id=parent.job_id, owner="alice", tab_id="analysis-1",
    )

    assert deleted["tab_id"] == "analysis-1"
    assert repository.load_custom_analysis(
        parent_job_id=parent.job_id, owner="alice", tab_id="analysis-1",
    ) is None
    assert repository.require(parent.job_id).job_id == parent.job_id


def test_custom_analysis_tabs_are_scoped_to_parent_owner(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    parent = repository.create(_record("parent"))
    repository.create_custom_analysis(
        parent_job_id=parent.job_id, owner="alice",
        title="分析", source="result = 1", tab_id="analysis-1",
    )

    assert repository.list_custom_analyses(
        parent_job_id=parent.job_id, owner="bob",
    ) == []
    with pytest.raises(KeyError):
        repository.update_custom_analysis(
            parent_job_id=parent.job_id, owner="bob", tab_id="analysis-1",
            title="越权", source="result = 2",
        )


def test_repository_initializes_schema_once_per_instance(tmp_path, monkeypatch) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    original = repository._ensure_schema
    calls = []

    def counted(conn):
        calls.append(1)
        return original(conn)

    monkeypatch.setattr(repository, "_ensure_schema", counted)
    repository.ensure_schema()
    repository.list(owner="alice")
    repository.list_for_deployment(
        deployment_id="test",
        statuses=(JobStatus.SUBMITTED,),
    )

    assert len(calls) == 1


def test_schema_upgrade_backfills_active_job_run_spec_hash(tmp_path) -> None:
    path = tmp_path / "jobs.sqlite"
    original = JobRepository(path)
    original.create(replace(_record("legacy-active"), run_spec_hash=""))
    assert original.require("legacy-active").run_spec_hash == ""

    upgraded = JobRepository(path)
    loaded = upgraded.require("legacy-active")

    assert loaded.run_spec_hash == hashlib.sha256(
        orjson.dumps(
            loaded.job_spec["run_spec"],
            option=orjson.OPT_SORT_KEYS,
        )
    ).hexdigest()
    assert loaded.terminal_assurance is None


def test_repository_freezes_plan_and_enforces_transitions(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    created = repository.create(_record("job-1"))
    planning = repository.transition(
        created.job_id,
        JobStatus.PLANNING,
        expected=JobStatus.SUBMITTED,
    )
    planned = repository.set_execution_plan(
        planning.job_id,
        plan={"products": ["A.DCE"], "frequency": "DAY1"},
        notices=[{"severity": "info", "code": "auto_source"}],
        requires_confirmation=True,
    )

    assert planned.status is JobStatus.AWAITING_CONFIRMATION
    assert planned.execution_plan_hash
    assert planned.plan_notices[0]["code"] == "auto_source"

    queued = repository.approve_plan(planned.job_id, owner="alice")
    running = repository.transition(
        queued.job_id,
        JobStatus.RUNNING,
        expected=JobStatus.QUEUED,
        worker_pid=123,
    )
    succeeded = repository.transition(
        running.job_id,
        JobStatus.SUCCEEDED,
        expected=JobStatus.RUNNING,
        result_summary={"success": True, "annual_return": 0.1},
    )

    assert succeeded.status is JobStatus.SUCCEEDED
    assert succeeded.result_summary == {"success": True, "annual_return": 0.1}
    with pytest.raises(ValueError, match="invalid job transition"):
        repository.transition(succeeded.job_id, JobStatus.RUNNING)


def test_successful_terminalization_persists_trusted_assurance(tmp_path) -> None:
    run_spec = {"workspace_id": "workspace-1", "factor": "momentum"}
    run_spec_hash = hashlib.sha256(
        orjson.dumps(run_spec, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()
    repository = JobRepository(tmp_path / "jobs.sqlite")
    created = repository.create(JobRecord(
        job_id="assured",
        run_id="run-assured",
        owner="alice",
        workspace_id="workspace-1",
        kind="backtest",
        status=JobStatus.SUBMITTED,
        source_revision="backend-revision-1",
        runner_path="tests.server.long_lived_worker_fakes:cpu_runner",
        job_spec={"run_id": "run-assured", "run_spec": run_spec},
        run_spec_hash=run_spec_hash,
    ))
    repository.transition(created.job_id, JobStatus.PLANNING)
    repository.set_execution_plan(
        created.job_id,
        plan={"runner": created.runner_path, "steps": ["compute"]},
        notices=[],
        requires_confirmation=False,
    )
    repository.transition(created.job_id, JobStatus.RUNNING)

    completed = repository.transition(
        created.job_id,
        JobStatus.SUCCEEDED,
        expected=JobStatus.RUNNING,
        result_summary={"success": True, "sharpe": 1.2},
    )

    assert completed.worker_exitcode is None
    assert completed.terminal_assurance is not None
    assert completed.terminal_assurance.disposition == "trusted"
    assert completed.terminal_assurance.anomaly_codes == ()
    assert completed.terminal_assurance.run_spec_hash == run_spec_hash
    assert completed.terminal_assurance.backend_revision == "backend-revision-1"


def test_ordinary_planning_failure_is_not_usable_without_maintenance(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    created = repository.create(_record("planning-failed"))
    repository.transition(
        created.job_id,
        JobStatus.PLANNING,
        expected=JobStatus.SUBMITTED,
    )

    failed = repository.transition(
        created.job_id,
        JobStatus.FAILED,
        expected=JobStatus.PLANNING,
        error={"code": "invalid_research_input", "message": "factor is invalid"},
    )

    assert failed.terminal_assurance is not None
    assert failed.terminal_assurance.disposition == "not_usable"
    assert (
        "execution_plan_missing_or_changed"
        in failed.terminal_assurance.anomaly_codes
    )
    with connect_sqlite(tmp_path / "jobs.sqlite") as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM research_maintenance_cases"
        ).fetchone()[0] == 0


def test_succeeded_assurance_anomaly_opens_one_case_in_terminal_transaction(
    tmp_path,
) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    created = repository.create(JobRecord(
        **{
            **_record("unattested-success").__dict__,
            "source_revision": "",
        }
    ))
    repository.transition(created.job_id, JobStatus.PLANNING)
    repository.set_execution_plan(
        created.job_id,
        plan={"products": ["A.DCE"]},
        notices=[],
        requires_confirmation=False,
    )
    repository.transition(created.job_id, JobStatus.RUNNING)

    completed = repository.transition(
        created.job_id,
        JobStatus.SUCCEEDED,
        result_summary={"success": True},
    )

    assert completed.terminal_assurance is not None
    assert completed.terminal_assurance.disposition == "maintenance_required"
    with connect_sqlite(tmp_path / "jobs.sqlite") as conn:
        case = conn.execute(
            "SELECT * FROM research_maintenance_cases"
        ).fetchone()
    assert case is not None
    assert case["owner_user_id"] == "alice"
    assert case["kind"] == "backend_anomaly"


def test_success_without_backend_revision_requires_maintenance(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    repository.create(replace(_record("unattested-success"), source_revision=""))
    repository.transition("unattested-success", JobStatus.PLANNING)
    repository.set_execution_plan(
        "unattested-success",
        plan={"products": ["A.DCE"]},
        notices=[],
        requires_confirmation=False,
    )
    repository.transition("unattested-success", JobStatus.RUNNING)

    completed = repository.transition(
        "unattested-success",
        JobStatus.SUCCEEDED,
        result_summary={"success": True},
    )

    assert completed.terminal_assurance is not None
    assert completed.terminal_assurance.disposition == "maintenance_required"
    assert (
        "backend_revision_unattested"
        in completed.terminal_assurance.anomaly_codes
    )


def test_artifact_manifest_hash_is_independent_of_arrival_order(tmp_path) -> None:
    hashes = []
    for job_id, names in (
        ("artifact-order-a", ("zeta", "alpha")),
        ("artifact-order-b", ("alpha", "zeta")),
    ):
        repository = JobRepository(tmp_path / f"{job_id}.sqlite")
        repository.create(_record(job_id))
        repository.transition(job_id, JobStatus.PLANNING)
        repository.set_execution_plan(
            job_id,
            plan={"products": ["A.DCE"]},
            notices=[],
            requires_confirmation=False,
        )
        repository.transition(job_id, JobStatus.RUNNING)
        for name in names:
            repository.record_artifact(
                job_id=job_id,
                name=name,
                relative_path=f"{job_id}/{name}.json",
                content_type="application/json",
                content_hash=hashlib.sha256(name.encode()).hexdigest(),
                size_bytes=len(name),
            )
        completed = repository.transition(
            job_id,
            JobStatus.SUCCEEDED,
            result_summary={"success": True},
        )
        assert completed.terminal_assurance is not None
        hashes.append(completed.terminal_assurance.artifact_manifest_hash)

    assert hashes[0] == hashes[1]


def test_terminal_artifact_manifest_is_immutable(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    repository.create(_record("immutable-artifacts"))
    repository.transition("immutable-artifacts", JobStatus.PLANNING)
    repository.set_execution_plan(
        "immutable-artifacts",
        plan={"products": ["A.DCE"]},
        notices=[],
        requires_confirmation=False,
    )
    repository.transition("immutable-artifacts", JobStatus.RUNNING)
    repository.record_artifact(
        job_id="immutable-artifacts",
        name="result",
        relative_path="immutable-artifacts/result.json",
        content_type="application/json",
        content_hash="a" * 64,
        size_bytes=10,
    )
    completed = repository.transition(
        "immutable-artifacts",
        JobStatus.SUCCEEDED,
        result_summary={"success": True},
    )

    with pytest.raises(ValueError, match="artifacts are immutable"):
        repository.record_artifact(
            job_id="immutable-artifacts",
            name="late",
            relative_path="immutable-artifacts/late.json",
            content_type="application/json",
            content_hash="b" * 64,
            size_bytes=12,
        )

    assert repository.require(
        "immutable-artifacts"
    ).terminal_assurance == completed.terminal_assurance


def test_terminal_assurance_keeps_the_policy_used_at_completion(tmp_path) -> None:
    path = tmp_path / "jobs.sqlite"
    original_validator = BackendAssuranceValidator({
        "policy_id": "backend-assurance@test-original",
        "checks": ["terminal_state"],
    })
    repository = JobRepository(path, assurance_validator=original_validator)
    repository.create(_record("historical-policy"))
    repository.transition("historical-policy", JobStatus.PLANNING)
    repository.set_execution_plan(
        "historical-policy",
        plan={"products": ["A.DCE"]},
        notices=[],
        requires_confirmation=False,
    )
    repository.transition("historical-policy", JobStatus.RUNNING)
    completed = repository.transition(
        "historical-policy",
        JobStatus.SUCCEEDED,
        result_summary={"success": True},
    )

    upgraded_repository = JobRepository(
        path,
        assurance_validator=BackendAssuranceValidator({
            "policy_id": "backend-assurance@test-upgraded",
            "checks": ["terminal_state", "new_check"],
        }),
    )
    historical = upgraded_repository.require("historical-policy")

    assert completed.terminal_assurance is not None
    assert historical.terminal_assurance is not None
    assert (
        historical.terminal_assurance.policy_hash
        == completed.terminal_assurance.policy_hash
        == original_validator.policy_hash
    )
    assert (
        historical.terminal_assurance.policy_hash
        != upgraded_repository.assurance_validator.policy_hash
    )


def test_terminalization_has_two_canonical_reads_and_one_job_write(
    tmp_path,
    monkeypatch,
) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    repository.create(_record("traced-terminal"))
    repository.transition("traced-terminal", JobStatus.PLANNING)
    repository.set_execution_plan(
        "traced-terminal",
        plan={"products": ["A.DCE"]},
        notices=[],
        requires_confirmation=False,
    )
    repository.transition("traced-terminal", JobStatus.RUNNING)
    statements: list[str] = []

    def traced_connect(*args, **kwargs):
        connection = connect_sqlite(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(
        "server.jobs.repository.sqlite.connect_sqlite",
        traced_connect,
    )
    repository.transition(
        "traced-terminal",
        JobStatus.SUCCEEDED,
        expected=JobStatus.RUNNING,
        result_summary={"success": True},
    )

    normalized = [" ".join(statement.split()) for statement in statements]
    reads = [
        statement for statement in normalized
        if statement.upper().startswith("SELECT")
    ]
    writes = [
        statement for statement in normalized
        if statement.upper().startswith("UPDATE RESEARCH_JOBS")
    ]
    assert len(reads) == 2
    assert len(writes) == 1
    assert "RETURNING *" in writes[0].upper()
    assert all(
        "research_backend_assurance_receipts" not in statement
        for statement in normalized
    )


def test_job_list_metadata_uses_one_bounded_read(
    tmp_path,
    monkeypatch,
) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    for job_id in ("list-1", "list-2"):
        repository.create(_record(job_id))
        repository.transition(job_id, JobStatus.PLANNING)
        repository.set_execution_plan(
            job_id,
            plan={"products": []},
            notices=[],
            requires_confirmation=False,
        )
    repository.pin("list-1", owner="alice")
    repository.record_artifact(
        job_id="list-1",
        name="summary",
        relative_path="list-1/summary.json",
        content_type="application/json",
        content_hash="a" * 64,
        size_bytes=12,
    )
    statements: list[str] = []

    def traced_connect():
        connection = connect_sqlite(
            repository.db_path,
            foreign_keys=True,
        )
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(repository, "_connect", traced_connect)

    rows = repository.list_with_metadata(owner="alice", limit=20)

    assert [
        (item["job"].job_id, item["pinned"], item["artifact_count"])
        for item in rows
    ] == [
        ("list-2", False, 0),
        ("list-1", True, 1),
    ]
    reads = [
        " ".join(statement.split())
        for statement in statements
        if statement.lstrip().upper().startswith("SELECT")
    ]
    assert len(reads) == 1
    assert "USER_JOB_PINS" in reads[0].upper()
    assert "RESEARCH_JOB_ARTIFACTS" in reads[0].upper()


def test_repository_closes_connection_after_successful_read(
    tmp_path,
    monkeypatch,
) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    repository.ensure_schema()
    connections = []

    def traced_connect():
        connection = connect_sqlite(
            repository.db_path,
            foreign_keys=True,
        )
        connections.append(connection)
        return connection

    monkeypatch.setattr(repository, "_connect", traced_connect)

    assert repository.list(owner="alice") == []
    assert len(connections) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        connections[0].execute("SELECT 1")


def test_repository_closes_connection_after_failed_read(
    tmp_path,
    monkeypatch,
) -> None:
    repository = JobRepository(tmp_path / "missing-schema.sqlite")
    connections = []

    def traced_connect():
        connection = connect_sqlite(
            repository.db_path,
            foreign_keys=True,
        )
        connections.append(connection)
        return connection

    monkeypatch.setattr(repository, "_connect", traced_connect)

    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        repository.list(owner="alice")
    assert len(connections) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        connections[0].execute("SELECT 1")


def test_job_detail_uses_one_read_for_pin_and_run_identity(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "jobs.sqlite"
    with connect_sqlite(path) as connection:
        ensure_research_run_schema(connection)
        connection.execute(
            """
            INSERT INTO research_runs (
                run_id, owner, workspace_id, configuration_id,
                configuration_revision, kind, run_spec_version,
                run_spec_hash, run_spec_json, decision_contract_hash,
                methodology_hash, trial_plan_id, trial_plan_hash,
                trial_plan_version, trial_role, trial_stage,
                comparison_id, graph_instance_id, graph_branch_id,
                sample_ref, sample_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "run-1", "alice", "workspace-1", "configuration-1",
                1, "backtest", 2, _record("identity").run_spec_hash,
                "{}", "1" * 64, "2" * 64, "trial-plan-1",
                "3" * 64, 1, "selection", "selection",
                "baseline", "instance-1", "branch-1",
                "sample-1", "4" * 64, time.time(),
            ),
        )
    repository = JobRepository(path)
    repository.create(_record("detail-1"))
    repository.transition("detail-1", JobStatus.PLANNING)
    repository.set_execution_plan(
        "detail-1",
        plan={"products": []},
        notices=[],
        requires_confirmation=False,
    )
    repository.record_artifact(
        job_id="detail-1",
        name="net_returns",
        relative_path="detail-1/net_returns.parquet",
        content_type="application/x-parquet",
        content_hash="5" * 64,
        size_bytes=128,
    )
    repository.pin("detail-1", owner="alice")
    statements: list[str] = []

    def traced_connect():
        connection = connect_sqlite(path, foreign_keys=True)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(repository, "_connect", traced_connect)

    detail = repository.load_detail("detail-1", owner="alice")

    assert detail is not None
    assert detail["job"].job_id == "detail-1"
    assert detail["pinned"] is True
    assert detail["trial_binding"]["trial_plan_hash"] == "3" * 64
    assert detail["graph_binding"] == {
        "instance_id": "instance-1",
        "branch_id": "branch-1",
    }
    assert detail["identity_refs"] == {
        "contract_hash": "1" * 64,
        "methodology_hash": "2" * 64,
        "trial_plan_hash": "3" * 64,
        "run_spec_hash": _record("identity").run_spec_hash,
    }
    assert detail["active_artifacts"] == [{
        "name": "net_returns",
        "content_hash": "5" * 64,
        "content_type": "application/x-parquet",
        "size_bytes": 128,
    }]
    reads = [
        statement
        for statement in statements
        if statement.lstrip().upper().startswith("SELECT")
    ]
    assert len(reads) == 1


def test_repository_allows_one_step_job_and_one_replaceable_pin_per_user(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    repository.create(_record("step-1", step_mode=True))
    with pytest.raises(ValueError, match="step job already active"):
        repository.create(_record("step-2", step_mode=True))

    for job_id in ("normal-1", "normal-2"):
        repository.create(_record(job_id))
        repository.transition(job_id, JobStatus.PLANNING)
        repository.set_execution_plan(
            job_id,
            plan={"products": []},
            notices=[],
            requires_confirmation=False,
        )

    repository.pin("normal-1", owner="alice")
    repository.pin("normal-2", owner="alice")
    assert repository.pinned_job_id(owner="alice") == "normal-2"

    repository.transition("normal-2", JobStatus.RUNNING)
    assert repository.pinned_job_id(owner="alice") == ""


def test_cancel_is_immediate_before_running_and_durable_while_running(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    repository.create(_record("queued"))
    repository.transition("queued", JobStatus.PLANNING)
    repository.set_execution_plan(
        "queued", plan={"products": []}, notices=[], requires_confirmation=False
    )
    cancelled = repository.request_cancel(
        "queued", owner="alice", reason="explicit_cancel"
    )
    assert cancelled.status is JobStatus.CANCELLED
    assert cancelled.cancel_reason == "explicit_cancel"
    assert cancelled.terminal_assurance is not None
    assert cancelled.terminal_assurance.disposition == "not_usable"

    repository.create(_record("running"))
    repository.transition("running", JobStatus.PLANNING)
    repository.set_execution_plan(
        "running", plan={"products": []}, notices=[], requires_confirmation=False
    )
    repository.transition("running", JobStatus.RUNNING)
    assert repository.require("running").terminal_assurance is None
    requested = repository.request_cancel(
        "running", owner="alice", reason="explicit_cancel"
    )
    assert requested.status is JobStatus.RUNNING
    assert requested.cancel_requested_at is not None
    assert requested.terminal_assurance is None


@pytest.mark.parametrize("stage", ["submitted", "planning"])
def test_early_cancel_always_persists_not_usable_assurance(
    tmp_path,
    stage,
) -> None:
    repository = JobRepository(tmp_path / f"{stage}.sqlite")
    repository.create(_record(stage))
    if stage == "planning":
        repository.transition(stage, JobStatus.PLANNING)

    cancelled = repository.request_cancel(
        stage,
        owner="alice",
        reason="explicit_cancel",
    )

    assert cancelled.status is JobStatus.CANCELLED
    assert cancelled.terminal_assurance is not None
    assert cancelled.terminal_assurance.disposition == "not_usable"


def test_repository_tracks_artifact_metadata_and_user_storage_quota(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    repository.create(_record("artifact"))
    repository.record_artifact(
        job_id="artifact",
        name="result",
        relative_path="artifact/result.json",
        content_type="application/json",
        content_hash="abc",
        size_bytes=321,
    )
    repository.set_storage_quota(owner="alice", quota_bytes=300)

    assert repository.storage_usage(owner="alice") == 321
    assert repository.storage_quota(owner="alice", default_bytes=999) == 300
    assert repository.load_artifact(
        job_id="artifact", name="result", owner="alice"
    )["relative_path"] == "artifact/result.json"
    repository.mark_artifacts_deleted(job_id="artifact", owner="alice")
    assert repository.storage_usage(owner="alice") == 0


def test_repository_records_structured_job_input_metadata(tmp_path) -> None:
    repository = JobRepository(tmp_path / "job-inputs.sqlite")
    repository.create(_record("job-input"))

    stored = repository.record_artifact(
        job_id="job-input",
        name="strategy_source__example",
        relative_path="job-input/inputs/strategy_source/example.py",
        content_type="text/x-python",
        content_hash="abc",
        size_bytes=123,
        artifact_role="input",
        artifact_kind="strategy_source",
        file_name="actor.py",
        logical_path="strategies/demo/actor.py",
        title_zh="临时策略源码：strategies/demo/actor.py",
    )

    assert stored["artifact_role"] == "input"
    assert stored["artifact_kind"] == "strategy_source"
    assert stored["file_name"] == "actor.py"
    assert stored["logical_path"] == "strategies/demo/actor.py"
    assert stored["title_zh"] == "临时策略源码：strategies/demo/actor.py"
