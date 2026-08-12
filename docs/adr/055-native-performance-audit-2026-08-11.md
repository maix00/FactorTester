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

The event-driven historical-field path had one further bounded repeat. A
FIELD_CHANGE event is the only supported mutation point for its current field
state, but replay timestamps include per-order/per-ledger causal epsilon
values. The old timestamp cache therefore rebuilt the same 25-product mapping
for each distinct event key. A run-scoped snapshot cache now keeps the
resolved mapping for the current field-state generation and invalidates it
when a FIELD_CHANGE is applied. A synthetic 20,000-event × 25-product helper
benchmark changed from `0.0840 s` to `0.0468 s`; the 3-month platform replay
remained within normal run-to-run noise (`123.964 s` before versus `125.735 s`
after), with identical metrics, groups, settings, and equity-curve artifact
hashes (`8e75c6c3…` and `d1a2d7d0…`). This is accepted as a bounded
helper/field-resolution optimization, not a claim of a whole-run speedup.

The same profile identified a more frequent scalar conversion cost in
`minor_units_to_major`: every minor-unit `DataMoney` scalar was first wrapped
in a temporary NumPy array. The scalar path now performs the equivalent
`numpy.float64 / scale` operation, while vector inputs retain the previous
conversion and live-view behavior. `DataMoney.to_major` also memoizes only
scalar derived values on the instance; mutable vector amounts are deliberately
not cached. The scalar return type remains `numpy.float64`.

The isolated 8-million-call microbenchmark changed from `4.06 s` for repeated
uncached conversion to `0.96 s` for the scalar conversion path; reusing one
scalar `DataMoney` object measured `0.64 s` before the scalar path and `0.61 s`
with the final path. A platform A/B using the frozen 10-group, 3-month
configuration produced byte-identical metrics and equity artifacts. The eight
pre-change runs had a mean of `125.15 s` (standard deviation `3.11 s`); three
final-candidate runs had a mean of `121.45 s` (standard deviation `1.02 s`).
The observed reduction is about `3.0%` on this host, so it is recorded as a
measured scalar conversion improvement, not a claim that every workload will
scale by the same percentage. The candidate and baseline metric digest was
`26c0adeec43e4e208b9893f14fe409045541a45ba35ee2ff59b4e32a8559784c`, and both
equity artifacts retained hashes
`8e75c6c3b238a83a92768d722be35d24ca9549b6d48c83683750054629a0fc76` and
`d1a2d7d0416229638fa2b4fb436f92d905616951f2af9831b1260a1b21081dcf`.

Wall-clock observations must be separated from engine time in this audit.
The Mac recorded repeated Maintenance Sleep intervals while an earlier long
job was reported as running; those intervals can inflate user-visible elapsed
time without adding Python CPU time. Job `started_at`/`finished_at`, worker
CPU, and the engine Flow profile are the authoritative runtime measurements.

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

The synthetic fixture did not expose the second issue found in the formal
platform replay: a futures rollover leaves zero-quantity ProductPosition
records in the ledger.  The target-sizing flow previously unioned those
historical keys into every signal, and the hard margin-limit projection copied
them repeatedly.  The number of such keys grows with the number of expired
contracts, so the cost can spike at rollover-heavy windows even though the
equity result is unchanged.

### Formal platform replay

The Friday failure was replayed through the 8180 platform deployment, not a
local direct call.  The frozen configuration was the original 10-strategy,
25-night-product run from source revision `f00fdad5e258fc6ba5b68e9d7eae11f6b738d303`:
native engine, automatic margin, infinite liquidity, summary retention,
2024-01-01 start, `MmRateOfChg|P:CA|N:5m|$F:5m|$Rev` plus `SgCCS|N:5m|$F:5m|$Rev`,
five groups per factor, and exchange fees.

The first platform replay showed the order-audit checksum path sorting and
JSON-encoding every retained record at result projection.  The checksum was
moved to record production with an exact canonical-byte implementation; a
second replay showed the remaining rollover/tombstone path.  After filtering
zero-quantity, zero-margin entries from sizing and margin projection, the
metrics and equity-curve artifact hashes remained identical.

