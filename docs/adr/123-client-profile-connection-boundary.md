# ADR 123: Keep local Profiles portable and bind servers to the client

## Status

Accepted

## Context

A local Profile describes a user's identity, workspaces, agents, and local
research state.  It is not a deployment or network configuration.  Earlier
Profile versions stored `server.base_url`, which caused a moved or retired
server port to break report-reference validation, Graph commands, and local
research creation even when the client had already been pointed at another
server.

Server-hosted Profiles are different: their runtime binding is represented by
the server-side runtime record (`runtime_kind=server` and an executor/server
identity).  That identity is stable metadata; a service port is not.

## Decision

- Client-owned local Profiles use schema version 10 and never contain a
  `server` endpoint field.
- The installed FactorTester client binds to one server through its global
  client configuration, an explicit command connection override, or a
  Manager-issued server-Agent capability.  Report authorities and Graph
  commands use that connection rather than reading a Profile endpoint.
- Manager synchronization derives the Manager address from the client
  connection or accepts an explicit Manager URL.  It never derives an
  address from Profile JSON.
- Legacy local Profiles are migrated once on load: their old endpoint is
  discarded and the normalized Profile is persisted.  Legacy endpoint data is
  not used as a fallback.
- Server-side runtime/projection code may retain a stable server identity for
  a server-hosted Profile, but must not require a port in that identity.

## Consequences

Changing the client's configured server does not move, duplicate, or rewrite
Profile workspaces and research reports.  A client must be configured before a
network operation that has no explicit endpoint; a clear configuration error
is preferable to silently reconnecting to a stale Profile port.

