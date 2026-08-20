from __future__ import annotations

import hashlib
import time
from dataclasses import replace

import orjson

from server.jobs.models import JobRecord, SchedulingEntitlement
from server.jobs.repository import JobRepository
from server.jobs.scheduling import ResearchJobScheduler
from server.jobs.scheduling.result_projection import _compact_runtime_info_rows
from server.jobs.scheduling.worker_pool import (
    _bounded_summary,
    persisted_result_summary,
)
from server.jobs.states import JobStatus


RUNNERS = "tests.server.long_lived_worker_fakes"


def _record(
    job_id: str,
    *,
    runner: str = "planned_cpu_runner",
    owner: str = "alice",
    loops: int = 50_000,
    seconds: float | None = None,
) -> JobRecord:
    run_spec = {
        "workspace_id": "workspace-1",
        "products": ["A.DCE"],
    }
    job_spec = {
        "run_id": f"run-{job_id}",
        "run_spec": run_spec,
        "loops": loops,
        "product_selections": {
            "core": {
                "selected_paths": [
                    {"product": "A.DCE", "source": "CNFutures", "frequency": "DAY1"}
                ]
            }
        },
    }
    if seconds is not None:
        job_spec["seconds"] = seconds
    return JobRecord(
        job_id=job_id,
        run_id=f"run-{job_id}",
        owner=owner,
        workspace_id="workspace-1",
        kind="fake",
        status=JobStatus.SUBMITTED,
        deployment_id="test",
        source_revision="test-backend-revision",
        runner_path=f"{RUNNERS}:{runner}",
        job_spec=job_spec,
        run_spec_hash=hashlib.sha256(
            orjson.dumps(run_spec, option=orjson.OPT_SORT_KEYS)
        ).hexdigest(),
        entitlement=SchedulingEntitlement(max_concurrency=1),
        created_at=time.time(),
    )


def _drive(scheduler, repository, job_id, statuses, *, timeout=8.0):
    deadline = time.monotonic() + timeout
    seen = []
    while time.monotonic() < deadline:
        scheduler.tick()
        current = repository.require(job_id)
        seen.append(current.status)
        if current.status in statuses:
            return current, seen
        time.sleep(0.01)
    raise AssertionError(f"job did not reach {statuses}: {repository.require(job_id)}")


