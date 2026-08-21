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

A terminal parent Job may also own supplemental computations. They remain
ordinary `research_jobs` child rows with `job_role=supplemental`; the parent
keeps its terminal state and the ordinary Job list continues to project one
parent row. While any child is active, that row may display the aggregate
status “分析中”. The parent detail owns a lazy, searchable and paginated history
of its supplemental children.

Built-in supplemental analyses navigate back into the test Module that owns
their semantics. Backtest strategy-analysis history therefore resolves a
stable strategy identity and opens the existing strategy-analysis overlay at
the recorded analysis tab. Generic Job code does not interpret those tabs.

Custom supplemental analyses are persistent result-area Tabs owned by the
parent Job. A random stable `tab_id` identifies one draft, its current Python
submission snapshot, and its current structured result. Renaming does not
change that identity. Re-running overwrites the current snapshot and result,
but every supplemental child remains in history. Explicit Tab deletion removes
the draft and current files while preserving those history rows as
non-recoverable audit records.

The generic Jobs result shell appends these custom Tabs to backtest, IC,
factor-series, and non-domain result viewers. Test Modules keep ownership of
their built-in result tabs. Visitors may read retained custom results but never
receive source or mutation controls.

Custom Python receives only a bounded read-only virtual artifact API. Execution
requires an operating-system sandbox, has no unsafe fallback, and denies
network, environment, subprocess, and filesystem mutation. CPU, memory,
wall-time, file-descriptor, input-artifact, and structured-output bounds apply.
Only the trusted supplemental sink may replace the result artifact beneath
`<parent-job-id>/custom-analyses/<tab-id>/`.

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
- Supplemental computation is routed by the parent Job's storage server, not
  by a historical business port.
- Deleting a custom-analysis result artifact does not delete its Tab; deleting
  the Tab is the only operation that removes its current submission and result.
