# ADR 074: Public network summary and visitor catalog visibility

## Status

Accepted

## Context

The Manager home page is used from both an internal network and a public
Manager.  A client must not infer or hard-code the public address from its own
URL.  At the same time, a visitor needs a useful read-only view of public
factor metadata and of the data sources known to the federation.

The existing federation registry identified nodes mainly by `role`.  That is
not sufficient once more than one public Manager or more feature nodes are
added.  The public/private network scope must be explicit, while old registry
entries remain readable.

The public container's `.settings` already binds `data_dir` to `/data` and
`source_data_dirs.LocalCNFutures` to `/data/sources/LocalCNFutures`.  The
source path is therefore configuration-driven; a missing product-source
projection is not fixed by copying the data disk or mirroring SQLite.

## Decision

1. Federation registrations carry `public_server` and, for internal nodes,
   `internal_addresses`.  Old entries default `main` to public and `feat` to
   non-public for compatibility.  Internal addresses are private IPs only.
2. The home API returns separate `internal_server_addresses` and
   `public_server_addresses`.  The latter includes the current public Manager
   when applicable, is server-provided, and is capped at three online public
   nodes.  Legacy fields remain for Swift target switching.
3. The Web home page renders one IP address per line.  Empty lists render
   `无在线内网服务器` or `无在线公网服务器`; the client does not add ports or
   derive an address from the browser URL.
4. Visitor catalog responses expose all source descriptors and their provider
   overlay.  Each source is annotated separately as visible and fetchable.
   Internal-only providers remain visible as metadata but cannot be selected
   by visitor product, tree, contract, or market-data routes.  User product
   groups and factor sets remain private.
5. Visitor factor catalog uses the registered public factor source only and
   projects metadata without source code or workspace paths.  A visitor's
   task and artifact restrictions remain unchanged.
6. Device authentication still uses the registered public key.  Enrollment
   and last-seen IPs are audit fields and need not match.  Browser credentials
   remain origin-scoped by WebCrypto/IndexedDB: a key enrolled under the
   direct IP is not automatically readable under the ngrok origin.  When a
   configured ingress has no local credential, its compliance page redirects
   to the canonical public IP so the already-enrolled key can authenticate
   without copying the private key across origins.

## Consequences

- Adding a second public Manager does not require a client release or a
  hard-coded IP list.
- An internal source can be advertised without accidentally turning visitor
  metadata access into data-byte access.
- Public source data is fetchable only from a local public provider in this
  release.  A future cross-public-node data proxy can add an explicit remote
  fetch capability without weakening the visitor policy.
- The data disk remains the source of truth for LocalCNFutures.  Deployment
  should verify the mounted path and the source projection endpoint after a
  release.
