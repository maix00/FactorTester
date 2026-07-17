from __future__ import annotations

import time

from server.jobs.scheduling import LongLivedWorkerPool


RUNNERS = "tests.server.long_lived_worker_fakes"


def _collect(pool, predicate, *, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    messages = []
    while time.monotonic() < deadline:
        messages.extend(pool.poll(timeout=0.05))
        if predicate(messages):
            return messages
    raise AssertionError(f"worker messages timed out: {messages}")


def _finished(messages, job_id):
    return any(
        item.get("type") == "task_finished" and item.get("job_id") == job_id
        for item in messages
    )


def test_worker_process_is_reused_and_affinity_selects_warm_idle_worker() -> None:
    with LongLivedWorkerPool(size=2) as pool:
        first_pid = pool.submit(
            job_id="first",
            runner_path=f"{RUNNERS}:cpu_runner",
            payload={"loops": 20_000},
            cache_keys=["A.DAY1"],
        )
        _collect(pool, lambda rows: _finished(rows, "first"))

        second_pid = pool.submit(
            job_id="second",
            runner_path=f"{RUNNERS}:cpu_runner",
            payload={"loops": 20_000},
            cache_keys=["A.DAY1"],
        )
        messages = _collect(pool, lambda rows: _finished(rows, "second"))

    result = next(
        item for item in messages
        if item.get("event") == "result" and item.get("job_id") == "second"
    )
    assert first_pid == second_pid == result["data"]["pid"]


def test_pool_runs_cpu_jobs_in_multiple_real_processes() -> None:
    with LongLivedWorkerPool(size=2) as pool:
        pids = {
            pool.submit(
                job_id=job_id,
                runner_path=f"{RUNNERS}:cpu_runner",
                payload={"loops": 500_000},
            )
            for job_id in ("one", "two")
        }
        messages = _collect(
            pool,
            lambda rows: _finished(rows, "one") and _finished(rows, "two"),
        )

    result_pids = {
        item["data"]["pid"] for item in messages if item.get("event") == "result"
    }
    assert len(pids) == 2
    assert result_pids == pids


def test_cooperative_cancel_keeps_worker_and_forced_cancel_replaces_it() -> None:
    with LongLivedWorkerPool(size=1, cancel_grace_seconds=0.05) as pool:
        original_pid = pool.submit(
            job_id="cooperative",
            runner_path=f"{RUNNERS}:blocking_runner",
            payload={"seconds": 5},
        )
        _collect(
            pool,
            lambda rows: any(
                item.get("type") == "task_started" for item in rows
            ),
        )
        assert pool.request_cancel("cooperative") is True
        cooperative = _collect(pool, lambda rows: _finished(rows, "cooperative"))
        assert any(
            item.get("event") == "error" and item["data"].get("cancelled")
            for item in cooperative
        )

        reused_pid = pool.submit(
            job_id="forced",
            runner_path=f"{RUNNERS}:uncooperative_runner",
            payload={"seconds": 5},
        )
        assert reused_pid == original_pid
        _collect(
            pool,
            lambda rows: any(
                item.get("type") == "task_started"
                and item.get("job_id") == "forced"
                for item in rows
            ),
        )
        assert pool.request_cancel("forced") is True
        forced = _collect(
            pool,
            lambda rows: any(
                item.get("type") == "worker_terminated" for item in rows
            ),
        )
        replacement = pool.worker_snapshot()[0]

    assert any(item.get("job_id") == "forced" for item in forced)
    assert replacement["pid"] != original_pid
    assert replacement["alive"] is True


def test_crashed_worker_is_reported_and_replaced() -> None:
    with LongLivedWorkerPool(size=1) as pool:
        original_pid = pool.submit(
            job_id="crash",
            runner_path=f"{RUNNERS}:crash_runner",
            payload={"exitcode": 23},
        )
        messages = _collect(
            pool,
            lambda rows: any(
                item.get("type") == "worker_crashed" for item in rows
            ),
        )
        replacement = pool.worker_snapshot()[0]

    crash = next(item for item in messages if item.get("type") == "worker_crashed")
    assert crash["worker_pid"] == original_pid
    assert crash["worker_exitcode"] == 23
    assert replacement["pid"] != original_pid
    assert replacement["alive"] is True
