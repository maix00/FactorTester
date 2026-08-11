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
live_lookback_window = "20d"
```

The existing `required_lookback` declaration is accepted as a compatibility
alias.  The value is a time duration, not a number of bars; it is resolved with
the same parser as `warmup_window`.  A callable declaration is evaluated once
per live factor instance.  An absent declaration means unbounded history, so
legacy behavior is unchanged.

When a finite window is declared, the live table includes rows whose
represented `bar_end` is within that duration of the newest visible bar.  The
visibility clock (`available_at`) still controls which rows may enter the
table; the retention declaration never permits a future row.  A factor that
needs cumulative state must omit the declaration or maintain that state in
`on_bar`.

The table store uses an append-only, chunk-growing numeric buffer and exposes a
pandas view of the populated rows.  Duplicate timestamps and timezone-aware
indexes retain the compatibility path with the previous pandas merge rules.

## Acceptance

- undeclared factors receive the same full-history rows and duplicate handling;
- finite declarations keep a bounded trailing time window;
- hidden causal bars remain pending until `available_at`;
- snapshots held by a factor remain stable under later appends (pandas
  copy-on-write plus copy-on-grow storage);
- live and precomputed factor tests continue to pass;
- windowed legacy replay scales linearly in bar count and does not retain the
  complete history.
