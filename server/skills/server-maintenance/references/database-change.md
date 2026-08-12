# Database maintenance

Use this reference for schema changes, canonical-owner migrations, retention
cleanup and orphan repair.

## Before mutation

- Obtain explicit authority for the exact case and database identity.
- Create a backup and run an integrity check.
- Produce a deterministic dry-run manifest with exact rows, refs, artifact
  paths, expected statement count, plan hash and rollback invariant.
- Reject cross-workspace, pinned, unknown or out-of-root references. Never
  discover deletion targets by guessing IDs or scanning arbitrary paths.

## Apply

- Revalidate database identity, revision and manifest hash immediately before
  applying.
- Use one bounded transaction for metadata changes.
- Delete artifacts only below the authorized root and exact relative paths.
  Record missing files as `missing_already`.
- Do not write per-read telemetry or add a table when an existing canonical
  owner, event or receipt can express the fact.

## Verify

Run foreign-key/reference checks, integrity check, row-count invariants and
hot-path SQL statement benchmarks. Persist one minimal purge/migration receipt
with plan hash, counts, actor, time and rollback/result status. Do not retain
complete database dumps or server paths in client-visible evidence.
