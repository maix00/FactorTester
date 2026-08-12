# ADR 054: Public factor registry and client asset boundary

- Status: Accepted
- Date: 2026-08-11

## Context

The server checkout previously carried three repository-local mirrors:

- `Factors/` for public FactorFamily source;
- `client-sources/` for provider manifests and connector code;
- `client-adapters/` for client adapter packages.

The public factor source is already persisted in the SQLite
`factor_family_sources` registry. Client sources and adapters are owned by the
client distribution, not by the server runtime. Keeping repository mirrors
created two authorities and allowed a missing database row or stale release
cache to be silently masked by a local file.

## Decision

1. `factor_family_sources` is the only server authority for public
   FactorFamily source. Public catalog, metadata, group discovery, runtime
   loading, and data-dictionary scanning read that registry directly.
2. The repository-level `Factors/` compatibility fallback is removed. Public
   rows are not deleted when a local workspace file is missing.
3. `client-sources/` and `client-adapters/` are removed from the server
   checkout. Release embedding accepts explicit external roots for these
   assets; with no roots, it produces a provider-neutral runtime with no
   managed source or adapter directories.
4. Runtime cache keys include external client assets only when their roots are
   explicitly supplied. A cache containing unexpected source or adapter
   directories is rejected instead of being reused implicitly.
5. User factor workspaces continue to materialize public source under their
   own `public_factors/` directory. A super-admin push may update the public
   SQLite registry; that workspace is an authoring surface, not a server
   fallback.

## Consequences

- A public factor cannot become executable merely by appearing in the server
  working tree; it must be registered in SQLite.
- Client release builds that need provider assets must obtain them from the
  separate client distribution and pass those roots explicitly.
- Tests for public factors load the registered source, while client catalog and
  release tests use temporary external manifests/builders.
- Existing SQLite public rows remain intact; this change removes mirrors and
  fallback paths, not factor definitions.

## Verification

- The registry and deleted public mirror were compared before removal: 48
  public rows and 48 source files matched one-to-one.
- Focused factor-workspace, catalog, metadata, client-manifest, and release
  tests cover registry-only loading and optional external asset injection.
- The server is not restarted or deployed as part of this local repository
  change; runtime activation remains a separate maintenance operation.
