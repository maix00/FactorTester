# Grill Evidence Registry

This registry prevents the detailed Grill records from duplicating the same
large code excerpts, papers, and acceptance scenarios. It is a documentation
index, not runtime Agent context. Exact line numbers are intentionally omitted
where the owning implementation is still changing; paths and semantic owners
are stable enough for review, while a release receipt pins the final commit.

## Evidence sources

### Domain and architecture documents

- **D-FE** — [`CONTEXT.md`](../../../CONTEXT.md), especially FactorFamily,
  FactorExpr, SignalAlign, execution backend, cache, parameter-space, and
  Research Workspace/Run/Job definitions.
- **D-MAP** — [`CONTEXT-MAP.md`](../../../CONTEXT-MAP.md) and
  [Research Decision Governance](../CONTEXT.md), defining the Agent Flow,
  Factor Research Graph, Maintenance Case, evidence, and audit boundaries.
- **D-PLAN** —
  [`research-decision-graph-plan.md`](../../research-decision-graph-plan.md),
  containing fixed governance, local context protocol, server ownership,
  delivery slices, and acceptance matrix.
- **D-EXPR** —
  [`ADR-001`](../../adr/001-expression-tree-factor-engine.md),
  [`ADR-005`](../../adr/005-intermediate-neg-and-storage.md),
  [`ADR-015`](../../adr/015-explicit-factor-author-sdk.md), and
  [`ADR-022`](../../adr/022-factor-execution-backends.md).
- **D-IDENTITY** —
  [`ADR-037`](../../adr/037-research-run-job-persistence-boundary.md),
  [`ADR-038`](../../adr/038-single-host-research-scheduler-and-data-affinity.md),
  and
  [`ADR-039`](../../adr/039-research-result-artifacts-and-user-quotas.md), as
  referenced by the root context.

### Current code facts

- **C-FP** — [`tools/factors/expr/leaf.py`](../../../tools/factors/expr/leaf.py)
  resolves a `FactorParam` from the referenced factor's `_func_expr`; the child
  does not carry an independent SignalAlign into the parent expression.
- **C-ALIGN** —
  [`tools/factors/FactorFamily.py`](../../../tools/factors/FactorFamily.py),
  [`tools/factors/Factors.py`](../../../tools/factors/Factors.py), and
  [`tools/factors/expr/signal_align.py`](../../../tools/factors/expr/signal_align.py)
  own final factor alignment and the raw/function/aligned expression boundary.
- **C-WHERE** —
  [`tools/factors/expr/conditional.py`](../../../tools/factors/expr/conditional.py)
  and
  [`tools/factors/expr/composite.py`](../../../tools/factors/expr/composite.py)
  currently contain duplicate `WhereOp` definitions, motivating the sole-owner
  migration gate.
- **C-SDK** —
  [`tools/data/factor_workspace/sdk.py`](../../../tools/data/factor_workspace/sdk.py)
  is the explicit Factor Author SDK surface described by ADR-015; generated
  client workspaces must validate against that surface with real Pyright.
- **C-GRAPH** —
  [`server/services/research_graphs.py`](../../../server/services/research_graphs.py)
  owns immutable graph storage, activation gates, proposal/review/audit
  records, compact context limits, token reservation/receipt accounting, and
  branch state.
- **C-CLI** —
  [`tools/cli/commands/research_graph.py`](../../../tools/cli/commands/research_graph.py)
  records audit evidence through CLI/API without directly editing a graph.
- **C-HARNESS** —
  [`tools/cli/agent-harness/cli_anything/factortester_research`](../../../tools/cli/agent-harness/cli_anything/factortester_research)
  contains the current Agent-facing graph/capability/session protocol and its
  unit/full/server tests.

### Statistical and quantitative-research sources

