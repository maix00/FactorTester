# ADR 165: Celery + RabbitMQ Job dispatch, transactional outbox, and worker boundary

## Status

Accepted for implementation on `fix/issue-443-nautilus-bridge`. This ADR adds a
dispatch layer; it does **not** replace FactorTester Job facts or the Nautilus
execution contract in ADR-162.

## Decision

FactorTester keeps the authoritative RunSpec, JobAttempt state machine,
progress/activity facts, cancellation intent and result/artifact storage.
Celery workers execute finite backtest jobs; RabbitMQ only transports a small,
versioned message.

```text
Manager / API
  -> one SQLite transaction: JobAttempt + dispatch outbox
  -> dispatcher publishes message -> RabbitMQ (publisher confirm)
  -> Celery worker claims by (job_id, attempt)
  -> Nautilus engine
  -> FactorTester progress/result write-back
```

The broker message contains only:

```text
schema_version, job_id, attempt, deployment_id,
run_spec_hash, job_spec_hash
```

It must never contain market arrays, DataFrames, FactorExpr objects, full RunSpec
payloads or result artifacts. Workers read frozen references from storage.

## Multi-server and multi-port routing

One shared RabbitMQ broker may serve local Docker and public servers, but each
Job is owned by exactly one `(deployment_id, service_port)` target.  The
message carries both fields (schema v2).  The dispatcher publishes to a direct
exchange with routing key/queue:

```text
factortester.jobs.<deployment_id>.<service_port>
```

Each target binds its own worker queue on the shared broker.  The worker also
checks the message target before claiming and returns `wrong_target` without a
DB claim.  This is defense in depth; a misbound consumer must not execute
another server's Job against the wrong SQLite/RunSpec store.

A single logical queue with consumers filtering after dequeue is rejected for
multi-server deployment: a wrong consumer would have to reject/requeue and
could starve the correct target.

## Outbox contract

`research_job_dispatch_outbox` is written in the same transaction as the Job's
transition to `queued` (or `awaiting_confirmation` approval). Rows are keyed by
`(job_id, attempt)` and carry a lease:

```text
pending -> publishing -> sent
                     \-> failed -> pending (backoff) | dead
```

- dispatcher claims with `BEGIN IMMEDIATE` and a lease;
- broker confirm is required before `sent`;
- duplicate publish/consume is expected;
- worker atomically claims JobAttempt before doing work;
- result writes are idempotent by `(job_id, attempt)`;
- JSON serialization only, never pickle;
- retry count is bounded; exhausted rows become `dead`, not infinite retries.

## Local multi-port harness

`deploy/docker/job-dispatch/compose.yaml` runs one RabbitMQ broker and two
workers for `local-docker` ports 8000/8001.  Queues are target-scoped; the
workers share a state/data mount only because they are the same server.  The
harness is optional and not a production deployment.  Compose validation:
`docker compose ... config` exits 0.  A live run still requires Docker daemon
and the approved Nautilus executor.

Live local check (2026-10-25, fake executor only): RabbitMQ 3.13 container;
two queued Jobs for `local-docker` ports 8000/8001; dispatcher published both
target queues; the 8001 worker consumed only the 8001 message, wrote
`succeeded` and progress, while 8000 remained queued with one message.  This
proves broker routing/target isolation, not Nautilus execution.

Additional live checks (fake executor only): publishing the same message twice
produced one `succeeded` execution and one `duplicate` result; killing the
worker during a 30s task left the Job RUNNING until its 8s lease expired, then
`recover_expired_leases` marked it `failed/worker_lease_expired`; cancelling a
running Job made the executor observe the boundary and close as `cancelled`
without a false failure.

## Worker boundary

Celery worker configuration starts with `prefetch_multiplier=1`, one process,
`task_acks_late=True` only after the duplicate-delivery path is tested, and a
container memory/CPU hard limit. Worker process recycling is not a substitute
for the container limit.

RabbitMQ deployment is private-network only, persistent queue/messages with
publisher confirms. A single-node broker is not described as quorum
fault-tolerant.

Long-running paper/live Nautilus `TradingNode` processes are supervised outside
Celery; Celery may carry finite start/stop commands, never own the only liveness
signal for a live trading process.

## Migration gates

1. Freeze current Job/worker responsibilities; historical backtest Jobs remain
   read-only. New submissions select Nautilus RunSpec only.
