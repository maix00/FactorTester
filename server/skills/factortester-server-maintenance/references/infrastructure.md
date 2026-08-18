# FactorTester infrastructure maintenance

Load this reference only for an authorized container, tunnel, peer-key, or
server-release case. It describes invariants and verification boundaries; it
does not publish a transport address or grant permission to change a server.

## Contents

- [Discover the server contract](#discover-the-server-contract)
- [FactorTester application planes](#factortester-application-planes)
- [Node and database identity](#node-and-database-identity)
- [Host and container lifecycle](#host-and-container-lifecycle)
- [Release and rollback](#release-and-rollback)
- [Failure and security boundaries](#failure-and-security-boundaries)

## Discover the server contract

Target-specific connection metadata belongs to the target server's colocated
`.settings` file. Read it through the authenticated Manager projection:

```bash
factortester-manager server inspect --json
factortester-manager server access --json
```

Use the returned `management_access` entries to select an already approved
operator tool. The entries are opaque declarations: they may expose a method
kind, profile, endpoint, port, and bounded capabilities, but never credentials
or executable commands. Do not hardcode a host, port, SSH alias, container
context, tunnel endpoint, or fallback route in this reference. An empty or
stale declaration is a blocker, not an invitation to guess.

The Manager CLI remains an application client. Its `jobs`, `artifacts`,
`storage`, `research-graph`, and `services` commands operate through the
FactorTester API. They do not operate the host or choose an infrastructure
transport.

The operator wrapper validates real Docker, Git, SSH, and FactorTester
backends; it is not a mock implementation. Do not create a duplicate
`cli-anything-factortester-server` harness merely to wrap those existing
commands.

## FactorTester application planes

The server identity response is authoritative for the client-visible
FactorTester control and data endpoints. Keep these planes separate:

- control plane: authentication, UI metadata, Job scheduling, service
  selection, and short-lived transfer authorization;
- data plane: capability-authorized artifact and submission bytes;
- execution services: Manager-owned worker instances selected through the
  control plane.

Do not expose an execution service merely because it is running. Do not send
artifact bytes through a control request when the server has issued a data
capability. Validate the selected server, Job, artifact name, size, expiry,
content hash, and transfer result.

The deployment declaration may advertise these protocol surfaces explicitly;
the labels are not permission to open a host firewall or to guess an endpoint:

| Surface | Declared transport | Boundary |
|---|---|---|
| client control | TCP 7998 | Web, Swift, and CLI Manager access |
| client data | TCP 7997 | capability-authorized object bytes |
| peer control | TCP 17998 | WireGuard-only Manager federation |
| peer data | TCP 17997 | WireGuard-only peer byte stream |
| FactorTester tunnel | UDP 51820 | deployment-owned WireGuard identity |
| PostgreSQL tunnel | UDP 51821 | separate database WireGuard identity |

The public client needs only 7998 and 7997. The peer surfaces remain private
to the overlay and must not be security-group ingress. The local operator SSH
forward may use local `2222`; it is not a public FactorTester port.

## Node and database identity

FactorTester nodes and the control database have independent identities and
lifecycles. A deployment coordinator owns the signed public inventory and
decides which nodes are eligible for an authenticated relation. PostgreSQL is
authority for its declared data domain; it is not a byte-transfer queue.

Each node retains its own private key with owner-only permissions. Only public
key material and bounded identity metadata may leave that node. Rotate a key
by staging the replacement, verifying the private health check and handshake,
then revoking the old declaration before removing old local material. Never
place private keys, registration bearers, database passwords, or Manager
sessions in Git, settings returned by the API, images, logs, or client bundles.

Peer discovery is not authentication. Establish a direct relation only when a
Job, data source, artifact, submission, or execution capability selects the
peer. Do not create one listener or one permanent request channel for every
known server.

When `management_access` declares `kind=wireguard`, it discloses an already
authorized server-to-server transport capability to the operator workflow. It
does not disclose private keys or authorize peer changes. The operator must
use the deployment's signed public inventory and verify the WireGuard
handshake, the FactorTester 7998 control plane, and the 7997 data plane as
separate checks. The Manager CLI and this Skill must not manufacture peers,
routes, endpoints, or tunnel configuration from a generic WireGuard label.

## Host and container lifecycle

Use only the operator tool selected from the target server's
`management_access` declaration. Its `--help` and status/plan operations
must be read before a mutation. Prefer a native, machine-readable receipt and
verify the resulting revision, identities, health checks, data roots, and
running services.

A status operation must not build, pull, publish, prune, delete a volume, or
restart a service. A mutating operation must be explicit, idempotent where
possible, and leave the last verified release recoverable. Keep server
settings, state roots, data roots, repositories, and node identities isolated
between nodes. Never mount a broad host parent or an unrestricted host
control socket into the application.

A FactorTester service restart is distinct from a host/container restart. Use
the Manager's application-level `services` command for the former. Use the
declared operator workflow for the latter, with explicit authorization and a
rollback plan.

Never use `docker system prune`, delete named PostgreSQL volumes, or remove a
release image/worktree outside the declared retention operation.

## Release and rollback

The public server must not fetch source from an unapproved remote. An
authorized publisher transfers a clean, exact revision through the declared
operator transport, verifies the remote revision, and activates an immutable
release. Build and dependency changes require an explicit build step; a
source-only reload must not silently rebuild or pull.

Before activation, record the source revision, current release, service
identity, database backup/restore target, and expected endpoint projection.
After activation, verify the revision, application control/data health,
private database reachability, distinct node identities, and absence of
unapproved public surfaces. If activation or verification fails, restore the
previous release and retain the database volume and external backup.

## Failure and security boundaries

- A healthy tunnel process does not prove a peer handshake or application
  health; verify each layer independently.
- Missing or expired peer metadata returns an explicit node-unavailable result.
  The application error is `node_unreachable`; never fall back to a guessed
  endpoint or unrelated application port.
- A PostgreSQL outage must not turn PostgreSQL into the artifact transfer
  queue or stop already-authorized local application behavior.
- Manager sessions, browser sessions, short-lived data capabilities, and peer
  tickets are separate credentials with separate expiry and scope.
- Never print private keys, bearer values, database URLs, source paths,
  proprietary data, or complete artifacts.
- Stop before mutation when the target, revision, identity, backup, rollback
  target, or authorization is ambiguous.
