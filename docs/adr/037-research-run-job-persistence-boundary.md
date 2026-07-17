# ADR-037: Research Run and Job Persistence Boundary

## Status

Accepted. Supersedes the lifecycle and persistence decisions in ADR-036.

## Context

An asynchronous research job must remain queryable when its submitting HTTP
request, browser page, CLI process, or Flask worker disappears. Persisting every
SSE activity and progress update made SQLite a high-frequency event transport,
slowed real backtests materially, and still did not make computation resumable.

The system also needs to distinguish the configuration requested by a user from
the concrete products, sources, fields, frequencies, and data versions resolved
for execution.

## Decision

Research ownership is `user -> ResearchWorkspace -> ResearchRun -> JobAttempt`.
A run freezes the requested RunSpec. Each analysis attempt has a `job_id` and a
compact, immutable ExecutionPlan produced asynchronously before execution.
Retries create a new attempt; rerunning a complete submission creates a new
run. A historical configuration never overwrites a workspace that has since
changed: restoring it creates a new workspace.

Jobs are durable and page-independent. Refresh, page close, SSE disconnect, CLI
exit, and API-only restart do not alter job state. Cancellation is explicit.
`page_uuid` and `view_uuid` remain transient UI/runtime identities and are not
job owners or cancellation keys.

SQLite WAL stores only low-frequency canonical facts:

- run/job identity, owner, workspace, kind, retry chain, and timestamps;
- frozen RunSpec/hash and compact ExecutionPlan/hash/notices;
- status, cancellation request/reason, execution/deployment metadata;
- permission-derived scheduling entitlement and the user's one queue pin;
- compact result summary or error/traceback;
- artifact identity, integrity, size, state, and user quota.

SQLite does not store progress, activity, SSE history, activity manifests,
worker heartbeats, process-slot renewals, cache inventory, DataFrames, complete
curves/details, or step engine state. Real-time progress and a bounded event
ring belong to the job daemon. On reconnect the daemon sends its current
in-memory snapshot; an unavailable cursor produces an explicit reset. Database
state remains authoritative for lifecycle and terminal summaries.

Job metadata and compact summaries do not expire silently. Users may explicitly
delete terminal history. Temporary transport/staging files are TTL-managed;
retained result policy is defined by ADR-039.

The state model is:

```text
submitted -> planning -> awaiting_confirmation -> queued -> running
                                      |                       |-> paused
                                      |                       |-> succeeded
                                      |                       |-> failed
                                      `---------------------->|-> cancelled
```

Normal auto resolution is informational. Semantic fallbacks are warnings.
Product exclusion, window clipping, or replacement of an explicit source or
frequency requires confirmation. Unsatisfied requirements fail planning.

## Consequences

- Web and CLI use the same workspace/run/job APIs.
- A personal task view can reconstruct status without browser-local state.
- Removing database event replay is intentional; progress continuity depends on
  the live daemon, while lifecycle continuity depends on SQLite.
- `test_job_events`, persisted latest progress/manifest, view-owned job leases,
  renewable SQLite process slots, and lifecycle-policy compatibility branches
  are retired.
- Step mode remains memory-resident in one worker. API restart is harmless, but
  daemon restart is not resumable and must fail explicitly.

