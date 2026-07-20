# ADR-038: Single-Host Research Scheduler and Data Affinity

## Status

Accepted.

## Context

Per-request child processes cannot share process-local market-data caches and
allow every Flask worker to create a competing scheduler. Backtest planning also
depends on an ordered chain: run window, frozen product selection, term-structure
expansion, source/frequency/field resolution, coverage, then data loading.

## Decision

The supported deployment is one host with SQLite WAL and a Unix domain socket.
A dedicated job daemon is the sole scheduler for a deployment. Flask owns only
authentication and HTTP/SSE projection. The local 7998 worktree manager
supervises an API/daemon/worker service bundle and injects deployment, source
revision, artifact root, and socket identity. Multiple hosts must not consume
the same SQLite queue.

Submission performs cheap validation only. A long-lived planner pool generates
an immutable DataRequirementPlan/ExecutionPlan by reusing the production Flow
semantics. Execution workers consume that plan and do not re-read mutable page
state or silently resolve a different plan. Relevant data-version changes while
queued trigger replanning; material changes require user confirmation.

Execution uses long-lived workers with bounded process-local, read-only caches.
Cache keys include authorization scope, source and schema versions, product,
frequency, fields, partition/window identity, adjustment policy, and relevant
term-structure/trading-rule versions. Concurrent loads use single-flight within
a worker. Workers report cache inventory to the daemon in memory only.

The scheduler is work-conserving and fair across users. Permission-derived
priority classes and reserved capacity are evaluated before bounded data
affinity. Priority never preempts running work. Without competing users, one
user may burst into otherwise idle workers. Each user may pin one queued job;
the pin wins over data affinity within that user's queue and is consumed when
the job starts. Unpinned jobs may be reordered only within bounded look-ahead
and maximum-wait constraints.

Working data is pinned while a job runs; reusable cache is LRU/idle-evictable.
Jobs larger than a normal worker cache budget use an exclusive large-job worker
and do not leave a reusable cache. Requests above the server hard memory limit
fail planning. Public immutable market data may be shared across users; private
data includes its authorization domain in the key.

Each user may have one non-terminal step-mode job. It retains the same worker
and job identity while paused. Paused work blocks ordinary daemon drain; force
restart marks it failed. Cooperative cancellation is attempted first; an
unresponsive worker is killed and replaced, losing only that worker's cache.

The 7998 manager supports normal, debug, and explicit debug-wait bundle modes.
API-only restart leaves daemon and running jobs intact. Protocol incompatibility
requires a drain/restart of the bundle. Native planner/execution children attach
through VS Code subprocess debugging; external conda engines require opt-in
debugpy support in their own environments.

## Consequences

- No public worker port is introduced.
- The daemon's bounded event broker supplies SSE progress without database
  writes; SQLite cancellation is the durable fallback and the Unix socket is the
  immediate notification path.
- A shared Arrow/mmap cache service is deferred until profiling proves that
  cross-worker duplicate loading remains material.
- Identical jobs are not coalesced. Only immutable input data is reused.
- A future multi-host deployment requires PostgreSQL-style queue locking, a
  broker, shared artifact storage, and a separately designed distributed cache.

