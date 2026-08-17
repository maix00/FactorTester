# ADR 102: Bounded password login from public visitor mode

## Status

Accepted

## Context

The public Manager exposes a deliberately limited visitor session so a
visitor can inspect the public task and catalog views.  The public deployment
also requires device-authenticated sessions for ordinary browser access.  A
visitor must not be able to turn that limited session into an arbitrary
account session, but a small number of explicitly approved ordinary users
need a password-login path for controlled testing.

## Decision

Add `FACTORTESTER_PUBLIC_VISITOR_LOGIN_ALLOWLIST`, defaulting to an empty
value.  A request may use password login while a valid visitor cookie is
active only when all of the following hold:

1. the request is on the public Manager's visitor origin and uses the normal
   secure transport check;
2. the submitted identifier resolves exactly, case-sensitively, to one
   allowlisted account (canonical username, `organization@alias`, or alias);
3. the account is active and has the ordinary `user` role with no admin flag.

The resulting session is recorded as `visitor-password`, bound to the
Manager origin, and accepted by the existing public origin gate.  The
visitor cookie is expired in the same response.  The visitor capability set,
registration policy, device enrollment, and Manager/admin permissions do not
change.

The current deployment allowlist is the non-secret value `testA`.  Account
hierarchy is separate data: `GTHT@testA@545963541963` remains an ordinary
user and is recorded as the parent of
`GTHT@MaxJJW@392452984564`.

## Consequences

- A deployment must opt in each account; a missing setting preserves the
  existing visitor-login rejection.
- Alias matching remains case-sensitive and ambiguous aliases fail closed.
- PostgreSQL remains the account authority when available; an existing
  Manager SQLite account row is used during the established database outage
  fallback.  No device or visitor-account cache table is introduced.
- The relationship helper is dry-run by default and requires an explicit
  backup before applying account data changes.
