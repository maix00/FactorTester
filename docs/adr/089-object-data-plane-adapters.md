# ADR 089: Object bytes use the 7997 data plane

## Status

Accepted — incremental implementation in #216

## Context

Account-domain synchronization and object transfer have different failure and
ownership requirements.  PostgreSQL and each Manager's account SQLite carry
small user-owned metadata, revisions, and outbox state.  Research report
attachments, publication assets, local-resource snapshots, factor source
files, Job submissions, and Job artifacts are larger, have one storage owner,
and must remain usable when PostgreSQL is unavailable.

The previous research publication path put bounded object bodies in
`content_base64` inside the 7998 JSON projection.  That made a metadata read
also carry file bytes and prevented the same transfer protocol from being
used by multiple storage Managers.

## Decision

Use two parallel but independent channels:

1. The account-domain channel keeps user, organization, Profile, factor
   manifest, product-category, and publication metadata in the Manager-local
   SQLite mirror and lazily synchronizes with PostgreSQL.  It is not in the
   byte-transfer critical path.
2. The object channel uses Manager 7998 for object identity, metadata,
   authorization, transfer records, and short-lived capabilities.  It uses
   Manager 7997 for the verified byte stream over the normal local or
   WireGuard route.
3. Every transfer identifies an opaque `object_kind` and `object_id` in
   addition to the legacy Job fields.  `ObjectOriginRegistry` selects a
   domain Origin Adapter; the Job artifact resolver remains the compatibility
   fallback.
4. A research publication is a two-phase operation.  The source-free
   projection is committed first.  Each asset, attachment, and local resource
   then receives an independent 7998 upload capability and is uploaded on
   7997.  The destination Adapter verifies the declared size and SHA-256 and
   atomically promotes the file into the publication's storage directory.
5. New publication clients must not send object bodies in the 7998 projection.
   Older `content_base64` projections remain accepted during migration, but
   the server strips them before storing the projection and does not expose
   them as a federated read response.
6. The storage Manager is authoritative for object bytes.  A remote reader
   obtains metadata through 7998 and asks its request-owning Manager for a
   7997 ticket; if the source Manager is unavailable, the read fails clearly.
   There is no implicit replica and no PostgreSQL byte copy.
7. Factor source has its own `factor_source` object kind, Origin Adapter, and
   Destination Adapter.  A Run context sent to a candidate executor carries
   only the canonical family reference, source policy, byte count, SHA-256,
   and storage Manager.  Before capability preflight, the origin Manager
   stages each source through its local 7997 upload endpoint; the destination
   commits it into its local factor-source SQLite table.  The executor then
   hydrates and revalidates the source before planning.  The direct full-source
   context remains available only to local compatibility callers and tests.

## Module boundaries

```text
server/manager/objects/
  models.py                         # object kinds and references
  references.py                     # opaque identity codecs
  origin.py                         # Origin Adapter registry
  destination.py                    # Destination Adapter registry
  adapters/factor_source.py         # factor source read/commit seam
  adapters/public_research.py      # publication read origin
  adapters/public_research_destination.py
                                    # verified publication promotion
server/manager/services/
  research_object_transfer.py       # metadata ticket -> 7997 read
  factor_source_transfer.py         # stage factor objects before remote Run
server/services/
  factor_source_objects.py          # source-free and origin-upload manifests
server/manager/http/
  object_transfer_routes.py         # 7998 object upload capabilities
tools/cli/.../public_research/
  object_store.py                   # publication object seam
  object_uploads.py                  # detach and hash client bodies
```

The Module seam keeps `runtime.py`, `federated_public_data.py`, and the data
plane process entry point from becoming storage-specific registries.  New
object families add an Origin/Destination Adapter and tests rather than a new
Manager-to-Manager transport.

## Consequences

- PostgreSQL downtime does not block a local object transfer whose Manager
  already has the local transfer record and storage file.
- A publication can be listed from metadata before its object bytes finish
  uploading; a missing body is reported as unavailable rather than silently
  copied through the control database.
- Uploads are individually retryable and idempotent by publication, object
  kind, object identity, and content hash.
- Remote factor execution fails during capability preflight when the source
  Manager or destination data plane is unavailable; it does not fall back to
  embedding source text in the 7998 run request.
- The legacy projection compatibility path can be removed after all Web,
  Swift, and CLI publishers use the object upload capability.
- The account-domain and object channels may be monitored and retried
  independently; neither is a second PostgreSQL port or a second database.
