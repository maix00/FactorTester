# ADR 108: Test workbench run observability

## Status

Accepted

## Context

The IC and backtest configuration pages share the same run-batch surface, but
its implementation was loaded only after a product group had been selected.
That made the RunSpec and run controls disappear on the initial configuration
page. The same global-IIFE boundary also allowed the batch and result modules
to call configuration or Job APIs without declaring their module dependencies.

## Decision

- Load the run-batch view for every test configuration page after the settings
  shell is ready. Keep the execution/action code deferred until the user
  previews or runs a group; disabled batch actions explain that a product group
  must be selected.
- Declare `workbench-ic-controls` for the batch and submission groups, and
  declare `jobs` for the inline result/progress group. These are runtime
  dependencies, not incidental globals.
- Reuse `FTJobProgress.progressView` and its SSE stream for the inline progress
  bar. On a terminal event, read the Job detail once more before rendering
  domain results.
- Reuse `FTICResults.section` and `FTBacktestResults.section`, so the
  configuration page uses the same Highcharts and table viewers as Job detail.
- Include the selected Manager `server_id` in a successful run submission
  response. Keep it on the RunSpec/Job links and detail requests so a remote
  execution node remains addressable; artifact reads continue to use the
  storage-server query and do not inherit the worker port.

## Consequences

The configuration page now exposes a stable RunSpec/run surface before any
catalog selection, and a submitted test can show progress, a Job link, and its
final charts/tables without navigating away. Only the lightweight view and
progress code are added to the page; compiler, source, and submission code
remain action-bound. A single visible batch panel owns the shared progress
stream, matching the existing Job detail stream semantics.
