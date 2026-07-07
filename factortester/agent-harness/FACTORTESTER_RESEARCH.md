# FactorTester Research Harness

## Purpose

This CLI-Anything harness makes FactorTester agent-native for systematic factor
research. It does not reimplement FactorTester. The backend is the real
`factortester` CLI, which talks to a configured FactorTester HTTP server.

The harness adapts two research skill systems:

- `longbridge-quant`: factor definition, IC/IR, decile or group portfolios,
  factor decay, execution-cost awareness.
- `quantitative-research`: skeptical validation, train/test or walk-forward
  discipline, transaction costs, look-ahead checks, sample-size checks, regime
  awareness, and multiple-testing accounting.

## Research Loop

1. Define the factor family, factor alias or parameter grid, product groups,
   time range, and cost/capacity settings.
2. Run cheap diagnostics first: factor sequence sanity, IC/IR, IC decay, factor
   type analysis, product-group coverage, and transaction-cost feasibility.
3. Run group/backtest grids only after diagnostics pass.
4. Audit order flow, snapshots, ledger results, volume-capacity constraints,
   margin mode, fee mode, and runtime summaries.
5. If a CLI/backend feature is missing or results reveal a platform bug, stop
   research, record a gap, fix the codebase in the owning branch, validate, then
   resume the same session.

## Backend Contract

The harness calls `factortester` as an external command. Users of the installed
client do not need server source code on their machine. Commands should use
`--json` where available, and failures must be recorded rather than silently
ignored.

## Canonical Validation Checklist

- IC uses rank correlation by default and reports IC mean, IR, hit rate, t-stat,
  decay, and sample count.
- Backtests include fees, capacity, and explicit margin mode.
- Signal timestamps and execution timestamps obey no-look-ahead rules.
- Product groups are point-in-time enough for the requested research question.
- Parameter grids record how many hypotheses were tried.
- Final claims are out-of-sample or explicitly marked exploratory.
