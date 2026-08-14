# ADR 079: Profile projection cache during control-database outages

## Status

Accepted

## Context

PostgreSQL is the authoritative shared store for account, organization,
hierarchy, quota, device, and synchronized Profile metadata.  A Manager must
nevertheless keep serving local application state when the control database is
temporarily unreachable.  The public Manager also normally has no access to a
user's device-local Client root, so an empty PostgreSQL response cannot be
distinguished from an unsynchronized Profile unless the Manager keeps a local
projection.

## Decision

1. Every Manager stores a bounded, source-free Profile projection cache below
   its own `state_root/profile-cache`.  The cache is separate from the Client
   root and is written atomically with owner-only permissions.
2. Cache files are keyed by a SHA-256 digest of the authenticated principal;
   they contain only sanitized Profile metadata and pending Profile IDs.  Local
   paths, source code, credentials, session references, and access tokens are
   never written to this cache.
3. Profile sync writes the safe local projection first.  PostgreSQL success is
   reported as `status=synced`; a PostgreSQL outage is reported as
   `status=pending` and does not pretend that the global projection committed.
4. Profile reads merge local Client data, the safe cache, and PostgreSQL rows.
   Pending cache entries are retried and upserted when PostgreSQL becomes
   available; the cache remains usable if that retry fails.
5. The CLI exposes `factortester client profile sync [PROFILE_ID]`.  Bootstrap
   invokes the same authenticated sync path, while a Manager or database
   outage leaves the local Profile valid and reports the sync as pending.
6. This cache does not turn PostgreSQL into an optional authority for security
   mutations.  Existing Manager sessions may continue until their normal
   expiry.  New password/device authentication, registration, organization or
   quota changes remain dependent on the control database and must return a
   degraded error when it is unavailable; they must not be accepted locally
   and silently diverge between servers.

## Consequences

- A public or local Manager can still display an already synchronized Profile
  during a PostgreSQL outage.
- Recovery is idempotent: the next Profile read or explicit sync clears the
  pending marker after the PostgreSQL upsert succeeds.
- A stale cached projection can show metadata until PostgreSQL recovers, but it
  cannot grant a new account, device, quota, or organization privilege.
- The same pattern can later be applied to other bounded read projections,
  but raw credentials and authoritative account revocations must not be copied
  into an unbounded offline authorization cache without a separate decision.
