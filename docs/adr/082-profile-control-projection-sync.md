# ADR 082: Profile registration projects through Manager control plane

## Status

Accepted for implementation in Issue #208.

## Context

A local Profile is created on the Swift/CLI client and contains execution
metadata, Agent bindings, and local research references.  The public Manager
cannot mount that client directory.  Its Profile list is therefore a
sanitized projection stored in PostgreSQL `control_profiles`, with the
Manager-local projection cache used while PostgreSQL is unavailable.

The execution service and Manager are separate endpoints.  A Profile may use
an execution/worktree port such as 8000, 7999, or 8141; the control-plane
projection must always be sent to the Manager on 7998.  Treating the execution
URL as the database synchronization URL caused locally registered Profiles to
remain invisible on the public Manager.

## Decision

1. `client profile create` writes the local Profile first, then immediately
   sends its sanitized projection to `/api/client/profiles/sync` on Manager
   7998.  Swift passes its separately configured `ManagerConfig` URL when
   available; the CLI derives the same host and scheme with port 7998 only as
   a compatibility fallback.
2. Manager authentication uses the existing URL-scoped Manager bearer token
   in the CLI Keychain.  The older cookie session remains a compatibility
   fallback.  The client never connects directly to PostgreSQL.
3. A Manager or PostgreSQL outage does not roll back local Profile creation.
   The operation returns `server_visibility_pending`; when the Manager is
   reachable but PostgreSQL is down, its existing sanitized local projection
   cache records the pending row and flushes it after recovery.
4. Profile projection and research publication remain separate.  A Profile
   can be listed after synchronization without making any private research
   report public; only an explicitly uploaded and visible publication enters
   the shared research catalog.
5. The authenticated principal is checked before writing the projection.  A
   stale local principal is a migration problem and must not be silently
   rebound to another account.

## Consequences

- Profile registration becomes visible across Manager instances after the
  normal PostgreSQL/control-plane path succeeds.
- Execution URLs and report/artifact references retain their existing meaning;
  no execution port is rewritten to 7998.
- Offline local creation is available, but remote visibility is explicitly
  marked pending until synchronization succeeds.
- Existing local Profile identity migration remains an explicit migration
  operation and must be followed by a Profile sync; it is not performed by a
  network read or by guessing a principal from a display name.