- **S-MHT** — Harvey, Liu, and Zhu, “... and the Cross-Section of Expected
  Returns,” *Review of Financial Studies*, on data mining and multiple testing:
  [journal page](https://academic.oup.com/rfs/article-abstract/29/1/5/1843824).
- **S-ML** — Gu, Kelly, and Xiu, “Empirical Asset Pricing via Machine
  Learning,” on disciplined model comparison and out-of-sample evaluation:
  [NBER working paper](https://www.nber.org/papers/w25398).
- **S-VARY** — Hastie and Tibshirani, “Varying-Coefficient Models,” supporting
  state-dependent/conditional relationships without implying that every state
  variable is standalone alpha:
  [journal page](https://rss.onlinelibrary.wiley.com/doi/10.1111/j.2517-6161.1993.tb01939.x).
- **S-NONLINEAR** — Freyberger, Neuhierl, and Weber, “Dissecting
  Characteristics Nonparametrically,” supporting nonlinear characteristic
  transformations while requiring disciplined validation:
  [paper](https://ewfs.org/wp-content/uploads/2018/02/Freyberer-Dissecting-Characteristics-Nonparametrically-137.pdf).

These papers support statistical principles, not exact FactorTester thresholds
or graph edges. Numeric gates require product-specific validation and may not
be inferred from a citation alone.

## Per-question evidence and acceptance scenarios

| Questions | Evidence | Concrete acceptance or counterexample |
|---|---|---|
| 48 | D-MAP, D-PLAN, C-GRAPH | One branch lacks `tanh`; another independent IC job finishes. Only the first pauses and resumes from a receipt. |
| 49–51 | S-MHT, S-ML, D-PLAN | An IC sign-change-inspired gate becomes a new trial; an exposed holdout cannot confirm the edited hypothesis; a five-way sweep is ledgered and budgeted. |
| 52–53 | S-VARY, S-ML, D-FE | A volatility state has no standalone alpha but improves a preregistered interaction; a separately predictive auxiliary routes to multi-factor. |
| 54–58 | D-EXPR, C-ALIGN, D-PLAN | `$Rev` negates direction but never marks validity; same name/different hash cannot reuse evidence; same complete identity can. |
| 59–60 | D-MAP, C-GRAPH | Routine run completion writes evidence without waking a reviewer; graph activation cannot mutate a branch mid-job. |
| 61–62 | D-FE, D-EXPR, C-FP | Exact canonical composition passes all surfaces; a changed formula receives new identity instead of overwriting an old good result. |
| 63–66 | C-FP, C-ALIGN, D-EXPR | Raw child expression is aligned once by the parent; live/precomputed choice stays outside FactorExpr; strategy gating cannot relabel factor evidence. |
| 67–69 | C-WHERE, C-SDK, D-EXPR | `tanh` and public `where` need batch/incremental/hash/SDK tests; moving files alone must preserve imports, keys, NaNs, and representative factors. |
| 70–72 | D-MAP, C-WHERE, C-SDK | Research may add an auxiliary inside scope; the flat semantic Module layout removes duplicate WhereOp without creating a shallow directory. |
| 73–75 | D-MAP, D-IDENTITY | Two Agents produce sibling versions; identical structural hash reuses evidence; Planning, not Maintenance, asks the user what to research next. |
| 76–78 | D-PLAN, D-IDENTITY | Startup packet omits full catalogs; local checkpoint contains private detail; server resume packet verifies Git/factor/graph/RunSpec hashes. |
| 79–86 | D-MAP, C-GRAPH, D-PLAN | A waiting branch does not keep an LLM alive; a Codex runtime may offer Goal, and unsupported Goal falls back without blocking work. |
| 87–90 | D-PLAN, C-GRAPH | Unchanged event/heartbeat produces zero wake and zero write; one changed event creates one compact, budget-reserved wake. |
| 91–93 | D-MAP, D-PLAN | Backend jobs parallelize without one LLM per branch; Planning and Maintenance remain lightweight workflows until stable graph semantics exist. |
| 94–98 | D-MAP, S-ML | User confirms an open discovery scope; each executable candidate enters the same validation graph; exact targeted research short-circuits discovery. |
| 99–100 | S-ML, D-PLAN | Historical candidate generation uses a cutoff-bound state snapshot, never a regime label computed with future data; external Skill search is last. |
| 101–104 | S-MHT, D-FE, D-EXPR | A factor may be supported in one scope and contradicted in another; old-version performance never transfers to a repaired formula without new evidence. |
| 105–108 | D-MAP, C-FP, C-GRAPH | Server can compare opaque hashes and implement a general operator from test vectors without storing the private factor DAG. |
| 109–111 | D-MAP, D-PLAN | User sees a compact Work Package choice; a backend change is approved in the Maintenance conversation, not Research or UI. |
| 112–113 | D-MAP, C-HARNESS, C-GRAPH | Research graph returns a current-node gap only; future-node Bootstrap/Skill gaps cannot block candidate discovery. |
| 114–115 | S-MHT, S-ML | Input missingness inspection is a diagnostic; viewing IC/PnL requires a formal trial; failed submissions remain in attempt count. |
| 116–117 | D-MAP, D-PLAN, C-CLI | Graph stores an audit need description, local ledger records the chosen Skill, and the compact index links to detailed evidence rather than entering runtime context. |

## Release-time evidence rule

The working records above explain semantics but are not release receipts.
Before activation, each implemented change must pin:

- repository commit and graph/catalog/product-profile hashes;
- exact test command and result artifact;
- applicable statistical evidence and threshold configuration;
- reviewer/audit decision hash;
- token, context-size, database, and latency measurements required by the
  acceptance matrix;
- rollback target.
