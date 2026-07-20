# ADR-039: Research Result Artifacts and User Quotas

## Status

Accepted.

## Context

Complete backtest, IC, and evaluation results can contain large curves and
details. Storing those JSON payloads in SQLite bloats the canonical metadata
store, while retaining every complete result by default consumes unbounded
disk. Asynchronous execution still needs a short-lived cross-process delivery
path even when the user did not request permanent retention.

## Decision

Every terminal job retains a compact result summary in SQLite. Complete curves,
trades, daily details, and diagnostics are retained only when the user explicitly
requests full-result storage. Large payloads live in a server-managed artifact
root with staging, temporary, and retained areas. Workers write staging files,
verify content hashes, and atomically promote them. Web requests never provide
arbitrary server paths; CLI may download a result to a client-side path.

Temporary delivery artifacts have a short TTL. Retained artifacts remain until
the user deletes them or an explicit, visible administrative policy applies.
Deleting a retained artifact preserves the job, RunSpec, ExecutionPlan, summary,
and a `deleted_by_user` artifact record.

Each user has a soft retained-byte quota. A job accepted while the user is under
quota may finish and retain its complete result even if that result exceeds the
quota. Once actual retained usage exceeds quota:

- running jobs continue;
- queued and planning jobs are cancelled with `storage_quota_exceeded`;
- paused jobs remain paused but cannot continue;
- new submissions are rejected until usage returns below quota.

No older result is silently deleted and accepted work is not downgraded to
summary-only. A server-wide hard free-space threshold still protects the host.
Artifact metadata is sufficient to calculate usage; no high-frequency byte
counter is required.

The personal Web interface and CLI expose usage, quota, largest retained
artifacts, per-job and bulk deletion, and concise remediation for quota errors.
Cleanup reconciles abandoned staging/temporary files and database/file
tombstones without deleting retained files that remain referenced.

## Consequences

- SQLite stores artifact metadata and compact summaries, never large result
  payloads.
- Full-result retention is an explicit per-job choice, with a run-level default
  that individual analyses may override.
- Historical jobs without retained artifacts remain useful for audit, workspace
  cloning, summary inspection, and explicit rerun.
