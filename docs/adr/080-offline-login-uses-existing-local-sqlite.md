# ADR 080: Offline login and Manager-scoped account identity

- Status: Accepted
- Date: 2026-08-14
- Scope: Manager password login, registration, and account identity

## Context

PostgreSQL is the authoritative control database for users, organizations,
hierarchy, quotas, and registered devices. An internal Manager can still be
reachable directly on port 7998 when PostgreSQL or the public Manager is down.
The repository already gives each deployment node a unified local SQLite
database from `.settings`; its existing `accounts` table contains the local
account rows and PBKDF2 password verifiers.

Manager nodes do not all own the same registration namespace. The internal
feature Manager manages `GTHT`; the public main Manager manages `default`.
Without an explicit deployment override, this scope is selected from the
Manager role. The canonical username grammar is
`organization@alias@numeric-suffix`; aliases are case-sensitive and cannot
contain `$` or `@`.

The local SQLite database is not continuously synchronized by this decision.
It is simply the local account data already present on that Manager. Adding a
second authentication cache or a device table would create another projection
to maintain and would make the failure behavior harder to reason about.

## Decision

1. When PostgreSQL is available, password and device authentication continue
   to use PostgreSQL as the authority.
2. A full canonical username is looked up exactly. An alias-only input is
   resolved only among accounts whose organization is in the current
   Manager's configured scope. `organization@alias` is the scoped shorthand
   form. Ambiguous aliases require the full canonical username; comparisons
   are case-sensitive.
3. Registration and offline registration require the requested organization
   to be in the Manager scope. A blank organization uses the first scoped
   organization. The local SQLite database must be writable; PostgreSQL is
   not required for the first local write.
4. If a password authentication request raises `ControlDatabaseError`, the
   Manager reads the existing local SQLite `accounts` table. A local account
   with a valid password verifier may log in; a missing account or wrong
   password is rejected.
5. If registration occurs while PostgreSQL is unavailable, the Manager writes
   the new row to the existing `accounts` table in one transaction with a
   small `pending_account_registrations` outbox row. The outbox is pushed
   lazily on the next request that can reach PostgreSQL; there is no realtime
   synchronization worker. Such an offline registration is a normal user,
   never a locally bootstrapped super-admin.
6. No authentication snapshot, lease metadata, or device cache table is
   created. The outbox is only for eventual delivery of explicitly created
   local registrations.
7. Device allow-list reads, device challenge verification, enrollment, and
   revocation require PostgreSQL. During a PostgreSQL outage they return an
   unavailable response rather than using stale device data.
8. Password changes, role/hierarchy changes, and quota mutations do not write
   local SQLite while PostgreSQL is configured. They require the control
   database administration path.
9. The local fallback only catches a control-database availability failure.
   It is not used for an invalid password, a disabled public device, or any
   other authorization denial.

## One-time identity migration and cleanup

The legacy `18717974771` account is migrated by
`scripts/migrate_account_identity.py`. The command is dry-run by default and
requires an explicit hashed manifest, `--delete-other-users`, a SQLite backup,
and a `pg_dump` backup before applying changes. It preserves the password salt
and verifier, changes the canonical identity to `GTHT@MaxJJW@<random-digits>`,
and updates organization, hierarchy, profile, quota, device, authorization,
and source references in both databases.

The apply step removes all other active central accounts and all other
non-empty values in explicitly user-owned local SQLite columns, including
orphaned rows no longer represented in `accounts`. Public service principals
such as `__public_jobs__` and `__public_graph__` are retained. Local
`device-registry.json`, `device-authorizations.json`, and `sessions.json` can
be included with one or more `--state-root` arguments; device public keys and
session token hashes are preserved while their username/principal is renamed.
Browser IndexedDB private keys are not server-readable and are intentionally
not copied or regenerated.

Principal workspace directories are only touched when an explicit
`--user-root-parent` is supplied. The target directory is renamed and other
active child directories are moved into the backup's `user-roots/` archive;
the command never silently guesses a data-disk location.

The migration process must run in the Manager network namespace that owns the
database WireGuard peer. On the current internal Docker node this is the
Manager container's database interface (10.79.0.2) connecting to the remote
database address (10.79.0.1:5432). The FactorTester federation address
(10.77.0.1) is not a PostgreSQL endpoint, and a host-level test from the Mac
is not a valid database-path test. The existing local 127.0.0.1:2222
SSH/Session-Manager forward is an operator maintenance transport; it is not a
public database or application port. Run the script with docker exec in the
Manager container, or use that maintenance transport only to establish an
explicitly scoped diagnostic tunnel.

## Consequences

Internal password login can continue without a live central database, as long
as the account already exists in that Manager's local SQLite. Public and
device-management behavior remains fail-closed while PostgreSQL is down.
Local account changes and central revocations are not propagated by this
fallback; they become authoritative again when PostgreSQL is available. No
additional ports, background connections, authentication/device
synchronization tables, or cache cleanup process are required; the only extra
row set is the explicit registration outbox.
