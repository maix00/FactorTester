# ADR 063: Separate server federation from control-database settings

## Status

Accepted.

## Context

The settings title “peer attachment” mixed two independent concerns. Manager
federation exchanges server endpoints, online execution ports, load, and data
source capabilities over port 7998. PostgreSQL on port 5432 is instead the
authoritative store for users, organizations, hierarchy, quotas, and public
device authorizations, including the small cross-Manager user-language
preference. A remote server's loopback database URL
(`127.0.0.1:5432`) cannot be copied unchanged to another Manager.

The old federation page also rendered stopped worktree ports as selectable,
even though registration payloads correctly filtered them before advertising
to a peer. That UI suggested an offline service could be offered remotely.

## Decision

1. Rename the user-facing “peer attachment” section to “server federation”.
   It configures only Manager-to-Manager registration, callback endpoints,
   heartbeat state, and task synchronization.
2. Show only currently online service ports in the federation settings page.
   Heartbeats dynamically advertise every online Manager-owned service and
   never advertise a stopped port. This supersedes ADR 056's manual per-port
   checkbox: an empty stored port selection now means automatic discovery,
   and the outward capability APIs also omit offline ports. A Manager with no
   execution port remains a valid online peer and may advertise ports in a
   later heartbeat.
3. Add a separate super-administrator control-database page. A local Manager
   may configure PostgreSQL host/IP, port, database, application role,
   write-only password, TLS mode, and timeout.
4. Validate connectivity, credentials, and schema before replacing the active
   control store. On success, account authentication, device registration,
   and authorization grants switch immediately. Newly started execution and
   artifact children receive the same URL; already-running children report a
   restart requirement instead of inheriting a process-global mutation.
5. Persist UI-managed credentials only in the Manager state directory with
   mode 0600. API responses return host, port, database, user, TLS mode, and a
   password-present boolean, never the password or raw URL.
6. A deployment-provided environment URL remains authoritative and read-only
   in the UI. This keeps the public systemd node under server configuration
   management while allowing a local LaunchAgent node to be configured by an
   authenticated super administrator.
7. Explicit user-language preferences are write-through PostgreSQL records.
   Managers cache them locally for five minutes, so normal page/API reads do
   not put PostgreSQL on every-request paths. A one-time device grant stores a
   concrete language snapshot so rendering at another origin remains stable.

## Consequences

- Device authorization grants created on an internal Manager can be consumed
  by the public Manager because both use one PostgreSQL authority.
- The database host shown on the remote node may be loopback, while another
  node must use the remote server's reachable IP or hostname.
- Federation and database failures are reported independently and no longer
  share a misleading settings title.
- Rotating an environment-managed database password remains an operational
  deployment action; rotating a UI-managed local password is available only
  to a super administrator over an accepted secure/private transport.
