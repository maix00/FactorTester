# ADR-030: External precomputed factor artifacts

- **Date:** 2026-07-17
- **Status:** accepted
- **Related:** ADR-022, ADR-025, issue #137

## Context

External research systems can produce a date-by-product factor table, but a
Parquet path alone is not a factor contract.  GTHT must retain product identity,
information time, execution time, source hashes, missing-value presence, and the
exact precomputed schedule used by native and isolated framework replay.

Daily external tables are indexed by trading day at midnight.  Midnight is not
an executable futures event and night-session calendar dates are not equivalent
to trading days.

## Decision

`PrecomputedFactorArtifact` is a read-only, factor-like input:

- it verifies the handoff and Parquet hashes before reading values;
- it accepts only normalized, timezone-naive trading-day indexes in v1;
- it resolves every external symbol explicitly to one unique GTHT Product;
- it rejects duplicate timestamps/products, infinity, all-missing panels,
  same-bar execution, and non-experimental cross-market claims;
- it exposes vectorized `evaluate()` but never claims to be `FactorExpr` or to
  support incremental execution;
- it constructs a per-run `FactorRunResult` with presence mask and provenance;
- it maps trading-day values onto the actual GTHT signal schedule derived from
  market data and `SignalAlign`.

`FactorSignalStore` retains provenance under the same schedule key as the
precomputed table. `PrecomputedFactorSource.from_artifact()` carries that same
table and provenance into framework adapter planning.

## Boundaries

The artifact producer remains outside GTHT. GTHT does not import Vibe-Trading,
does not execute external Python formulas, and does not trust producer labels
without verification.

The durable HTTP/CLI registration surface depends on issue #123's workspace/run/
job API being integrated into the target baseline. Until then, the shared
artifact and replay boundary is usable from Python but is not advertised as a
remote-client feature.

## Consequences

- Native and framework execution can share one verified factor table.
- Signal timing is causal and night-session trading-day semantics are retained.
- Existing FactorExpr evaluation is unchanged.
- Artifact registration, upload/storage policy, and frozen RunSpec metadata are
  a separate integration layer, not hidden inside the factor loader.