| Window | Before fix (s) | After audit fix (s) | After tombstone fix (s) |
| ---: | ---: | ---: | ---: |
| 1 month | 110.5 | 73.408 | 73.405 |
| 3 months | 327.5 | 177.026 | 171.823 |
| 6 months | cancelled at 209.8 | 496.782* | 355.614 |
| 12 months | not completed | 855.606* | 669.296 |

`*` The 6- and 12-month audit-fix-only runs were submitted concurrently; the
single-worker tombstone-fix 6-month run is the comparable measurement.  The
12-month audit-fix-only run completed successfully; one later retry was
invalidated by a duplicate daemon restart, not by the backtest.

For the comparable post-fix windows, 1/3/6/12 months took
73.405/171.823/355.614/669.296 seconds.  The 3-to-6-month ratio is 2.07×,
and the 6-to-12-month ratio is 1.88×; both are close to the expected 2× for a
doubling of history.  The 3-, 6-, and 12-month before/after metrics were
identical.  Their equity-curve report hashes were respectively
`8e75c6c3b238a83a92768d722be35d24ca9549b6d48c83683750054629a0fc76`,
`d92634ae7067a414a517490f8b618d0e8c05ffac203e224af614cba57d4f4887`, and
`6bfe4417d4ae25687a86b82335491c9daa924d0ba870aad45ce8f679955ca3e3`.

The platform also exposed an operational guardrail: submitting through the
7998 manager while a manually launched daemon for the same deployment is
running can mark the old worker `scheduler_restarted`.  Such a Job is not a
performance observation and must be excluded from the table.

The audit then tested two further non-margin candidates against the same
frozen 10-group, three-month platform RunSpec.  The bar-proxy scheduler now
parses the immutable engine visibility policy once per strategy scheduling
batch; the focused helper benchmark reduced repeated MIN1 visibility-policy
resolution by about 20%, while the complete platform runs remained dominated
by normal market-data and worker variance.  Three post-change runs took
`110.420`, `105.274`, and `102.242` seconds, with identical metric and equity
artifact hashes (`26c0adee…`, `8e75c6c3…`, `d1a2d7d0…`).  The measured
`schedule_order_execution` totals were `7007`, `7081`, and `6525` ms, so this
is accepted as a local static-policy cleanup, not as a claimed whole-run
speedup.

A second candidate prebuilt one product's historical-field row for the two
cash-constraint simulations (reducing and increasing legs) in a SIGNAL/ORDER
batch.  Its focused tests passed and the complete native result remained
identical, but the platform replay took `133.993` seconds and the
`constrain_to_ledger_cash` total was `12388` ms, compared with the noisy
`10285`–`11380` ms baseline range.  The batch dictionary construction did not
produce a stable end-to-end gain, so that candidate was rejected and its
source changes were removed.  A direct scaling check over 1,000, 10,000,
100,000, and 300,000 order legs measured the batched path at 1.35×, 1.42×,
1.56×, and 1.63× the original lookup path, respectively.  Therefore a longer
backtest window would increase both costs approximately with the number of
legs; it would not create a crossover in which this rejected candidate becomes
faster.  The only way to make this optimization viable would be to eliminate
the per-batch dictionary construction or reuse a lifecycle-owned product-row
index whose identity and invalidation rules are already explicit.

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

Accept the measured optimizations in this audit: the two bounded caches, the
scalar DataMoney conversion path, the
eager streaming order-audit checksum, the compact lifecycle event axis, the
zero-position tombstone filters, the lazy partial-fill index, and the batched
lot cleanup. Each one removes a measured repeated lookup, serialization pass,
history-sized Python-object structure, or per-event scan while preserving the
field-default, routing, duplicate-detection, lifecycle, margin, and cost-basis
contracts. The tombstone filters retain any position with non-zero quantity or
reserved margin; they do not alter historical ledger inspection. Any further
optimization must first demonstrate a repeated lookup or a per-event cost
that increases with the number of prior bars, then compare exact equity,
position, target, and order-audit outputs before and after the change.

## Verification

- 131 focused native/server regression tests passed across the audit paths;
  the complete native suite passed with `841` tests and five expected flow
  contract warnings.
- The earlier registry/workspace boundary suite remains recorded above; its
  pandas 3.x timestamp-unit caveat is unrelated to this performance change.
- Server tests were not executable in the available conda runtime because it
  lacks Flask and `cli_anything`; changed server modules were compile-checked
  and their SQLite behavior was verified directly.
