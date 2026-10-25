#!/usr/bin/env python3
"""Dispatch smoke test for one deployment/port pair.

Creates a queued backtest-shaped probe Job in an isolated SQLite file (never the
production DB unless explicitly passed), publishes its outbox row, and waits for
the target worker to reach a terminal Job state.

This is an acceptance probe, not a Nautilus backtest: it requires the target
worker's configured executor to accept the probe RunSpec reference.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from server.jobs.dispatch.dispatcher import DispatchRunner, KombuPublisher
from server.jobs.dispatch.outbox import DispatchOutbox
from server.jobs.models import JobRecord
from server.jobs.repository.sqlite import JobRepository
from server.jobs.states import JobStatus


def create_probe(repo: JobRepository, *, job_id: str, deployment: str, port: int) -> None:
    try:
        repo.require(job_id)
    except KeyError:
        repo.create(JobRecord(
            job_id=job_id,
            run_id=f"smoke-{job_id}",
            owner="__dispatch_smoke__",
            workspace_id="__dispatch_smoke__",
            kind="backtest",
            status=JobStatus.SUBMITTED,
            deployment_id=deployment,
            service_port=port,
            run_spec_hash="0" * 64,
            job_spec={"task_name": "dispatch smoke", "run_spec": {}},
        ))
        repo.transition(job_id, JobStatus.PLANNING)
        repo.transition(job_id, JobStatus.QUEUED)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--broker", required=True)
    parser.add_argument("--deployment", required=True)
    parser.add_argument("--port", type=int, action="append", required=True)
    parser.add_argument("--queue", default="factortester.jobs")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args(argv)
    repo = JobRepository(args.db)
    ids = []
    for port in args.port:
        job_id = f"dispatch-smoke-{args.deployment}-{port}"
        create_probe(repo, job_id=job_id, deployment=args.deployment, port=port)
        ids.append(job_id)
    outbox = DispatchOutbox(args.db)
    runner = DispatchRunner(
        outbox,
        KombuPublisher(args.broker, queue=args.queue),
        target_online=repo.worker_target_online,
    )
    dispatch_deadline = time.time() + args.timeout
    while time.time() < dispatch_deadline:
        result = runner.run_once(limit=max(1, len(args.port)))
        if result["sent"]:
            break
        time.sleep(2)
    deadline = time.time() + args.timeout
    terminal = {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}
    while time.time() < deadline:
        records = [repo.require(job_id) for job_id in ids]
        if all(record.status in terminal for record in records):
            print(json.dumps([
                {"job_id": r.job_id, "port": r.service_port,
                 "status": r.status.value, "result": r.result_summary,
                 "error": r.error}
                for r in records
            ], ensure_ascii=False, indent=2))
            return 0 if all(r.status is JobStatus.SUCCEEDED for r in records) else 1
        time.sleep(2)
    print(json.dumps({"error": "timeout", "jobs": ids}, ensure_ascii=False))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
