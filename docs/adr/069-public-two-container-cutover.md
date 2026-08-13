# ADR 069: Cut over the public host to two isolated containers

## Status

Accepted.

## Context

ADR 066 defines the local server container boundary and the public host's two
trust domains. The existing public host still runs FactorTester and PostgreSQL
as native system services, exposes PostgreSQL on host TCP 5432, and couples
release cleanup to mutable host paths. Issue #184 additionally requires
server-only `17998/17997` surfaces bound to FactorTester's WireGuard address.

## Decision

The public host is cut over to exactly `factortester-public` and
`postgresql-control`. Each container establishes and owns its own WireGuard
interface and root-only key. The application image embeds one full Git SHA and
runs no source watcher. PostgreSQL uses a named volume and a checked restore
from the native custom-format dump.

Public host mappings are limited to `7998`, `7997`, federation UDP `51820`, and
database-tunnel UDP `51821`. Main test port `8000`, PostgreSQL TCP `5432`, and
peer TCP `17998/17997` are not host-published. Port 8000 is loopback-only in the
FactorTester container and reached through Manager. Same-host database traffic
uses an internal Docker network. Peer listeners from Issue #184 bind only the
FactorTester WireGuard address inside its container.

Container startup does not depend on PostgreSQL health. This preserves the
Manager, existing local task state, and byte-plane availability when the
control database is down. Database-backed operations return their existing
degraded errors and recover after PostgreSQL reconnects.

The release verifier, rather than the container entrypoint, performs the
idempotent control-database schema migration and checks that the stored schema
version equals the application revision's declared version. A PostgreSQL
outage therefore does not restart or hide an already-running Manager, but the
release cannot be accepted as verified until migration and version validation
succeed.

The normal publisher uses incremental Git transfer and Docker layer caching.
Only after the new application passes runtime verification and a database
restore check does it append a verified deployment receipt and prune old
application releases. The default rollback depth is three verified revisions.
Pruning is allowlisted to the application's full-SHA image tags and matching
Git release worktrees; PostgreSQL images, volumes, backups, unrelated Docker
projects, and the global build cache are outside that operation. Cleanup
failures are reported without rolling back an already verified application.

Native service removal follows, rather than precedes, three checks: the
container database has the migrated schema/data, its own backup passes a test
restore, and Manager/data/main endpoints pass. A rollback dump is retained
outside the volume during the observation window.

## Consequences

- Application releases restart only FactorTester; PostgreSQL remains online.
- Public TCP 5432 and host-level 8000 disappear from the runtime surface.
- FactorTester and database peers can be revoked independently.
- Issue #184 is validated against the final WireGuard topology instead of a
  temporary SSH/NAT transport.
- Deleting old host runtimes is an explicit post-validation cleanup and cannot
  remove the container database volume.
