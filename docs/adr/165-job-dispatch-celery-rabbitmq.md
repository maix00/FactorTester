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
