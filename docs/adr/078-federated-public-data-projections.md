# ADR 078: Federated public data projections

## Status

Accepted

## Context

The public Manager is a browser entry point, but a user's Profile metadata,
factor catalog, and shared research publication may be owned by an internal
Manager.  Mounting the internal Client home or copying source code into the
public container would leak device-local paths and make the public node a
second authority.  The existing cross-server task query also fan-outs to
registered Managers when the tab opens, so stale registrations and oversized
peer pages make the first view slow.

## Decision

1. Add one authenticated peer-control read surface for bounded `research` and
   `catalog` projections.  It is available only behind the existing Manager
   federation proxy token and has an explicit operation allow-list.
2. Public research list entries carry their owning `source_server_id`.  The
   public Manager reads report metadata from all live peers, then fetches a
   selected projection/chapter/asset on demand from the owning peer.  Report
   mirrors and bytes remain on the owner; PostgreSQL is not placed in this
   content path.
3. Profile responses use PostgreSQL's safe `control_profiles` projection when
   available and fall back to the local Client root.  The federated response
   strips device-local paths, source code, credentials, and session secrets.
4. Factor responses merge source-free public metadata for visitors and the
   authenticated principal's source-free library for logged-in users.  Factor
   source bodies remain on the owning node and are never returned by the peer
   projection.
5. Peer discovery uses only online leases for read-through requests.  A
   five-second in-process cache and requested-page-sized peer queries reduce
   repeated cross-server task-list latency; offline registrations remain
   status data but never block the request.

## Consequences

- The public Manager can display shared research, registered Profiles, and
  factor metadata without mirroring private client directories.
- A source node being offline makes its on-demand content unavailable, while
  already cached metadata remains bounded and clearly source-labelled.
- PostgreSQL remains the control-plane authority for migrated Profile metadata;
  it is not required for report bytes or task-list fan-out.
- A future persistent projection cache can replace the in-process cache without
  changing the peer operation contract.
