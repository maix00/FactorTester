# ADR 116: Canonical Shared Product Scope in Frozen Configurations

## Status

Accepted for Issue #279.

## Context

A frozen configuration repeated executable settings in analysis, local-setting,
and UI projections. Product selections also repeated `paths` as
`selected_paths`, remained under one analysis, and could depend on mutable
product-group/category rows. Freezing whole catalog and data-source projections
would solve that dependency but would copy volatile availability and the full
product catalog into every RunSpec.

## Decision

- `shared.product_selections` is the sole frozen representation of every
  product scope used by the selected analyses. Analyses and strategy groups
  retain only stable selection IDs.
- A selection stores one canonical `paths` array. It does not also store
  `selected_paths`.
- Existing product categories freeze stable metadata and a definition SHA-256.
  Their resolved selection paths already carry the execution semantics.
- Configuration-local categories freeze their complete item definitions because
  no external catalog row can recover them.
- Every referenced category freezes the stable declarations of its data-source
  families and members: identity, frequency, timezone, column mapping,
  capability dimensions, and naming scheme. Availability, product counts, and
  full catalog paths remain runtime state and are excluded.
- UI candidate catalogs and duplicated executable UI settings are not frozen.
  Equivalent factor aliases and repeated factor owner/family/parameter
  projections are canonicalized without deleting revision manifests or hashes.
- The origin Manager performs this freeze once before both capability preview
  and submission. Web, Swift, CLI, and federation therefore consume the same
  interface.
- Factor or executable category source is represented by an immutable content
  hash and artifact/source transfer reference. A RunSpec does not duplicate
  implementation text merely to make an object self-contained.

## Consequences

Historical execution does not depend on mutable product-group rows. Inline
objects remain template-safe without being inserted into account catalog tables.
Data-source availability is still checked on the selected execution node, while
the meaning of the requested source is frozen. Configuration size is bounded by
objects actually referenced by the run rather than by the size of the visible
catalog.
