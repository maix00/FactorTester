# ADR 121: Backtest result surfaces and lazy analysis

Status: Accepted

## Context

Backtest outputs used to map one generated artifact to one top-level tab.  That
made the tab row unstable, duplicated strategy-return views, and encouraged the
browser to fetch data unrelated to the question the user was asking.

The design is informed by established portfolio-analysis surfaces:

- QuantConnect groups result statistics, time-series charts and trades, lets
  users select visible charts, and links chart ranges.
- Pyfolio separates returns/risk tear sheets from transaction and round-trip
  analysis.
- FIX ExecutionReport models the order lifecycle as ordered state changes.
- GIPS requires fee basis, risk definitions, assumptions and simulated status
  to be visible rather than inferred from a chart.

## Decision

### Stable result surfaces

Backtest Jobs expose five stable surfaces:

1. **Overview** — runtime warnings, provenance and the bounded summary.
2. **Strategy statistics** — comparable strategy metrics; a strategy heading
   opens strategy-local analysis.
3. **Time-varying metrics** — equity/current drawdown, returns, rolling risk,
   cash, margin utilization, exposure and fill-based turnover. Strategy and
   curve selection live inside this surface.
4. **Execution and account** — an inner navigation for event flow, orders,
   fills/settlements, positions, cash, margin and fees.
5. **Return and risk analysis** — cost ratios, drawdown episodes and period
   returns.

Every top-level surface owns its strategy multi-selection state inside the
surface. Switching surfaces therefore restores that surface's previous
selection instead of applying an implicit global filter. Execution/account
inner pages additionally expose account, cash-pool and currency filters when
those identities are present in the authoritative artifact. They also show
the observed relationships from three independently pageable perspectives:
strategy, account, and cash pool. Account currency and cash-pool base currency
are separate dimensions: an account records the currency of its balance while
a pool's base currency is the common valuation unit. A missing identity or
currency remains explicitly unregistered and is never inferred from a strategy
label or from the other currency field.

The output registry declares `result_surface`, `result_view`,
`supplemental_bundle`, and semantic `result_order`. The UI consumes these
declarations and keeps a fallback projection only for old persisted Job
metadata. Artifact names remain storage identities, not navigation labels.

The strategy overlay keeps analyses that require one strategy identity or its
group membership: distribution, stability, capacity, tradability, calendar,
holding period, contribution, robustness and ranking. The duplicate strategy
return-series tab is removed because the external time-varying surface already
supports strategy filtering.

### Metrics and disclosure

The overview and strategy statistics should provide at least total and annual
return, volatility, Sharpe, Calmar, current and historical maximum drawdown,
win rate, turnover and material runtime warnings. Charts and tables retain the
strategy identity, timestamp/timezone, currency, fee basis, data-source and
fallback warnings needed to interpret those values. A missing value stays
missing; it is not converted to zero.

### Lazy loading

- Render the result shell, tabs and controls immediately.
- Fetch only the active inner page or selected curves.
- Fetch several newly selected curves concurrently and cache their immutable
  canonical payloads for the life of the mounted Job tab.
- Build DOM nodes only for the visible table page.
- Entering Execution and account initially loads one table. Event flow loads
  only orders and fills; account projections load when their inner page or
  chart is selected.
- Dimension choices are derived from the already loaded active artifact. The
  browser does not start a cross-server catalogue scan merely to populate an
  account or cash-pool filter.
- Ignore a completed fetch as navigation state. It may populate the immutable
  payload cache, but it must not switch a tab or reopen a closed control.

For artifacts that outgrow bounded canonical JSON, the next artifact schema
must add an indexed, immutable row/time partition and a capability-bound
`start/end/count` read. The browser must not emulate range queries by polling
business ports. Artifact bytes remain owned by the Job's storage server.

### Lazy computation and supplemental Jobs

- The primary run computes requested outputs in `post_replay` using one
  `ReportDataset`; cached projections prevent repeated scans.
- Optional post-run outputs are one supplemental Job request containing all
  selected outputs. Registry bundles identify shared work:
  `time_series`, `execution_account`, and `return_risk`.
- The supplemental identity is based on parent Job, source hashes, normalized
  request semantics and current output state. Concurrent equal requests reuse
  one queued/running Job; completed artifacts are stored on the parent while
  the child remains in supplemental history.
- Strategy-local tabs share one strategy-analysis bundle. Ranking remains a
  separate configuration/product-scope calculation.
- Deleting a generated artifact is an explicit user decision. Merely opening a
  result surface must not silently regenerate it; regeneration is an explicit
  supplemental action.

## Consequences

The navigation remains small even as outputs grow, cross-server reads occur
only for visible data, and supplemental work is auditable and deduplicated.
The immutable JSON format still has a whole-file transfer cost; very large
outputs require the indexed artifact schema described above rather than more
client-side pagination.

## References

- https://www.quantconnect.com/docs/v2/cloud-platform/backtesting/results
- https://www.quantconnect.com/docs/v2/cloud-platform/api-reference/backtest-management/read-backtest/charts
- https://quantopian.github.io/pyfolio/notebooks/round_trip_tear_sheet_example/
- https://www.fixtrading.org/online-specification/order-state-changes/
- https://www.fixtrading.org/online-specification/trade-appendix/
- https://interactivebrokers.github.io/tws-api/account_summary.html
- https://www.gipsstandards.org/standards/gips-standards-for-firms/gips-standards-handbook-for-firms/
