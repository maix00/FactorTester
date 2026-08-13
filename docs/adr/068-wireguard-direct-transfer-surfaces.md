# ADR 068: WireGuard-direct transfer surfaces

## Status

Accepted and implemented on 2026-08-13. This decision supersedes ADR-067 and
ADR-065, replaces the cross-node parts of ADR-057, and updates the 7997 process
boundary described by ADR-059. ADR-070 clarifies bootstrap discovery and the
difference between application-direct overlay traffic and physical WG peers.

## Context

ADR-067 assumed that some FactorTester nodes would remain unreachable behind
NAT. That assumption required transfer-specific SSE commands, source-push and
destination-pull modes, a connection-owner Manager, relay rendezvous, and an
SSH reverse-tunnel compatibility path. The deployment topology now gives each
FactorTester server its own WireGuard identity. Every enrolled server node can
reach every other enrolled server node by private overlay address; ADR-070
allows a NAT node's encrypted IP packets to traverse one public WireGuard
gateway without creating an application-layer relay.

User clients still need stable public entry points. They must not learn a
WireGuard address or connect to an execution worktree port. PostgreSQL also has
an independent WireGuard/Compose lifecycle and must not become a dependency of
an already-authorized file stream.

## Decision

### Four fixed network surfaces

Each FactorTester node exposes four disjoint surfaces:

| Surface | Default | Audience | Responsibility |
|---|---:|---|---|
| client control | TCP 7998 | Web, Swift, CLI | UI, sessions, metadata, scheduling, short-lived transfer access |
| client data | TCP 7997 | Web, Swift, CLI | capability-authorized upload/download bytes |
| peer control | TCP 17998 on the WireGuard address | FactorTester nodes only | signed registration, service proxying, immutable Attempt context and peer tickets |
| peer data | TCP 17997 on the WireGuard address | FactorTester nodes only | origin reads and destination writes |

The public listeners and peer listeners have separate HTTP handlers. Client
routes do not exist on peer ports and peer routes do not exist on client ports.
The peer listeners require an explicitly configured private WireGuard bind
address; wildcard, loopback, multicast, and public bind addresses are rejected.

Execution ports such as 8000, 8141, and future issue-worktree ports remain
loopback services behind their owning Manager. A peer selects them through
17998 control forwarding and never opens them directly.

PostgreSQL uses a separate WireGuard identity and tunnel. It stores users,
organizations and levels, device identities, distributed quota facts, and
audit projections. It is not a transfer queue and never carries artifact or
submission bytes. FactorTester and PostgreSQL tunnels may therefore be upgraded
or recovered independently.

### Endpoint identity and discovery

One versioned node advertisement contains four explicit endpoints:

```text
client_control_endpoint
client_data_endpoint
peer_control_endpoint
peer_data_endpoint
```

No peer endpoint is derived from a public URL. Advertisement protocol v2 signs
the full endpoint set, node identity, issue time, nonce, and expiring lease with
the node's enrolled Ed25519 key. Receivers persist nonce and issuance state so
that tampering, replay, and delayed older heartbeats cannot extend or replace a
newer lease. Senders persist a strictly increasing issuance clock in local
SQLite so process restart and a small wall-clock rollback cannot reorder their
heartbeats. The configured bootstrap URL is validated as a private
WireGuard IP on port 17998; a public 7998 URL is rejected. Planning an Attempt
with a missing, expired, or invalid peer endpoint returns
`node_unreachable`; it never falls back to a public address, an SSH tunnel, or
a NAT traversal mode.

An Attempt stores an immutable snapshot of the relevant endpoints. A topology
change creates a new Attempt instead of changing a live route.

### Durable authority and lifecycle

The Manager that receives a client access request owns the Transfer in its
local `transfers.sqlite`. It stores the immutable request, Attempts, endpoint
snapshot, hashed capabilities, status, retry error, expected length, and
expected SHA-256. SQLite remains sufficient to authorize and finish a transfer
while PostgreSQL is unavailable.

The request lifecycle is:

```text
created -> planned -> dispatched -> streaming -> verifying -> completed
                                  -> retry_wait -> planned (new Attempt)
                                  -> failed / expired / cancelled
```

An idempotency key identifies one logical request. A failed Attempt is never
rewritten; retry creates the next ordinal with a new immutable route snapshot
and the verified destination resume offset.