2. Outbox + contract + focused tests (this change).
3. Publish/confirm dispatcher and idempotent worker claim.
4. Nautilus vertical slice: real submitted Job produces status/progress/result.
5. Capability validation per data source/parameter; reject unsupported fields at
   submission with the exact field and reason.
6. Cancellation/retry/worker-loss fault injection.
7. Resource limits and representative peak RSS/CPU measurements.
8. Web job status/progress/results read the same Job facts.
9. Remove legacy runner entry points only after 1–8 pass.

## Non-goals

- Celery does not own Job business state or history.
- RabbitMQ does not store market data.
- Celery does not remove Nautilus data copies or replace its execution semantics.
- No dual-write between legacy and Nautilus execution.

## Acceptance

- A crash before publish, after publish before `sent`, and duplicate delivery
  leave exactly one effective Job claim/result.
- Queued/running cancellation, worker failure, process kill, duplicate message,
  and result-write-before-ACK are covered by tests.
- API, worker claim and capability preview agree on runnable/rejected Jobs.
- No legacy backtest runner entry point remains at final cutover.

## Implementation progress (2026-10-25, local only)

- Added `server/jobs/dispatch/contract.py`: JSON-only `DispatchMessage`
  with schema version, safe job id, sha256 RunSpec/JobSpec references.
- Added `server/jobs/dispatch/outbox.py`: `research_job_dispatch_outbox`
  lease/claim/backoff/dead handling; duplicate-safe `(job_id, attempt)` key.
- Job creation/transition/approval now enqueue the dispatch row inside the
  same SQLite transaction. Jobs without `run_spec_hash` or `deployment_id`
  (legacy/demo paths) are not queued.
- Added `JobRepository.claim_attempt`: duplicate Celery deliveries cannot
  claim the same JobAttempt twice.
- Added `dispatcher.py`: lease -> RabbitMQ publish (Kombu) -> `sent`, or
  failure backoff; broker URL is `FACTORTESTER_BROKER_URL`.
- Focused tests: `tests/server/test_job_dispatch_outbox.py`,
  `tests/server/test_job_dispatch_runner.py` (14 passed at this commit).
- Added `worker.py`: claim -> execute -> terminal write contract; duplicate
  deliveries return `duplicate` without a second execution.
- Cancelling a queued Job terminally closes its unsent outbox row in the same
  transaction.
- Added `celery_app.py`: JSON task `factortester.execute_job`, one process,
  prefetch=1, no pickle. It resolves `FACTORTESTER_NAUTILUS_EXECUTOR`
  (`module:attribute`) before claiming a Job. A missing executor raises before
  claim, so the Job stays queued.
- Added `service.py`: guarded dispatcher loop; preflight refuses to publish
  unless the same deployment has a complete executor.
- Added `research_job_worker_leases`: claim inserts a 120s lease (configurable
  by `GTHT_JOB_LEASE_SECONDS`); the worker heartbeats during execution. The
  dispatcher startup fails expired RUNNING Jobs with `worker_lease_expired`
  instead of replaying them automatically.
- Added `ExecutionContext`: executors can read cancellation at batch boundaries
  and write monotonic progress snapshots (`research_job_progress`).
- A cancellation observed before terminal execution writes `cancelled`, not a
  false failure; an executor exception after a cancel request also closes as
  cancelled.
- `task_acks_late=False` is provisional. It avoids a permanently RUNNING Job
  when a worker dies after claim, at the cost of losing a message if the
  process dies before ACK; the outbox/dispatcher and worker-loss gate must be
  revisited before enabling acks_late or automatic redelivery.

## 2026-10-25 Nautilus executor availability

`server/services/nautilus_bridge/job_executor.py` now provides
`NautilusJobExecutor`, the default target for
`FACTORTESTER_NAUTILUS_EXECUTOR`.  It validates Job identity, deployment,
service port, job-spec hash, RunSpec hash/version and execution-plan hash
before invoking the approved process runner.  The dispatch preflight therefore
resolves the real executor instead of failing closed.  The fake executor probe
remains a transport/routing test and is not a Nautilus backtest.

## 2026-10-25 persistent public test stack

Deployed a non-production dispatch test stack on the public server:

```text
RabbitMQ: factortester-job-rabbit
  network: factortester-public_private
  data: /opt/factortester-container/job-dispatch-test/rabbitmq
workers: inside the existing app container, release 6b704449
  public-test:8000, public-test:8001, fake executor only
state: /state/job-dispatch-test/jobs.db
release: /opt/factortester-container/releases/audit-dispatch-6b70
```

