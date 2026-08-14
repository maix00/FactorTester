# ADR 081: Manager sessions use the existing local SQLite database

## Status

Accepted

## Context

PostgreSQL is the shared authority for accounts, organizations, devices, and
quotas, but an already-running Manager must be able to validate its existing
sessions while PostgreSQL is unavailable. The repository already gives each
Manager a local SQLite database configured by `.settings`; that database
contains the local account projection and other Manager-visible data.

The previous session implementation persisted token hashes and session
metadata in `sessions.json`. That format had no `created_at` or `last_seen_at`
lifecycle fields, rewrote the whole file for each change, and made cleanup and
concurrent access harder to reason about. Existing JSON sessions are not to be
silently imported into the new store.

## Decision

1. Add a dedicated `manager_sessions` table to the existing local SQLite file
   resolved from `Settings.CACHE_DB_PATH`. Do not create a second session-only
   SQLite file in the Manager state directory.
2. Store only the SHA-256 token hash, principal, role, authentication method,
   issuing origin, display alias, `created_at`, `last_seen_at`, and
   `expires_at`. The raw bearer token is never persisted.
3. Use a 30-day absolute session lifetime, refresh within the existing
   seven-day refresh window, touch `last_seen_at` at most once per minute, and
   remove expired or 45-day-idle sessions during startup and periodic access.
4. The Manager session store is local and independent of PostgreSQL. PostgreSQL
   recovery may restore central authority, but it is not required to validate
   an already-issued local session.
5. The application does not read or migrate `sessions.json`. After the SQLite
   release has been deployed and verified, the exact legacy file is deleted
   from each deployment state directory. A restricted backup may be retained
   separately for rollback audit purposes.
6. Device-key automatic login remains a separate challenge/signature flow.
   Successful device verification issues a Manager session, but a failure in
   the device flow must not be diagnosed as a session-store failure.

## Consequences

- Local account fallback and session validation use the same per-Manager SQLite
  persistence boundary while PostgreSQL is offline.
- The existing SQLite file receives one authentication table and three indexes;
  no session JSON file or raw token material remains in active use.
- Removing legacy JSON sessions invalidates their old cookies. Users must sign
  in again or complete device-key authentication after the cutover.
- A damaged or unavailable local SQLite file prevents local session fallback;
  the Manager should fail closed rather than consult PostgreSQL for a raw
  session token.
