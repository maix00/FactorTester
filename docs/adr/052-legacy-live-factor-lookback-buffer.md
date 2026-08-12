# ADR-052: Bounded history for legacy live-factor adapters

- **Status**: Proposed for issue #180
- **Date**: 2026-08-11

## Context

Opaque non-`FactorExpr` live factors receive a pandas price table on SIGNAL.
Appending one row with `pd.concat` copied the complete history on every signal,
so a one-bar-per-signal replay accumulated a superlinear cost.  The adapter
also cannot infer whether an opaque factor needs a finite trailing window or a
cumulative history without changing its economics.

## Decision

The adapter accepts an optional factor declaration:

```python
live_lookback_bars = 120
# or, when expressing the contract in time:
live_lookback_window = "2h"
```

The existing `required_lookback` declaration is accepted as a compatibility
alias for `live_lookback_window`.  A declaration may be a positive integer
(already expressed in bars) or a time duration.  A duration is parsed with the
same `DataFreq`/product-session rules as internal rolling operators: the source
frequency is resolved once, the duration is converted to an integer bar count,
and the live adapter never performs timestamp subtraction while appending.  A
callable declaration is evaluated once per live factor instance.  An absent
declaration means unbounded history, so legacy behavior is unchanged.

When a finite window is declared, the live table keeps exactly the last
resolved number of logical visible bars.  The visibility clock (`available_at`)
still controls which rows may enter the table; the retention declaration never
permits a future row.  A factor that needs cumulative state must omit the
declaration or maintain that state in `on_bar`.

For intraday durations spanning one or more days, product session metadata is
used when available, matching `_resolve_windows`.  If only opaque product
identifiers are available, the adapter uses a conservative elapsed-frequency
ceiling rather than silently retaining fewer bars than the declared duration.

The table store uses an append-only, chunk-growing numeric buffer and exposes a
pandas view of the populated rows.  Duplicate timestamps and timezone-aware
indexes retain the compatibility path with the previous pandas merge rules.

## Acceptance

- undeclared factors receive the same full-history rows and duplicate handling;
- explicit bar declarations keep exactly that many trailing logical bars;
- duration declarations resolve to the same bar count as internal rolling
  window resolution before the first append;
- hidden causal bars remain pending until `available_at`;
- snapshots held by a factor remain stable under later appends (pandas
  copy-on-write plus copy-on-grow storage);
- live and precomputed factor tests continue to pass;
- windowed legacy replay scales linearly in bar count and does not retain the
  complete history.
