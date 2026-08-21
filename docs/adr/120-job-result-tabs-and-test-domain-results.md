# ADR-120: Job Result Tabs and Test-Domain Results

## Status

Accepted.

## Context

Job detail, embedded workbench results, IC results, and backtest results all
need the same result-area navigation. Their domain filters are not the same:
strategy identity and grouped-strategy diagnostics currently belong only to
backtest. Keeping both concerns in `jobs/` makes generic Job lifecycle code
interpret test-domain semantics and encourages parallel tab implementations.

## Decision

`jobs/result-tabs.js` owns the reusable result-area tab Interface: tab labels,
active state, activation events, and a slot for caller-provided controls. It
does not know strategies, factors, portfolios, or any RunSpec field.

Each test Module owns its result model and result-specific controls under
`test-modules/<test>/results/`. Backtest therefore owns stable strategy
identity, the exclusive “全部策略” multi-select Adapter, strategy filtering,
strategy statistics, grouped detail, and ranking diagnostics. Job detail and
the test workbench mount the same exported result Interface without copying a
parser or result-state model.

Result selection, pagination, folding, and active tabs are presentation state.
They do not enter RunSpec.

## Consequences

- New test Modules reuse one result-tab shell without inheriting backtest
  terminology or behavior.
- Backtest charts and tables consume one strategy-selection Interface.
- Physical paths express ownership: generic lifecycle UI under `jobs/`, test
  semantics under `test-modules/`.
- Existing browser globals remain stable while files move, preserving current
  Job-detail and embedded-workbench integrations.
