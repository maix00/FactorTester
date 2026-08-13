# ADR 059: Manager server module boundaries

## Status

Accepted; migration completed.

## Context

The former `scripts/worktree_flask_manager.py` combined the deployment entry
point, HTTP routing, authentication, federation, job selection, process
supervision, and HTML generation. Compatibility aliases temporarily preserved
that import namespace while the implementation moved into `server/manager/`.
Keeping those aliases after every internal caller had migrated would leave two
public names for each Manager module and allow deployments to drift back to the
retired entry point.

## Decision

New Manager server code belongs under `server/manager/`. The target layout is:

```text
server/manager/
  app.py                 # process bootstrap and lifecycle
  http/
    *_routes.py          # focused HTTP route families
    pages.py             # dependency-free HTML boundaries
    security.py          # transport, session, and access policy
  domain/
    devices.py           # device enrollment, challenge, and verification
    jobs.py              # task lookup and server/port selection
    federation.py        # peer registration and forwarding
  storage/
    control_db.py        # PostgreSQL control-plane repository
    sqlite.py            # local execution/index projections
  data_plane/
    app.py               # 7997 client + 17997 peer transfer process
  state/                 # routing, jobs, worktrees, sessions, processes
  web/                   # Manager Web shell and static modules
```

`server.manager.app` is the only Manager process entry point. ADR-068 replaced
the old artifact service with `server.manager.data_plane.app`, the sole
7997/17997 transfer-process entry point; its listeners expose disjoint client
and WireGuard peer routes.
All Manager imports use `server.manager.*`; the retired `scripts/worktree_*`
aliases and `/manager-legacy` page are removed. `runtime.py` is only the
composition root for `ManagerState` and `Handler`; route Implementation lives
in the focused modules under `server/manager/http/`.

The term *worktree* remains part of the domain: a Manager discovers and starts
feature worktrees and exposes them through `/api/worktrees`. Removing the old
script namespace does not remove that capability or the peer-routing protocol.

## Consequences

- Deployments and the local LaunchAgent use `python -m server.manager.app`.
- Device authentication pages can be tested without constructing Manager
  state or opening a database connection.
- Tests import the canonical Module directly, so a legacy namespace cannot
  conceal a missing or circular dependency.
- The HTTP dispatch Seam has one Interface and one implementation namespace;
  worktree execution and federated routing retain their existing behavior.
