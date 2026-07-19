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

1. Confirm the concrete product range and requested sources with the user.
   Run compact `products availability` inspection before sample design, then
   define factor family, factor alias or parameter grid, time range, and
   cost/capacity settings. Product groups/product paths define
   the cross-sectional ranking universe; product masks only filter the already
   computed membership or targets for trading/evaluation. Do not treat a masked
   broad-universe run as equivalent to reranking inside the masked subset.
2. Use obligation discovery to state the exact data coverage, field/frequency,
   visibility-time, latency, provenance, and permitted-use facts that the
   decision requires. Availability inspection collects facts; it does not
   discharge those obligations by itself.
3. Inspect backend FactorExpr operators. If the research idea needs operators
   that are not covered, record the missing operator semantics/signature/tests
   and fix the platform before testing the factor.
4. Prepare/sync the factor workspace and read the factor family source before
   testing it.
5. Synthesize a TrialPlan only for actionable obligations. Bind the Decision
   Contract, compact availability evidence, factor/data/timing semantics,
   product accounting, market-regime comparisons, trial ledger, costs,
   capacity, resource limits, sample roles, freeze proof, and graph branch.
6. Run cheap diagnostics first: factor sequence sanity, IC/IR, IC decay, factor
   type analysis, product-group coverage, and transaction-cost feasibility.
7. Query the factor research result store before repeating runs. Import existing
   report artifacts with `factor-library import-result` or write script results
   directly with `factor-library save-result`, use
   `factor-library metrics` for canonical metric names, and use
   `factor-library history` / `rank` / `stability` to find candidates that
   deserve revalidation.
   Prefer structured metadata on every saved run: `sample_role`,
   `regime_label`, `slice_name`, `test_count`, `grid_size`, `oos_pass`,
   `multi_product_group_pass`, and `costed_pass`.
8. Run group/backtest grids only after diagnostics pass.
9. Audit order flow, snapshots, ledger results, volume-capacity constraints,
   margin mode, fee mode, and runtime summaries.
10. If a CLI/backend feature is missing, a FactorExpr operator is missing, an
   operator semantic is wrong, or calculations are incorrect, stop research,
   record a gap, fix the codebase in the owning branch/worktree, validate
   thoroughly, merge only through the approved workflow, restart the service, and
   resume the same session.

## Backend Contract

The harness calls `factortester` as an external command. Users of the installed
client do not need server source code on their machine. Commands should use
`--json` where available, and failures must be recorded rather than silently
ignored.

## Canonical Validation Checklist

- IC uses rank correlation by default and reports IC mean, IR, hit rate, t-stat,
  decay, and sample count.
- Factor source changes are made only after checking the backend FactorExpr
  operator registry and inspecting the workspace source.
- Missing operators are not worked around in factor code; they are recorded with
  semantics, signature, and tests, then implemented in the owning platform branch.
- Backtests include fees, capacity, and explicit margin mode.
- Signal timestamps and execution timestamps obey no-look-ahead rules.
- Operator semantics and factor calculations are verified before being used as
  research evidence.
- Product groups are point-in-time enough for the requested research question.
- Product group/product path and product mask are recorded separately:
  product group/path determines factor ranking, group boundaries, IC universe,
  and type-analysis universe; product mask is applied after membership to decide
  which products are traded or evaluated. Reports must state whether a result
  comes from a newly constructed product group or from a broader group plus mask.
- Parameter grids record how many hypotheses were tried.
- Saved research runs carry sample/regime/slice labels and overfit-audit fields
  whenever those are known.
- New IC/type/backtest runs are queryable through `factor-library history` and
  old artifacts are backfilled through `factor-library import-result`.
- `factor-library rank` is a candidate-generation query only; it never replaces
  sliced validation, cost/capacity checks, or untouched/prospective review.
- Recency alone does not make a sample OOS. A recent interval or stream is
  untouched only when sealed after the factor, selection boundary, and
  TrialPlan freeze; otherwise report it as historical validation or exploratory
  evidence.
