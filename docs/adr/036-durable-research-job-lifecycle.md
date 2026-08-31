# ADR-036: Durable Research Job Lifecycle

## Status

Superseded by ADR-037, ADR-038, and ADR-039.

This document records the first durable-job design. Its view-owned
cancellation, persisted progress/events, renewable process slots, replay-based
step continuation, and TTL semantics are no longer current.

## Context

Long-running backtests and factor analyses previously belonged to a browser
page runtime. The HTTP request submitted an in-process closure that read mutable
page factors and wrote a single latest result. That made concurrent runs race,
made refresh/restart recovery unreliable, and prevented process isolation.

## Decision

Research execution uses four distinct identities:

- `session_uuid` authenticates HTTP requests. It does not own research data.
- `view_uuid` identifies one browser-tab observer lease. Refresh reclaims the
  same value from session storage; close marks it detaching.
- `workspace_id` owns research context and points to one mutable configuration.
- `run_id` owns one immutable RunSpec; each analysis is a durable `job_id` and
  retries or step continuations are linked attempts with new job IDs.

User configuration has one schema and one table. A workspace configuration and
a named reusable template are both `ResearchConfiguration` rows with different
roles. Editing overwrites the workspace row and increments an optimistic-lock
counter; it does not retain draft history. Saving or loading a template copies
the same canonical payload between configuration rows. Submitting copies that
payload into an immutable RunSpec, which is the historical execution record.

The submission boundary serializes the selected paths, factor aliases, settings,
time window, and analysis options. Workers receive only this RunSpec payload and
an importable runner path. They never receive Flask requests, sessions, browser
objects, or FactorTester instances, and do not consult mutable page state.

SQLite is canonical for job metadata, RunSpecs, status, cancellation requests,
bounded events, latest progress/manifest, checkpoints, errors, and artifact
metadata. Live process handles and SSE fanout remain process-local caches.
Process slots use renewable SQLite leases, so the configured concurrency limit
applies across Flask workers sharing the same database.

Cancellation is durable. The dispatching worker polls the canonical request and
forwards it to the child cancellation event, then terminates an unresponsive
worker after a grace interval. Dead dispatchers are reconciled to a readable
failed terminal record on startup.

Step mode persists a deterministic flow cursor and marks an attempt `paused`,
releasing its worker slot. `continue`, `until`, and `end` create explicit linked
attempts. Replay to the cursor may recompute prior deterministic flows; no
worker remains blocked waiting for UI input.

Observer-bound Web jobs are cancelled only after the view lease grace expires.
A refresh renews the same lease. CLI jobs default to durable and do not depend
on a view. Terminal records and artifacts remain queryable until TTL expiry;
expiry is represented explicitly rather than deletion.

## Consequences

- Web and CLI share `/api/test-authoring/workspaces`, `/api/runs`, and `/api/jobs`.
- Web and CLI share the same configuration/template schema and load/save API.
- Workspace revision numbers are counters, not stored historical snapshots.
- There is no direct job submission endpoint and no analysis-specific job API.
- SSE supports `Last-Event-ID` and `after`; a retained-event gap emits `reset`.
- Large artifact storage may move to files or object storage without changing
  job ownership; the database stores the artifact identity and integrity data.
- Deployments must share the configured SQLite database and artifact storage.
  Moving dispatch to a dedicated service later preserves the same API contract.
