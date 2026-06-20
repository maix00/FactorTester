# ADR 016: Provider-Scoped Derived Market Artifacts

## Status

Accepted

## Context

LocalCNFutures generated main-roll and term-structure files directly under the
global data directory. This prevents another local source from safely using the
same artifact names and offers no shared cross-platform lifecycle.

The historical term-structure file also mixed Wind primary and secondary
continuous mappings (`A.DCE` and `A_S.DCE`) with a maturity curve. Mapping
intervals were treated as maturity windows, so it was not a canonical listed
contract curve.

## Decision

- Artifacts are identified by `(provider, artifact_name, variant)`.
- Providers own configurable source-data and provider-namespaced artifact roots.
- Builders write staging files; the coordinator publishes with `os.replace`
  under a portable exclusive lock and persists state/coverage in SQLite.
- Flask startup performs ensure in a daemon thread and never waits for a build.
- `roller_info` represents primary/secondary continuous selection and adjustment.
- `term_structure:listed_contracts` comes from observed contract DAY1 rows;
  continuous mappings only annotate `IS_MAIN` and `IS_SECONDARY`.
- Product classification and data-series variants remain separate concerns.
- Canonical source files live under each provider's configured source root.
  Canonical generated files live only under that provider's artifact root;
  readers do not probe historical global paths or legacy filenames.

## Consequences

Future futures, options, rates, or other curve-bearing sources can register
builders without changing the coordinator. Large fact tables remain Parquet;
SQLite contains lifecycle and coverage metadata only.

The LocalCNFutures migration is complete. Migration utilities and read-time
fallbacks are deliberately absent, so a misplaced artifact fails visibly
instead of silently selecting stale data.
