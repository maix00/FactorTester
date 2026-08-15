# ADR 094: Server-owned management access and release scripts

## Status

Accepted

## Context

`factortester-manager` must remain usable on an administrator device that does
not have the FactorTester source tree. The CLI cannot infer whether a target is
local Docker, a remote SSH host, or a deployment transport from a hostname or
role. The existing Manager identity contract already has a validated,
non-secret `management_access` projection and a digest-checked script route,
but deployed settings had no entries and the asset directory had no scripts.

## Decision

1. Each Manager's colocated `.settings` is the source of truth for its own
   connection methods, endpoints, ports, profiles, capabilities, and local
   credential prerequisites.
2. The repository carries only small, reviewed, non-secret assets under
   `server/access-scripts/`. The Manager serves an asset only to an authorized
   Manager principal and verifies its declared SHA-256.
3. The CLI displays the declaration, checks only local readiness, and downloads
   a script with owner-only permissions. It never executes server-returned
   content and never receives a private key, password, token, or executable
   command from `.settings`.
4. Both local and public nodes expose the Docker inspection/restart helper. The
   public node additionally exposes bounded SSH inspection and exact-SHA
   release activation. Activation is still guarded by the existing remote
   backup, health, PostgreSQL-preservation, and rollback transaction.
5. WireGuard remains a server-to-server application transport declaration, not
   a Manager CLI host-management method. Peer keys, routes, and tunnel lifecycle
   stay deployment-owned.

## Consequences

- A clean administrator device can configure and authenticate the Manager, then
  discover the target-specific access workflow without a source checkout.
- A new device still needs its own Docker Context, SSH profile, or cloud
  credential; the server can describe the prerequisite but cannot manufacture
  it.
- Changing a public IP, SSH profile, or Docker Context requires updating that
  server's `.settings` and redeploying the declaration. Swift/research clients
  do not consume these host-management methods.
- Downloading a script is not an authorization to mutate a host. Operator
  approval and the target's host authorization remain separate boundaries.
