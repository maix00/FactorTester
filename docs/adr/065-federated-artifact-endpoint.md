# ADR 065: Advertise a distinct federated artifact endpoint

## Status

Accepted.

## Context

ADR 057 assigns large generated and submitted files to the per-server 7997
data plane, while Manager-to-Manager control traffic stays on 7998. A direct
server can derive `https://host:7997` from its Manager endpoint. A reverse
tunnel cannot: the peer may reach the Manager through a peer-local port such
as 17998 and the artifact service through a different peer-local port such as
17997. Deriving 7997 from the Manager callback then points at the peer's own
loopback listener instead of the source server.

## Decision

1. Federation settings store an optional exact `artifact_endpoint` separately
   from the Manager `public_endpoint`.
2. Registration heartbeats advertise that exact endpoint when configured.
   When it is empty, the existing same-host 7997 derivation remains the
   default for directly reachable servers. Environment-managed deployments
   may supply the same value through `FACTORTESTER_ARTIFACT_PUBLIC_ENDPOINT`.
3. Reverse-tunnel deployments expose two independent channels: 17998 to the
   source Manager's 7998 control plane, and 17997 to its 7997 artifact data
   plane. Service execution ports remain private and are never tunneled.
4. The artifact endpoint carries only short-lived, job-scoped ticket requests;
   user sessions and Manager capability tokens remain on 7998.
5. The execution server signs the artifact ticket, but the requesting Manager
   rebuilds the returned download URL from its own registered
   `artifact_endpoint`. The execution server's local 7997 URL is not a
   routable authority for another host.

## Consequences

- Large downloads do not consume the 7998 control-plane tunnel.
- Each peer sees the endpoint that is reachable from its own network context,
  including peer-local loopback endpoints created by reverse SSH tunnels.
- Existing direct deployments need no configuration change.
- A deployment must keep its advertised artifact endpoint and tunnel/listener
  lifecycle aligned; health checks should verify both 7998 and 7997 paths.