The isolated `dispatch_probe` Job kind is enabled only with
`FACTORTESTER_ALLOW_DISPATCH_PROBE=1`. The smoke probe created one Job per
port; both reached `succeeded` with their own port in the result. Production
8000/8001 APIs remained healthy. This validates transport/routing/terminal
writes, not Nautilus execution. The workers and RabbitMQ remain deployed for
acceptance; they use an isolated DB and must not be described as production
backtest execution.

Redeployed through `scripts/server/deploy_dispatch_test.sh` at release
`5633ff8789a3` (deployment `public-accept3`): both ports again succeeded.  The
script initially passed the host release path to `docker exec -w`; that bug was
fixed by mapping the host worktree to `/opt/factortester/releases/...` inside
the app container.

## 2026-10-25 real Nautilus replay through Celery

A real NautilusTrader 2.0.0rc8 catalog replay was executed through the
Celery/RabbitMQ worker locally:

```text
8 CFFEX T2403 minute bars -> Nautilus BacktestEngine
reports: tearsheet.html, account.csv, orders.csv, fills.csv, positions.csv
result.engine = nautilus_trader
result.engine_version = 2.0.0rc8
Job status = succeeded
```

`NautilusJobExecutor` accepts an execution plan with
`kind=nautilus_catalog_replay`; catalog paths are confined to
`FACTORTESTER_NAUTILUS_CATALOG_ROOT`, receipts and hashes are verified by the
existing replay runner, and the Job result stores the replay receipt plus the
artifact directory. This is a real engine replay, not a factor-strategy
backtest and not a claim of factor performance. The public app image does not
ship the Nautilus runtime, so public acceptance of this path remains pending.

## 2026-10-25 Celery planning cutover

Manager-started services now set `FACTORTESTER_CELERY_PLANNING=1` and
`FACTORTESTER_CELERY_EXECUTION=1`.  Under those flags the legacy scheduler
does not plan, execute, or recover Jobs; `PlanningDispatcher` claims submitted
JobAttempts and publishes `factortester.jobs.plan` to the same target queue.
The plan task persists the execution plan and queues execution transactionally.
The legacy scheduler process remains only as a compatibility shell while its
remaining IPC operations are removed.

## 2026-10-25 real frozen-factor strategy through Celery

A real strategy-family Job was submitted through RabbitMQ and executed by a
Celery worker locally:

```text
factor: factor:v2:uMJYqbDQtQY81veVLREH51M3mnI0sskOFrh0wfyAT-A
alias: Mm|H:HA|L:LA|$F:1m
products: T2403, TL2406
strategy: cross_sectional_group split=2 group=1
```

Result:

```text
Job status: succeeded
bars: 16
publications.signal: 8
orders: 1
engine: nautilus_trader 2.0.0rc8
reports: tearsheet.html, orders.csv, fills.csv, positions.csv, account.csv
```

This used the public factor row/exported factor-library subset and the real
Nautilus engine; no synthetic factor or synthetic result was substituted.
The worker ran with a factor-library database path and the strategy executor.

## 2026-10-25 real strategy Job writes CouchDB report_ref

The same real frozen-factor strategy Job was rerun with a single worker
configured for CouchDB.  The Job completed and:

```text
Job status: succeeded
publications.signal: 8
orders: 1
report_ref: report:mm-celery-job:1
CouchDB GET report:mm-celery-job:1 -> 200
PostgreSQL research_jobs.report_ref -> report:mm-celery-job:1
```

The earlier empty report_ref was caused by a stale second worker without
CouchDB environment consuming the same queue; after stopping both old workers
and running one correctly configured worker, the full Celery -> Nautilus ->
CouchDB -> PostgreSQL projection passed.

## 2026-10-25 Nautilus retry from frozen plan

A failed Nautilus strategy Job was retried through the real retry API.  The
new Job copied the frozen execution plan, entered the queue, and executed on
a real Celery worker:

```text
retry_of: mm-celery-job
new job: 6cc81050031b440fb4a6e8e28b1cd448
status: succeeded
report_ref: report:6cc81050031b440fb4a6e8e28b1cd448:2
CouchDB GET -> 200
```

This validates retry for new Nautilus Jobs without re-planning the strategy
catalog.  Legacy backtests without a frozen plan still return 409.
