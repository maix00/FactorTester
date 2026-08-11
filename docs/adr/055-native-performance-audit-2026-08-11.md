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

## Retention and memory audit

Full-retention runs intentionally keep the structured order lifecycle and audit
records. `tracemalloc` on the same ten-strategy/ten-product fixture measured
`120.54 MiB` at 500 bars (`9,990` orders, `64,361` audit records) and
`239.39 MiB` at 1,000 bars (`19,990` orders, `128,890` audit records). The
approximately 2× memory growth matches the retained object counts; this does
not show a history-dependent memory leak. Long jobs should use the existing
summary/streaming retention choices when full per-order inspection is not
required; changing full-retention semantics is outside this audit.

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

The historical-field path had a second, independent repeat: every timestamp
rebuilt the same exchange-clearing defaults mapping for every product, although
those defaults are product/rule inputs and do not vary with event time.
`MarketDataStore` now keeps a bounded, run-scoped cache keyed by product identity
and normalized requested field names. It is cleared when a new market-data
payload or coverage seed is published; the cached product reference prevents
`id` reuse. Historical values still take precedence—the cache only avoids
rebuilding the fallback defaults mapping.

In a focused 100-product × 2,000-snapshot helper benchmark, this path changed
from `0.1224 s` to `0.0771 s` (about 37% lower). This is a field-resolution
microbenchmark, not a claim that the complete backtest is 37% faster.

The settlement path had a separate, smaller repeated read: after applying a
fill, the same `DataMoney` cash value was converted to major units once for
realised P&L and again for the fill record and audit record. The implementation
now converts that post-fill value once and reuses the resulting scalar for all
three consumers. On the 300-bar, ten-strategy/ten-product fixture this reduced
`DataMoney.to_major` calls from `89,670` to `71,760` (the accounting values and
all emitted records were unchanged). Wall-clock medians were `1.0036 s` before
and `0.9896 s` after in that short run; two 1,000-bar repeats were within
measurement noise (`3.657/3.598 s` versus `3.664/3.609 s`). This is therefore
recorded as a bounded duplicate-conversion cleanup, not as a headline whole-run
speedup.

## Strategy/product dimension audit

The same 250-bar fixture was also measured while changing the number of
strategies and products. With ten products, median native times for 1, 2, 5,
and 10 strategies were `0.1558 s`, `0.2538 s`, `0.4586 s`, and `0.8267 s`.
That is a substantially sub-quadratic increase as strategy count grows. With
ten strategies, the non-degenerate product counts 2, 5, and 10 measured
`0.6953 s`, `0.7401 s`, and `0.8267 s`; the corresponding order counts were
`4,990`, `4,990`, and `4,990`, so the small increase is consistent with fixed
per-product preparation rather than a product-history leak. The one-product
case (`0.1101 s`) is not comparable: its single group never creates the
normal rebalance workload (only 10 orders and 70 audit records, versus 4,970
fills and about 31,000 audit records in the other cases).

No additional dimension-dependent superlinear component was identified in
this audit. The remaining cost is dominated by intentionally retained order
and audit records and by per-event cash/order processing.

One order-lifecycle path did have a conditional superlinear risk. Duplicate
fill-id validation in `OrderStore.record_fill` scanned the complete fill list
for that order on every partial fill. The store now creates a per-order set
only when the second fill arrives and uses that set for subsequent validation;
single-fill orders therefore pay no new index allocation. A direct 10,000-fill
partial-order benchmark changed from `0.989703 s` to `0.034831 s`, while a
full-engine 80-bar snapshot (including equity, positions, settlements, and
audit records) remained byte-identical with SHA-256
`30bba935b39dded48e6559bc2756cbf92aefc2fc10572c11eb92756c4de35eba`.
This removes a real liquidity/partial-fill (O(k^2)) failure mode rather than
only changing a microbenchmark.

The same audit found a lot-accounting variant of the same pattern. FIFO/LIFO/
HIFO consumed lots were removed one at a time from the underlying deque. For
LIFO and HIFO, removing from the far end made a 5,000-lot close repeatedly
scan the remaining queue: the direct benchmark was `0.733311 s`/`0.728922 s`
before and `0.001644 s`/`0.001665 s` after (LIFO/HIFO respectively), with the
same realised P&L and empty position. FIFO already removes from the near end
and remained in the same millisecond range. The new path records exhausted lot
identities and rebuilds the container once, preserving the original order of
all surviving lots and the offset filter semantics. The gold-standard
FIFO/LIFO/HIFO accounting suite and the full engine tests cover the result
invariant.

## Decision

Accept the two bounded caches, the lazy partial-fill index, and the batched
lot cleanup because they target measured repeated work and preserve the
field-default, routing, duplicate-detection, and cost-basis contracts. Do not
add another speculative cache from this audit. Any further optimization must
first demonstrate a repeated lookup or a per-event cost that increases with
the number of prior bars, then compare exact equity, position, target, and
order-audit outputs before and after the change.

## Verification

- 47 focused registry, workspace, client-manifest, release, and cache tests
  passed after the boundary cleanup.
- 814 native tests passed with the local pandas compatibility shim; two
  `LivePriceTableBuffer` assertions differ only in pandas 3.x timestamp unit
  (`ns`/`s` versus the test's `us`) and are unrelated to this change.
- Server tests were not executable in the available conda runtime because it
  lacks Flask and `cli_anything`; changed server modules were compile-checked
  and their SQLite behavior was verified directly.
