# ADR 070: Bootstrap federation without singular-peer semantics

## Status

Accepted for Issue #185 on 2026-08-13.

## Context

The first two deployments used `peer_host`, `FACTORTESTER_PEER_ADDRESS`, and
`register_url` for values that actually belonged to the local node or to one
initial contact. Those names imply a permanent two-server relationship and do
not describe a future federation with several public and private servers.

WireGuard authenticates configured public keys and routes configured
`AllowedIPs`; it deliberately does not discover nodes or distribute keys.
Requiring an administrator to copy every new peer into every server would make
membership error-prone, while allowing an application Manager to invent peers
would collapse the deployment and application trust domains.

## Decision

### Stable node vocabulary

A `Federated Node` is keyed only by stable `server_id`. Each node advertises
its own client endpoints, overlay endpoints, execution ports, data-source
capabilities, load, revision, and lease. Public/private, main/feat, IP address,
and execution port are attributes rather than identities.

An `overlay_bind_address` or deployment `*_LOCAL_ADDRESS` is the address owned
by the current node's WireGuard interface. `Peer` is reserved for one remote
WireGuard or federation-directory record and is always part of a collection.
The old `--peer-host` option and schema-v1 `register_url` remain read-only
compatibility aliases during migration; new configuration is written using
`--overlay-bind-address` and `bootstrap_url`.

### One bootstrap, many discovered nodes

A non-public node configures one current `bootstrap_url` on private port
17998. The bootstrap is a seed and availability gateway, not a primary server.
Its authenticated registration response contains an expiring, credential-free
node directory keyed by `server_id`, so one registration can discover the
third and later servers. A directory entry carries signed identity/endpoint
metadata but never another node's proxy bearer. The legacy singular `peer`
response remains temporarily for the directly responding node and older
callers.

Discovery is not authentication. A node does not immediately register with
every directory entry. When selection of a port, capability, task destination,
artifact owner, or submission owner first requires a discovered node, the
requesting Manager verifies the signed directory entry and performs one direct
registration against that node's 17998 endpoint. Only then does the node enter
the authenticated route registry. One background scheduler renews the
configured bootstrap and the direct relationships that have actually been
activated; it does not create one listener/thread or eager heartbeat per
discovered node.

Only the response's `bootstrap_server_id` receives the measured request RTT.
Latency copied from another node is discarded because it was measured from a
different origin. Stale directory records expire through their leases.

### WireGuard provisioning and routing

WireGuard membership is managed by a deployment Module outside the Manager
application:

1. The joining deployment generates its private key locally with owner-only
   permissions and exports only its public key.
2. A cluster administrator or deployment coordinator allocates a unique
   tunnel address and approves the public record.
3. A signed, versioned inventory records `server_id`, tunnel kind
   (`factortester` or `database`), public key, address, reachable endpoint,
   allowed routes, generation, and enabled/revoked state. It never contains a
   private key, registration bearer, database password, or Manager session.
4. A privileged sidecar/deployment adapter validates the inventory and renders
   or applies WireGuard peer records. The unprivileged Manager cannot read the
   private key or mutate tunnel membership.

Public nodes with reachable UDP endpoints form direct public-to-public peers.
A private/NAT node keeps one active outbound public gateway and may retain
approved standby gateway metadata. The active public node routes overlay IP
packets between authorized peers. Application traffic still addresses the
destination node's 17998/17997 endpoint; the gateway performs only network
forwarding and never persists or mirrors artifact/submission bytes.

The first-enrollment bundle contains only the selected bootstrap's public key,
UDP endpoint, the joining node's allocated address, the cluster inventory
verification key, and the restricted federation registration credential.
Issue #185 currently uses one cluster-scoped bearer for direct application
registration; it is stored owner-only and never appears in discovery output.
Replacing it with per-node or one-time enrollment credentials is a later
security migration and is not claimed by this ADR. Operators do not fill one
form field per future peer.

### Authority and rotation

Private-key ownership remains with the deployment that uses the key. Public-key
distribution belongs to the cluster deployment coordinator, not PostgreSQL,
the FactorTester Manager, Git, or a container image. PostgreSQL may receive an
audit projection but is not required to bring up either tunnel.

Rotation generates a new local key, publishes a higher inventory generation,
applies both sides in a staged operation, verifies a handshake and the private
health endpoints, then removes the old public record and securely removes the
old local key/config. Revocation disables the inventory record first and is
propagated before local cleanup. FactorTester and database identities rotate
independently.

## Consequences

- Adding a server does not add a new user-managed settings field.
- A node can discover more than the one server used to bootstrap, while only
  nodes selected for actual work become authenticated routes.
- Public-key metadata can scale to any number of nodes without centralizing
  private keys.
- Bootstrap loss affects new directory refreshes. Activated direct relations
  continue renewing independently; never-activated directory records expire
  without creating credentials. Existing WireGuard state remains independent,
  and an approved standby can later become the active gateway.
- Routed private-node traffic may add one public-gateway network hop, but it
  avoids application-layer file relays, duplicate storage, SSH tunnels, and
  inbound NAT requirements.
