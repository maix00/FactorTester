# ADR 059: Manager server module boundaries

## Status

Accepted; migration is incremental.

## Context

`scripts/worktree_flask_manager.py` is both the deployment entry point and the
HTTP application. It has grown to contain routing, authentication, federation,
job selection, process supervision, and HTML generation. Adding public device
authentication directly to that file would make security changes difficult to
review and test.

## Decision

New Manager server code belongs under `server/manager/`. The target layout is:

```text
server/manager/
  app.py                 # process bootstrap and lifecycle
  http/
    handler.py           # HTTP route dispatch and response orchestration
    pages.py             # dependency-free HTML boundaries
    security.py          # transport, session, and access policy
  domain/
    devices.py           # device enrollment, challenge, and verification
    jobs.py              # task lookup and server/port selection
    federation.py        # peer registration and forwarding
  storage/
    postgres.py          # PostgreSQL control-plane repository
    sqlite.py            # local execution/index projections
  services/
    artifacts.py         # 7997 artifact data plane
    workers.py           # 8000 and feature worktree processes
```

The existing `scripts/worktree_*.py` files remain compatibility entry points.
Each migration moves one cohesive boundary, changes the legacy file to import
the new implementation, and keeps the old import names temporarily. The
production process starts at `server.manager.app`; it must not depend on a
legacy script path. Runtime implementation may still depend on legacy domain
services during this incremental migration, but new Manager code must not be
added to the compatibility file.

The first boundaries are now `server/manager/http/pages.py`,
`server/manager/domain/devices.py`, and
`server/manager/storage/control_db.py`. They own the public login/device-gate
pages, the device registry/challenge verifier, and the PostgreSQL repository.
The Manager runtime and process lifecycle now live in
`server/manager/runtime.py` and `server/manager/app.py`; the old
`scripts/worktree_flask_manager.py` path is a thin compatibility alias.
HTTP route dispatch is still grouped in `runtime.py` and is the next cohesive
boundary to split into `server/manager/http/handler.py`.

## Consequences

- Deployment commands and existing worktree paths continue to work during the
  migration.
- Device authentication pages can be tested without constructing Manager
  state or opening a database connection.
- The large legacy handler will shrink by boundary, rather than through one
  high-conflict rewrite.
- A compatibility shim is temporary and must be removed after all internal
  imports move to `server/manager/`.