### Download paths

A client first asks 7998 for access to one retained artifact. The response
contains a short-lived, role-scoped bearer and a URL on the selected Manager's
public 7997. Manager sessions and cookies are never sent to 7997.

For a local artifact:

```text
Client <- selected node :7997 <- local durable artifact
```

For a remote artifact:

```text
Client <- selected node :7997 <- WireGuard <- storage node :17997
```

The selected Manager imports immutable context to the storage node over signed
17998 control, obtains an origin-read ticket, and streams from 17997 with
backpressure. The selected node does not persist a relay copy. `HEAD` and one
strict HTTP byte range are supported. The origin verifies the retained file's
length and SHA-256 before serving any range.

### Upload paths

A client first asks 7998 for submission access, declaring exact length and
SHA-256. For a local destination, public 7997 writes private staging storage,
verifies the complete object, and atomically promotes it. For a remote
destination:

```text
Client -> selected node :7997 -> WireGuard -> storage node :17997
```

The selected node obtains a destination-write ticket over signed 17998 and
streams directly to the destination. Only the destination owns staging and the
final durable object; the selected node keeps no relay file. An interrupted
upload preserves only destination staging. A retry resumes from the verified
destination offset and still verifies the final length and SHA-256 before
atomic promotion.

### Authorization boundaries

Client capabilities use `client_download` or `client_upload`. Peer capabilities
use `origin_read` or `destination_write` and are bound to the authenticated
request-owner node. Every capability also binds Transfer ID, Attempt ID,
principal, byte window, expiry, and expected object identity. Persistent stores
hold bearer hashes, never bearer values.

Web, Swift, CLI, and peer transports reject redirects while carrying a transfer
bearer or node signature. Browser and Swift data sessions explicitly omit
Manager cookies, including when 7998 and 7997 share a hostname.

Node control requests are signed by an enrolled node key. Supplying a node ID
as a request parameter cannot change the authenticated identity.

### Module boundaries

The sole current data-plane entry point is
`server.manager.data_plane.app`. Its client and peer servers share only the
small transfer runtime and use disjoint handlers. Streaming, ranges, integrity,
lifecycle, local origins, direct pulls, local destinations, and direct pushes
remain separate semantic modules.

The old `server.manager.services.artifacts`, HMAC artifact-ticket codec,
`/v1/artifacts` routes, service-port byte routes, ZIP archive route, NAT
commands, SSE node agent/hub, inbox/outbox command stores, and relay rendezvous
are removed rather than kept as compatibility paths. Web, Swift, and CLI all
use 7998 access followed by cookie-free 7997 bytes.

## Failure behavior

- Missing or expired WireGuard endpoint: 7998 returns `node_unreachable`.
- Peer control/data timeout: the Attempt enters retry state; no public fallback
  or guessed endpoint is tried.
- Client interruption: the active Attempt fails; a new access request or the
  same idempotency key can create a retry Attempt.
- Destination commit followed by a lost final response: the destination reports
  an offset equal to the object length; a zero-byte Attempt re-verifies the
  promoted object and converges both nodes without copying the bytes again.
- Upload integrity mismatch: staging is preserved only for a valid resumable
  prefix; no final object is replaced.
- PostgreSQL outage: existing sessions and local identity caches continue to
  authorize local or known-peer transfers; global audit/quota projection waits
  for database recovery.
- Data-plane process restart: durable request, Attempt, ticket hash, and staging
  state remain in local storage; no in-memory rendezvous is required.
- Transfer SQLite v7 adds advertisement replay state additively. Existing v6
  requests and Attempts remain intact; the older NAT schema still follows the
  one-way archival migration before the version is advanced.

## Consequences

- All server pairs use one predictable application-visible overlay topology;
  public peers may connect physically end-to-end while a NAT node may route
  encrypted IP packets through one public gateway. There is no
  application-layer NAT transfer mode or per-public-server request listener.
- Public 7998 never carries artifact or submission bytes.
- Public clients need only 7998 and 7997. Extra 17998/17997 listeners are
  private implementation details inside the FactorTester WireGuard network.
- Files keep one durable owner, so distributed quota does not count relay
  mirrors.
- WireGuard is now required for cross-node transfer. Losing the overlay causes
  an explicit error instead of reduced-security fallback behavior.
