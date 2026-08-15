# ADR 087: Shared Account-Domain Synchronization

## Status

Accepted — implemented in #214

## Context

Multiple Managers must expose the same user's account-owned metadata while
remaining usable when the central PostgreSQL service is temporarily
unavailable. Product categories are one example; the same problem applies to
product groups, registered Profiles, factor registrations, preferences, and
other small account records. Copying each feature directly between every pair
of Managers would create a separate conflict and retry protocol for each
feature.

## Decision

Use one account-domain synchronization protocol with per-entity adapters:

1. PostgreSQL is the cross-Manager authority for account metadata. Each
   Manager's existing account SQLite remains a durable local mirror and
   offline working copy.
2. The local mirror records pending changes in a shared outbox and a pull
   cursor. Operations are idempotent and carry an entity type, stable entity
   ID, principal ID, origin Manager ID, payload revision, and tombstone state.
3. Reads serve the local mirror first and lazily pull newer revisions when
   PostgreSQL is reachable. Local writes are immediately durable; they are
   pushed synchronously when possible or remain in the outbox until recovery.
   Real-time replication is not required.
4. Stable global user IDs and entity IDs are the merge keys. Usernames and
   display aliases are labels, not synchronization identities. Concurrent
   edits use optimistic revision checks and produce an explicit conflict
   instead of silently overwriting newer data.
5. Large or server-local objects (factor source files, generated artifacts,
   submissions, and research files) do not pass through PostgreSQL. Their
   metadata and ownership manifests use the account protocol; bytes use the
   authenticated 7997/WireGuard data plane. A research publication metadata
   row includes owner, Profile, visibility, authorized users, generation,
   projection hash, and storage Manager. Revoking a publication emits a
   tombstone; it does not delete a remote copy's bytes.
6. Runtime state is excluded from account synchronization: Manager sessions,
   live node capabilities, provider online status, and route selection remain
   local/federated projections.

## Consequences

- Product categories can be created while PostgreSQL is offline and become
  visible on other Managers after lazy synchronization.
- A data-source bundle remains distinct from its providers: one category may
  refer to `Local`, while the federated source descriptor lists every online
  server that provides `Local`.
- Each new account-owned feature adds an adapter and schema projection, not a
  new Manager-to-Manager synchronization protocol.
- The implementation is intentionally lazy rather than real-time: an affected
  view pulls after its per-principal cooldown, then flushes the local outbox.
  PostgreSQL downtime therefore leaves local login and local metadata reads
  available; new remote visibility waits for recovery.
- `account_domain_entities`, `account_domain_outbox`,
  `account_domain_cursors`, and `account_domain_conflicts` live in the existing
  Manager SQLite database. The corresponding PostgreSQL table is only a
  metadata authority. No second SQLite file, port, or peer listener is added.
- Product categories/groups, factor sets/parameter configurations, factor
  source manifests, Profiles, user/org/level metadata, factor research-run
  metadata, and uploaded/shared research publication metadata use the same
  local adapter seam. Source code, report projections, assets, and generated
  bytes remain on their owning storage Manager and are never copied into the
  account-domain tables. Job artifacts/submissions continue to use the
  existing authenticated 7997/WireGuard data plane; the existing public
  research read-through endpoint is intentionally unchanged by #214 and
  still needs a separate research-object data-plane adapter before its
  cross-Manager byte path can be described as 7997-native.