def test_scheduler_plans_and_executes_real_job_in_child_process(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    repository.create(_record("success"))

    with ResearchJobScheduler(
        repository=repository,
        deployment_id="test",
        planner_workers=1,
        execution_workers=1,
    ) as scheduler:
        completed, seen = _drive(
            scheduler, repository, "success", {JobStatus.SUCCEEDED}
        )
        events = scheduler.broker.read("success")

    assert JobStatus.PLANNING in seen
    assert JobStatus.RUNNING in seen
    assert completed.worker_pid is not None
    assert completed.worker_pid != 0
    assert completed.worker_exitcode is None
    assert completed.result_summary["success"] is True
    assert completed.result_summary["pid"] == completed.worker_pid
    assert len(completed.execution_plan["cache_keys"]) == 1
    assert "A.DCE" in completed.execution_plan["cache_keys"][0]
    assert completed.terminal_assurance is not None
    assert completed.terminal_assurance.disposition == "trusted"
    assert events["latest_progress"]["event"] == "progress"


def test_explicit_result_outputs_are_not_generated_during_planning(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    job = _record("declared-outputs", runner="blocking_runner", seconds=30)
    job.job_spec["output_requests"] = ["ic_series", "ic_statistics"]
    repository.create(job)

    with ResearchJobScheduler(
        repository=repository,
        deployment_id="test",
        planner_workers=1,
        execution_workers=1,
        result_artifact_root=str(tmp_path / "artifacts"),
    ) as scheduler:
        running, _ = _drive(
            scheduler,
            repository,
            "declared-outputs",
            {JobStatus.RUNNING, JobStatus.FAILED},
        )
        assert running.status is JobStatus.RUNNING
        assert not (tmp_path / "artifacts" / "declared-outputs").exists()
        repository.request_cancel(
            "declared-outputs",
            owner="alice",
            reason="test_complete",
        )
        _drive(scheduler, repository, "declared-outputs", {JobStatus.CANCELLED})


def test_live_progress_event_does_not_read_durable_repository(tmp_path, monkeypatch) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    with ResearchJobScheduler(
        repository=repository,
        deployment_id="test",
        planner_workers=1,
        execution_workers=1,
    ) as scheduler:
        monkeypatch.setattr(
            repository,
            "load",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("live progress must not read durable repository")
            ),
        )
        scheduler._handle_event(
            "live-only",
            "progress",
            {"completed": 1, "total": 2},
            stage="execution",
        )
        snapshot = scheduler.broker.read("live-only")

    assert snapshot["events"][0]["event"] == "progress"


def test_scheduler_respects_per_user_concurrency_and_runs_queued_job_next(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    repository.create(_record("first", runner="blocking_runner", seconds=30))
    repository.create(_record("second"))

    with ResearchJobScheduler(
        repository=repository,
        deployment_id="test",
        planner_workers=2,
        execution_workers=2,
    ) as scheduler:
        first, _ = _drive(scheduler, repository, "first", {JobStatus.RUNNING})
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            scheduler.tick()
            second = repository.require("second")
            if second.status is JobStatus.QUEUED:
                break
            time.sleep(0.01)
        assert first.status is JobStatus.RUNNING
        assert repository.require("second").status is JobStatus.QUEUED
        repository.request_cancel("first", owner="alice", reason="explicit_cancel")
        _drive(scheduler, repository, "first", {JobStatus.CANCELLED})
        second, _ = _drive(scheduler, repository, "second", {JobStatus.SUCCEEDED})

    assert second.status is JobStatus.SUCCEEDED


def test_pin_only_reorders_its_owner_queue_without_cross_user_priority(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    bob = replace(
        _record("bob-first", owner="bob", runner="blocking_runner", seconds=30),
        created_at=time.time() - 10,
        entitlement=SchedulingEntitlement(priority_class="standard", weight=1.0),
    )
    alice_first = _record("alice-first", owner="alice")
    alice_pinned = _record("alice-pinned", owner="alice")
    for job in (bob, alice_first, alice_pinned):
        repository.create(job)
        repository.transition(job.job_id, JobStatus.PLANNING, expected=JobStatus.SUBMITTED)
        repository.set_execution_plan(
            job.job_id, plan={"cache_keys": []}, notices=[], requires_confirmation=False,
        )
    repository.pin("alice-pinned", owner="alice")

    with ResearchJobScheduler(
        repository=repository,
        deployment_id="test",
        planner_workers=1,
        execution_workers=1,
    ) as scheduler:
        scheduler.tick()

        assert repository.require("bob-first").status is JobStatus.RUNNING
        assert repository.require("alice-pinned").status is JobStatus.QUEUED

        repository.request_cancel("bob-first", owner="bob", reason="test_complete")
        _drive(scheduler, repository, "bob-first", {JobStatus.CANCELLED})
        scheduler.tick()

        assert repository.require("alice-pinned").status is JobStatus.RUNNING
        assert repository.require("alice-first").status is JobStatus.QUEUED


def test_scheduler_persists_failure_cancel_and_worker_crash(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    repository.create(_record("cancel", runner="blocking_runner", seconds=30))
    repository.create(_record("crash", runner="crash_runner", owner="bob"))

    with ResearchJobScheduler(
        repository=repository,
        deployment_id="test",
        execution_workers=2,
        cancel_grace_seconds=0.05,
    ) as scheduler:
        _drive(scheduler, repository, "cancel", {JobStatus.RUNNING})
        repository.request_cancel("cancel", owner="alice", reason="explicit_cancel")
        cancelled, _ = _drive(
            scheduler, repository, "cancel", {JobStatus.CANCELLED}
        )
        crashed, _ = _drive(
            scheduler, repository, "crash", {JobStatus.FAILED}
        )

    assert cancelled.cancel_reason == "explicit_cancel"
    assert cancelled.error["cancelled"] is True
    assert cancelled.terminal_assurance is not None
    assert cancelled.terminal_assurance.disposition == "not_usable"
    assert crashed.error["code"] == "worker_crashed"
    assert crashed.worker_exitcode == 17
    assert crashed.terminal_assurance is not None
    assert crashed.terminal_assurance.disposition == "maintenance_required"
    assert "worker_crashed" in crashed.terminal_assurance.anomaly_codes


def test_cancel_requested_before_result_commit_wins_result_race(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    repository.create(_record(
        "cancel-race",
        runner="cancel_result_race_runner",
        seconds=30,
    ))

    with ResearchJobScheduler(
        repository=repository,
        deployment_id="test",
        execution_workers=1,
    ) as scheduler:
        _drive(scheduler, repository, "cancel-race", {JobStatus.RUNNING})
        repository.request_cancel(
            "cancel-race", owner="alice", reason="explicit_cancel"
        )
        cancelled, _ = _drive(
            scheduler, repository, "cancel-race", {JobStatus.CANCELLED}
        )

    assert cancelled.cancel_reason == "explicit_cancel"
    assert cancelled.error["code"] == "cancelled_before_result_commit"
    assert cancelled.result_summary is None


def test_full_result_uses_files_and_over_quota_cancels_waiting_not_running(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    first = _record("full", runner="artifact_runner")
    first = replace(
        first,
        retention_mode="full",
        job_spec={**first.job_spec, "size": 200_000},
    )
    repository.create(first)
    repository.create(_record("waiting"))
    repository.set_storage_quota(owner="alice", quota_bytes=1)
    artifact_dir = tmp_path / "artifacts"

    with ResearchJobScheduler(
        repository=repository,
        deployment_id="test",
        execution_workers=1,
        result_artifact_root=str(artifact_dir),
    ) as scheduler:
        completed, _ = _drive(
            scheduler, repository, "full", {JobStatus.SUCCEEDED}
        )
        waiting = repository.require("waiting")

    assert completed.status is JobStatus.SUCCEEDED
    assert completed.result_summary["summary_truncated"] is True
    assert "equity_curve" not in completed.result_summary
    assert completed.result_summary["equity_curve_points_persisted"] is False
    assert completed.result_summary["equity_curve_artifact"] == (
        "equity_curve_report"
    )
    assert len(orjson.dumps(completed.result_summary)) < 64 * 1024
    assert waiting.status is JobStatus.CANCELLED
    assert waiting.cancel_reason == "storage_quota_exceeded"
    artifacts = repository.list_artifacts(job_id="full", owner="alice")
    assert {item["name"] for item in artifacts} == {
        "details", "result", "equity_curve_report", "equity_curve_receipt",
        "equity_curve_data", "equity_curve_data_receipt",
    }
    curve = next(
        item for item in artifacts if item["name"] == "equity_curve_report"
    )
    assert curve["content_type"] == "image/svg+xml"
    assert curve["size_bytes"] < 100_000
    assert all((artifact_dir / item["relative_path"]).is_file() for item in artifacts)


def test_bounded_summary_preserves_web_equity_curve_contract() -> None:
    points = 20_000
    result = _bounded_summary({
        "success": True,
        "metrics": {"A1": {"Total Return": 1.0}},
        "groups": [{
            "key": "A1",
            "timestamps": list(range(points)),
            "total_equity": [100_000_000 + value for value in range(points)],
            "gross_returns": [0.001] * points,
            "strategy_diagnostics": {"large": "x" * 600_000},
        }],
        "engine_result": {"large": "y" * 600_000},
    }, max_bytes=64 * 1024)

    assert result["summary_truncated"] is True
    assert result["metrics"]["A1"]["Total Return"] == 1.0
    assert result["groups"][0]["key"] == "A1"
    assert result["groups"][0]["timestamps"][0] == 0
    assert result["groups"][0]["timestamps"][-1] == points - 1
    assert len(result["groups"][0]["timestamps"]) < points
    assert result["equity_curve_downsampled"] is True
    assert len(orjson.dumps(result)) <= 64 * 1024


def test_persisted_ic_summary_keeps_explicit_diagnostic_scalars() -> None:
    result = persisted_result_summary({
        "success": True,
        "ic_metric_selection": {
            "mode": "selected", "requested": ["core"],
            "excluded": [], "resolved": ["mean_ic"],
        },
        "forward_horizon_sampling": {
            "mode": "scale_aware", "source": "request",
            "resolved_horizons": ["MIN1", "HOUR1", "DAY1"],
        },
        "factors": [{
            "factor_alias": "F1",
            "ic_diagnostics_schema": "ic-diagnostics-v1",
            "rolling_ic": {
                "window": 60,
                "rolling_k_signals": [60],
                "span_definition": "endpoint_elapsed",
                "signal_interval_seconds": 60,
                "expected_endpoint_span_seconds": [3540],
                "expected_coverage_span_seconds": [3600],
                "mean_ic": [0.1] * 100,
            },
            "period_diagnostics": {
                "schema": "ic-period-diagnostics-v1",
                "periods": {
                    "hour": {
                        "rule": "hour", "min_signal_observations": 2,
                        "min_periods": 3, "n_periods_total": 4,
                        "n_periods_estimable": 4, "n_periods_hac_estimable": 4,
                        "period_estimability_status": "estimable",
                        "periods": [{"mean_ic": 0.1}] * 4,
                    },
                },
            },
            "ic_stats_by_forward_horizon": {
                "MIN1": {"0": {
                    "diagnostics_schema": "ic-diagnostics-v1",
                    "n_signal_observations": 100,
                    "mean_ic": 0.1,
                    "icir_signal": 0.5,
                    "t_stat_iid": 5.0,
                    "t_stat_hac": 3.0,
                    "effective_n_capped": 60.0,
                    "direction_rate": 0.6,
                }},
            },
        }],
    })

    factor = result["factors"][0]
    assert result["forward_horizon_sampling"]["mode"] == "scale_aware"
    assert result["forward_horizon_sampling"]["resolved_horizons"][-1] == "DAY1"
    assert result["ic_metric_selection"]["requested"] == ["core"]
    stats = factor["ic_stats_by_forward_horizon"]["MIN1"]["0"]
    assert stats["mean_ic"] == 0.1
    assert stats["t_stat_hac"] == 3.0
    assert stats["effective_n_capped"] == 60.0
    assert factor["period_diagnostics"]["periods"]["hour"]["n_periods_estimable"] == 4
    assert factor["rolling_ic"]["expected_endpoint_span_seconds"] == [3540]


def test_persisted_result_summary_replaces_curve_points_with_artifact_refs() -> None:
    result = persisted_result_summary({
        "success": True,
        "equity_curve_artifact_available": True,
        "metrics": {"A1": {"Sharpe": 1.2, "Max Drawdown": -0.08}},
        "groups": [{
            "key": "A1",
            "timestamps": list(range(20_000)),
            "total_equity": [100_000_000 + value for value in range(20_000)],
            "gross_returns": [0.001] * 20_000,
            "annualized_return": 0.18,
        }],
        "engine_result": {"opaque": "x" * 100_000},
    })

    assert result["metrics"]["A1"]["Sharpe"] == 1.2
    assert result["groups"] == [{
        "key": "A1",
        "annualized_return": 0.18,
        "equity_curve_points_persisted": False,
    }]
    assert result["equity_curve_artifact"] == "equity_curve_report"
    assert result["equity_curve_receipt_artifact"] == "equity_curve_receipt"
    assert "engine_result" not in result
    assert b"total_equity" not in orjson.dumps(result)
    assert len(orjson.dumps(result)) < 64 * 1024


def test_persisted_result_summary_preserves_runtime_profiles_before_large_groups() -> None:
    result = persisted_result_summary({
        "success": True,
        "runtime_info_rows": [{
            "code": "backtest_margin_execution_profile",
            "type": "性能",
            "status": "profiled",
            "details": {
                "orders_seen": 10_000,
                "over_limit_orders": 2_500,
                "over_limit_order_ratio": 0.25,
                "scaled_orders": 1_000,
                "stage_ms": {"find_scale": 123.4},
            },
        }],
        "groups": [{
            "key": "A1",
            "timestamps": list(range(20_000)),
            "total_equity": [100_000_000 + value for value in range(20_000)],
            "strategy_diagnostics": {"large": "x" * 100_000},
        }],
        "engine_result": {"opaque": "y" * 100_000},
    })

    row = result["runtime_info_rows"][0]
    assert row["code"] == "backtest_margin_execution_profile"
    assert row["details"]["over_limit_order_ratio"] == 0.25
    assert result["groups"][0]["key"] == "A1"
    assert len(orjson.dumps(result)) < 64 * 1024


def test_persisted_result_summary_keeps_terminal_performance_profile() -> None:
    rows = [
        {
            "code": "backtest_flow_profile",
            "type": "性能",
            "status": "profiled",
            "details": {"flow": f"flow-{index}", "total_ms": 100.0},
        }
        for index in range(160)
    ]
    rows.append({
        "code": "backtest_result_assembly_profile",
        "type": "性能",
        "status": "profiled",
        "details": {"phase": "result_assembly", "elapsed_ms": 321.0},
    })

    compacted = _compact_runtime_info_rows(rows, max_bytes=2_000)

    codes = [row["code"] for row in compacted]
    assert "backtest_result_assembly_profile" in codes
    assert len(orjson.dumps(compacted)) <= 2_000


def test_persisted_result_summary_keeps_compact_forward_ic_facts() -> None:
    result = persisted_result_summary({
        "success": True,
        "factors": [{
            "factor_alias": "Mm|H:4h|$F:30m",
            "primary_forward_return_horizon": "MIN30",
            "ic_stats_by_forward_horizon": {
                "MIN30": {"0": {
                    "mean": 0.01,
                    "IR": 0.2,
                    "t_stat": 2.0,
                    "se_iid": 0.003,
                    "hac_lag_formula": "formula",
                    "ic_series_ar1_half_life_seconds": 120.0,
                    "p90_ic": 0.04,
                }},
            },
            "forward_ic_half_life": {"status": "estimated", "duration": "HOUR1"},
            "forward_ic_half_life_exponential": {"status": "estimated", "half_life_seconds": 300.0},
            "ic_series_by_forward_horizon": [{"values": list(range(10_000))}],
        }],
    })

    factor = result["factors"][0]
    assert factor["factor_alias"] == "Mm|H:4h|$F:30m"
    assert factor["forward_ic_half_life"]["duration"] == "HOUR1"
    stats = factor["ic_stats_by_forward_horizon"]["MIN30"]["0"]
    assert stats["se_iid"] == 0.003
    assert stats["hac_lag_formula"] == "formula"
    assert stats["ic_series_ar1_half_life_seconds"] == 120.0
    assert stats["p90_ic"] == 0.04
    assert factor["forward_ic_half_life_exponential"]["half_life_seconds"] == 300.0
    assert "ic_series_by_forward_horizon" not in factor


def test_step_job_pauses_and_continues_in_same_worker_process(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    job = replace(_record("step", runner="pausing_runner"), step_mode=True)
    repository.create(job)

    with ResearchJobScheduler(
        repository=repository,
        deployment_id="test",
        execution_workers=1,
    ) as scheduler:
        first, _ = _drive(scheduler, repository, "step", {JobStatus.PAUSED})
        pid = first.worker_pid
        assert scheduler.continue_step("step", {"action": "continue"}) is True
        second, _ = _drive(scheduler, repository, "step", {JobStatus.PAUSED})
        assert second.worker_pid == pid
        assert scheduler.continue_step("step", {"action": "end"}) is True
        completed, _ = _drive(scheduler, repository, "step", {JobStatus.SUCCEEDED})

    assert completed.worker_pid == pid
    assert completed.result_summary["pid"] == pid
    assert completed.result_summary["seen"] == [0, 1]


def test_paused_step_job_cancels_and_releases_its_worker(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    repository.create(replace(
        _record("step-cancel", runner="pausing_runner"), step_mode=True
    ))

    with ResearchJobScheduler(
        repository=repository,
        deployment_id="test",
        execution_workers=1,
    ) as scheduler:
        paused, _ = _drive(
            scheduler, repository, "step-cancel", {JobStatus.PAUSED}
        )
        pid = paused.worker_pid
        repository.request_cancel(
            "step-cancel", owner="alice", reason="explicit_cancel"
        )
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            scheduler.tick()
            if scheduler.executors.worker_snapshot()[0]["job_id"] == "":
                break
            time.sleep(0.01)
        repository.create(_record("after-cancel"))
        completed, _ = _drive(
            scheduler, repository, "after-cancel", {JobStatus.SUCCEEDED}
        )

    cancelled = repository.require("step-cancel")
    assert cancelled.status is JobStatus.CANCELLED
    assert cancelled.terminal_assurance is not None
    assert cancelled.terminal_assurance.disposition == "not_usable"
    assert completed.worker_pid == pid


def test_drain_finishes_active_work_without_starting_queued_jobs(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    repository.create(_record("draining", runner="blocking_runner", seconds=0.2))
    repository.create(_record("held"))

    with ResearchJobScheduler(
        repository=repository,
        deployment_id="test",
        planner_workers=2,
        execution_workers=1,
    ) as scheduler:
        _drive(scheduler, repository, "draining", {JobStatus.RUNNING})
        deadline = time.monotonic() + 3
        while repository.require("held").status is not JobStatus.QUEUED:
            scheduler.tick()
            assert time.monotonic() < deadline
            time.sleep(0.01)
        scheduler.set_draining(True)
        finished, _ = _drive(
            scheduler, repository, "draining", {JobStatus.SUCCEEDED}
        )
        for _ in range(10):
            scheduler.tick()

    assert finished.status is JobStatus.SUCCEEDED
    assert repository.require("held").status is JobStatus.QUEUED
