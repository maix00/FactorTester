#!/usr/bin/env python3
"""Submit one real, bounded Nautilus catalog replay as a queued Job."""

from __future__ import annotations

import argparse
import json
import time
from decimal import Decimal
from itertools import islice
from pathlib import Path

from server.jobs.assurance import canonical_hash
from server.jobs.dispatch.dispatcher import DispatchRunner, KombuPublisher
from server.jobs.dispatch.outbox import DispatchOutbox
from server.jobs.models import JobRecord
from server.jobs.repository.sqlite import JobRepository
from server.jobs.states import JobStatus
from server.services.nautilus_bridge.catalog import stage_contract_minute_catalog
from server.services.nautilus_bridge.market_data import (
    FuturesContractSpec,
    iter_minute_bars,
)
from tests.nautilus_source_fixture import resolved_contract_minute_source
from server.services.research_run_identity import hash_run_spec


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--broker", required=True)
    parser.add_argument("--deployment", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--catalog-root", type=Path, required=True)
    parser.add_argument("--contract", default="CFFEX|F|T|2403")
    parser.add_argument("--code", default="T")
    parser.add_argument("--month", default="2403")
    parser.add_argument("--bars", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args(argv)
    bars = list(islice(iter_minute_bars(args.source, batch_size=4), args.bars))
    if len(bars) != args.bars:
        raise SystemExit("source has fewer bars than requested")
    args.catalog_root.mkdir(parents=True, exist_ok=True)
    catalog = args.catalog_root / f"job-replay-{args.contract.replace('|', '-')}"
    spec = FuturesContractSpec(
        instrument_code=f"{args.code}{args.month}", venue="CFFEX", underlying=args.code,
        price_increment=Decimal("0.005" if args.code == "T" else "0.01"),
        price_precision=3 if args.code == "T" else 2,
        multiplier=Decimal("10000"), currency="CNY",
        activation_ns=1, expiration_ns=2_000_000_000_000_000_000,
        margin_init=Decimal("0.02"), margin_maint=Decimal("0.02"),
        provenance="synthetic replay probe metadata, not exchange authority",
        resolved_source=resolved_contract_minute_source(),
    )
    receipt = stage_contract_minute_catalog(
        args.source, catalog, contract_uid=args.contract, instrument_spec=spec,
        start_ns=bars[0].clock.interval_end_ns,
        end_ns=bars[-1].clock.interval_end_ns,
        batch_bars=3, max_bars=args.bars,
    )
    run_spec = {"run_spec_version": 10}
    plan = {
        "plan_version": 1,
        "kind": "nautilus_catalog_replay",
        "catalog_inputs": [{
            "catalog_dir": str(catalog),
            "contract_uid": receipt.contract_uid,
        }],
        "max_input_bars": args.bars,
        "batch_minutes": 3,
    }
    job_id = f"nautilus-replay-{args.deployment}-{args.port}"
    repository = JobRepository(args.db)
    if repository.load(job_id) is None:
        repository.create(JobRecord(
            job_id=job_id, run_id=f"run-{job_id}", owner="__nautilus_smoke__",
            workspace_id="__nautilus_smoke__", kind="backtest",
            status=JobStatus.SUBMITTED, deployment_id=args.deployment,
            service_port=args.port,
            runner_path="server.modules.single_factor_test.process_runners:run_group",
            job_spec={"owner": "__nautilus_smoke__", "run_spec": run_spec},
            run_spec_hash=hash_run_spec(run_spec),
            execution_plan=plan, execution_plan_hash=canonical_hash(plan),
        ))
        repository.transition(job_id, JobStatus.PLANNING)
        repository.transition(job_id, JobStatus.QUEUED)
    outbox = DispatchOutbox(args.db)
    runner = DispatchRunner(
        outbox, KombuPublisher(args.broker, queue="factortester.jobs"),
        target_online=repository.worker_target_online,
    )
    end = time.time() + 30
    while time.time() < end:
        if runner.run_once(limit=1)["sent"]:
            break
        time.sleep(1)
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        record = repository.require(job_id)
        if record.status in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}:
            print(json.dumps({
                "job_id": job_id, "status": record.status.value,
                "result": record.result_summary, "error": record.error,
            }, ensure_ascii=False, indent=2))
            return 0 if record.status is JobStatus.SUCCEEDED else 1
        time.sleep(2)
    print(json.dumps({"error": "timeout", "job_id": job_id}))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
