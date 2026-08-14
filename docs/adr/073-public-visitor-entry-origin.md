# ADR 073: Public visitor entry is ingress-scoped and redirects to the IP endpoint

## Status

Accepted

## Context

The public Manager is reachable both through the stable browser ingress
`https://eloquence-drizzly-fencing.ngrok-free.dev` and through its direct HTTPS
IP endpoint.  These are different browser origins.  The compliance page must
not accidentally advertise visitor mode on every public address, especially
the direct IP entry.

Visitor mode is the bounded anonymous projection that the local Manager
already exposes when `FACTORTESTER_REQUIRE_LOGIN_FOR_UI=0`: it can inspect the
server's newest twenty public test records, but it cannot submit authenticated
runs, inspect private account data, or download generated artifacts.

## Decision

1. A deployment explicitly lists browser ingress origins in
   `FACTORTESTER_PUBLIC_VISITOR_ORIGINS`.  The configured
   `FACTORTESTER_MANAGER_PUBLIC_ENDPOINT` is the visitor target, not an
   allowed display origin.  Therefore direct IP compliance pages never show
   the visitor entry unless an operator explicitly puts that IP in the
   ingress list.
2. The configured ingress compliance page links to the Manager's `/visitor`
   route.  The Manager creates a short-lived, single-use in-memory grant and
   redirects the browser to the configured HTTPS Manager endpoint, carrying
   only that grant and a safe local next path.
3. The IP endpoint consumes the grant and issues an origin-bound, short-lived
   visitor session cookie.  A manually supplied `?visitor=1`, an expired
   grant, a grant for another target, or a cookie on another origin does not
   enable visitor mode.
4. Visitor mode is represented by one `VisitorMode` capability object.  It
   uses the existing `__public_jobs__` projection when forwarding anonymous
   reads to a service, is capped at twenty server jobs, cannot submit work,
   and cannot obtain artifact-transfer authorization.  Existing route-level
   authentication checks remain in force for account, profile, settings,
   manager, and cross-server operations.
5. A login attempt from visitor mode returns a typed error and the web client
   returns to the compliance page with the visitor entry suppressed.

## Consequences

- The ngrok origin is only an ingress/choice page; the active visitor session
  lives on the public IP origin requested by the deployment.
- Direct IP access remains compliance-only until device authentication or a
  grant obtained through an explicitly configured ingress.
- Visitor grants and sessions are process-local anonymous state.  A Manager
  restart invalidates them and does not affect users, devices, PostgreSQL, or
  job records.
- The public task projection can expose recent task metadata and storage
  counters without exposing generated file bytes.

