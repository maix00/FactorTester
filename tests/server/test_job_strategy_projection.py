from __future__ import annotations

from server.jobs.models import JobRecord
from server.jobs.states import JobStatus


def test_job_summary_exposes_strategy_plan_without_source_text(monkeypatch, tmp_path) -> None:
    from server.services import transient_strategy_sources

    monkeypatch.setattr(
        transient_strategy_sources.Settings,
        "CACHE_DB_PATH",
        str(tmp_path / "cache.sqlite"),
    )
    scope = transient_strategy_sources.create_scope(
        owner="alice",
        entries=[{"path": "strategies/demo.py", "source_code": "secret"}],
    )
    job = JobRecord(
        job_id="job-1",
        run_id="run-1",
        owner="alice",
        workspace_id="ws-1",
        kind="backtest",
        status=JobStatus.SUBMITTED,
        job_spec={
            "transient_strategy_source_scope_id": scope["scope_id"],
            "run_spec": {
                "strategy_plan": [{
                    "source": "profile:strategies/demo.py",
                    "strategy_id": "demo",
                    "strategy_kind": "custom",
                }],
                "strategy_source_policy": {"mode": "transient_run_source"},
            },
        },
    )
    summary = job.summary()
    assert summary["strategy_specs"][0]["strategy_id"] == "demo"
    assert summary["strategy_source_policy"]["scope_status"] == "available"
    assert "secret" not in str(summary)
    transient_strategy_sources.cleanup_scope(scope["scope_id"])
