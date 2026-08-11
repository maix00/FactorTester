# ADR 055: Native backtest performance audit after runtime-boundary cleanup

- Status: Accepted (audit record)
- Date: 2026-08-11
- Related: ADR 051, ADR 052, ADR 053, ADR 054

## Scope

This audit checks whether removing the server's public-factor and client-asset
mirrors changes native backtest cost, and whether the existing hot path still
has history-dependent superlinear growth. It uses the existing full Flow
registry with synthetic data, ten strategies, and ten products. Only native
`run()` time is measured; process startup and pytest collection are excluded.

## Measurements

| Visible daily bars | Native run (s) | Relative to prior window |
| ---: | ---: | ---: |
| 250 | 0.8061 | — |
| 500 | 1.6220 | 2.01× |
| 1,000 | 3.2850 | 2.03× |
| 2,000 | 6.6268 | 2.02× |

The history-length ratios stay close to the expected 2× when the window
doubles. No new superlinear component is visible after the registry/client
boundary change.

A 500-day run with the opt-in cumulative flow profiler attributed the largest
totals to `apply_order_fill` (276.3 ms),
`schedule_order_execution` (212.1 ms),
`constrain_execution_to_ledger_cash` (156.0 ms), and
`construct_orders` (144.5 ms). Each was invoked once per expected event or
bar; no flow showed a growing per-event cost. Result assembly for the same
ten-strategy run was 24 ms and also doubled with history length.

## Incremental hot-path optimization

The next profile isolated repeated static strategy/product ledger lookups in
the replay path. `ledger_for_strategy_product` already retained an identity
cache, but every hit first rebuilt the StrategyBook/static-route checks. The
new path checks that cache directly when the current policy is still static
and no explicit order ledger is present. A dynamic `order_routing` policy is
checked before the fast return, so changing that policy cannot reuse a stale
route.

The paired control disables only this identity fast path; it uses the same
inputs, flows, and result retention. Median native run times were:

| Visible daily bars | Fast path (s) | Cache-disabled control (s) | Improvement |
| ---: | ---: | ---: | ---: |
| 500 | 0.5530 | 0.5631 | 1.79% |
| 1,000 | 1.1240 | 1.1597 | 3.08% |

On a deterministic 200-day, four-strategy/five-product run, the fast path and
the cache-disabled control produced byte-identical equity, display-equity,
position, notional, margin, target-trace, and order-audit snapshots. The
SHA-256 of both canonical snapshots was
`69423d23f6ad6fd043fa33c60bb29dcf9773a1d79369b6ca6c834df350549383`.

## Decision

Accept this bounded identity-cache optimization because it targets measured
repeated work and preserves exact outputs. Do not add another speculative
cache from this audit. Any further optimization must first demonstrate a
repeated lookup or a per-event cost that increases with the number of prior
bars, then compare exact equity, position, target, and order-audit outputs
before and after the change.

## Verification

- 47 focused registry, workspace, client-manifest, release, and cache tests
  passed after the boundary cleanup.
- 810 native tests passed with the local pandas compatibility shim; two
  `LivePriceTableBuffer` assertions differ only in pandas 3.x timestamp unit
  (`ns`/`s` versus the test's `us`) and are unrelated to this change.
- Server tests were not executable in the available conda runtime because it
  lacks Flask and `cli_anything`; changed server modules were compile-checked
  and their SQLite behavior was verified directly.
