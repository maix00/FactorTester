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

### Workflow and governance industry sources

- **I-LANGGRAPH** — LangGraph persistence separates thread-scoped checkpoints
  from cross-thread stores and uses durable interrupts for human review:
  [persistence](https://docs.langchain.com/oss/python/langgraph/persistence),
  [interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts).
- **I-OPENAI-HITL** — OpenAI Agents SDK scopes approval to interrupted tool
  calls and serializes RunState for durable resume:
  [human in the loop](https://openai.github.io/openai-agents-python/human_in_the_loop/).
- **I-TEMPORAL** — Temporal reconstructs workflow state from server-generated
  execution history rather than parallel per-evidence histories:
  [history service](https://github.com/temporalio/temporal/blob/main/docs/architecture/history-service.md).
- **I-INTOTO** — in-toto signatures and attestations address software supply
  chain actor/artifact integrity across trust boundaries:
  [specification](https://github.com/in-toto/specification/blob/master/in-toto-spec.md).
- **I-NIST-RMF** — NIST AI RMF GOVERN 1.3–1.4 requires risk-management activity
  and controls to match organizational risk tolerance and priorities:
  [AI RMF 1.0](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf).

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
| 48 | D-MAP, D-PLAN, C-GRAPH | One branch lacks `tanh`; another independent IC job finishes. Only the first pauses and resumes from a changed capability/Maintenance disposition. |
| 49–51 | S-MHT, S-ML, D-PLAN | An IC sign-change-inspired gate becomes a new trial; an exposed holdout cannot confirm the edited hypothesis; a five-way sweep is ledgered and budgeted. |
| 52–53 | S-VARY, S-ML, D-FE | A volatility state has no standalone alpha but improves a preregistered interaction; a separately predictive auxiliary routes to multi-factor. |
| 54–58 | D-EXPR, C-ALIGN, D-PLAN | `$Rev` negates direction but never marks validity; same name/different hash cannot reuse evidence; same complete identity and terminal-assurance scope can. |
| 59–60 | D-MAP, C-GRAPH | Routine run completion writes canonical Job/trace evidence without waking a reviewer; graph activation cannot mutate a branch mid-job. |
| 61–62 | D-FE, D-EXPR, C-FP | Exact canonical composition passes all surfaces; a changed formula receives new identity instead of overwriting an old good result. |
| 63–66 | C-FP, C-ALIGN, D-EXPR | Raw child expression is aligned once by the parent; live/precomputed choice stays outside FactorExpr; strategy gating cannot relabel factor evidence. |
| 67–69 | C-WHERE, C-SDK, D-EXPR | `tanh` and public `where` need batch/incremental/hash/SDK tests; moving files alone must preserve imports, keys, NaNs, and representative factors. |
| 70–72 | D-MAP, C-WHERE, C-SDK | Research may add an auxiliary inside scope; the flat semantic Module layout removes duplicate WhereOp without creating a shallow directory. |
| 73–75 | D-MAP, D-IDENTITY | Two Agents produce sibling versions; identical structural hash reuses evidence; Planning, not Maintenance, asks the user what to research next. |
| 76–78 | D-PLAN, D-IDENTITY | Startup packet omits full catalogs; local checkpoint contains private detail; server resume packet verifies Git/factor/graph/RunSpec hashes and only bounded evidence refs. |
| 79–86 | D-MAP, C-GRAPH, D-PLAN | A waiting branch does not keep an LLM alive; capability disposition wakes it once; a Codex runtime may offer Goal, and unsupported Goal falls back without blocking work. |
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
| 118 | D-MAP, D-PLAN, C-GRAPH | One “Work Package budget” object cannot own user scope, statistical multiplicity, and runtime enforcement. Counterexamples: token exhaustion pauses Agent Flow without rejecting the hypothesis; statistical futility can end a branch while runtime budget remains. |
| 119 | D-MAP, D-PLAN, S-MHT, S-ML | Daily IC and intraday strategy studies can share graph topology while using different immutable TrialPlans. Post-outcome plan mutation must create a new version and trial effect. |
| 120 | D-MAP, D-PLAN, C-GRAPH, D-IDENTITY | Result with mismatched TrialPlan hash is retained as an attempt but rejected as evidence for the expected plan. Plan is written once; progress never rewrites it. |
| 121 | D-MAP, D-PLAN, S-MHT, C-GRAPH | Standard protocol fixture freezes with zero reviewer token; a custom adaptive stopping rule with unresolved dependence assumptions triggers one Statistical Reviewer. |
| 122 | D-PLAN, D-IDENTITY, C-GRAPH, S-MHT | A preregistered main/enriched pair shares one plan. An aux-only RunSpec created after outcomes requires a new plan/version and cannot be inserted into the exposed comparison family. |
| 123 | D-PLAN, D-IDENTITY, C-GRAPH | Revised by 124: a Job can execute successfully under the wrong TrialPlan hash, but the conflict is represented by projections of canonical Job/assurance facts and existing graph-trace evidence rather than new persisted entities. |
| 124 | D-PLAN, D-IDENTITY, C-GRAPH, ADR-037 | A completed Job already owns execution/artifact/assurance facts. One current-branch transition validates their hashes and appends the existing graph trace; no duplicate receipt/envelope table, parent-hash subsystem, unchanged-state write, or full-history context load is allowed. |
| 125 | D-PLAN, D-IDENTITY, C-GRAPH, ADR-037 | One TrialPlan coordinates multiple RunSpecs: its compact body is written once in validation-design trace evidence, the branch projects the current hash, ResearchRuns bind hash/role/comparison, and JobAttempts inherit. Physical persistence may be refactored when owner and query-path evidence proves lower I/O. |
| 126 | D-MAP, D-PLAN, C-GRAPH, ADR-037 | Token exhaustion pauses Agent Flow without changing hypothesis state or stopping an unaffected backend Job. Graph instance/branch are deepened into Work Package/Hypothesis Branch owners; resource accounting is removed rather than mirrored into parallel tables. |
| 127 | D-MAP, D-PLAN, C-GRAPH, ADR-037 | A Research Agent that exhausts most of its UI-configured total retains the same remaining balance after restart and Agent-ID reclaim. Only Agent Flow persists a compact budget row; graph/backtest paths do not write it. |
| 128 | D-MAP, D-PLAN, C-GRAPH, ADR-037 | A reviewer settles under budget period A while reset is pending; period B opens afterward. UI preserves task-attributed usage in A, shows remaining allowance in B, and no streamed-token or recurring-reset writes occur. |
| 129 | D-MAP, D-PLAN, C-GRAPH, ADR-037 | Token exhaustion while an IC Job runs preserves the current graph node and Agent checkpoint; the Job finishes. A later UI budget revision wakes the Agent once, with no polling or extra pause write. |
| 130 | D-MAP, D-PLAN, ADR-037 | With 100,000 historical invocation rows, settings reads only one profile and one current aggregate. History remains collapsed until an explicit bounded cursor page is requested; one revision refreshes one Agent. |
| 131 | D-MAP, D-PLAN, ADR-037 | A Research Agent changes runtime midway through a budget period. Its Agent ID and balance persist; absent actual usage settles from the reservation and is labeled fallback. Earlier actual rows and policy remain immutable. |
| 132 | D-MAP, D-PLAN, C-GRAPH, ADR-037 | A process crashes after reservation but before settlement. One reserved AgentInvocation owns provenance and recoverable reservation; no separate execution/reservation/provider-receipt join or dual-write path is required. |
| 133 | D-MAP, D-PLAN | Two 10,000-token calls have different causes: one repeats Skill documents and one carries long conversation. Fixed-category counts reveal the cause without saving either content or adding a settlement transaction. |
| 134 | D-MAP, D-PLAN | Clearing UI/browser state does not reset a local Research Agent's balance. The local manager store remains authoritative; UI reconstructs its view and no invocation is dual-written to server by default. |
| 135 | D-MAP, D-PLAN, C-GRAPH | One large Skill load creates a UI diagnostic and no wake; repeated identical avoidable loads create one deduplicated proposal. Semantic changes enter Maintenance and are judged on evidence quality as well as token/I/O. |
| 136 | D-MAP, D-PLAN, C-GRAPH, C-CLI | After one Job completes, Research resume returns one changed Job ref and current local branch/action. It loads no full factor inventory, graph, Skill catalog, history, or output and performs no write for unchanged revision. |
| 137 | D-MAP, D-PLAN, C-GRAPH, C-CLI | An unchanged approved local Skill is resolved through an opaque ref with zero rediscovery/reapproval. A changed content hash invalidates reuse and requires conversation approval; server never receives actual Skill identity. |
| 138 | D-MAP, D-PLAN, C-GRAPH, ADR-037 | A conforming Job stores assurance in its existing terminal transaction and Research consumes it from the changed Job packet. No separate receipt read/write or reviewer wake occurs; concrete anomaly alone opens Maintenance. |
| 139 | D-MAP, D-PLAN, C-GRAPH, ADR-037 | One IC Job has a manifest mismatch while independent diagnostics run. Only dependent evidence waits; deterministic review precedes one optional source-authorized reviewer, and a fix produces a new revision/attempt while all Jobs remain. |
| 140 | D-MAP, D-PLAN, C-GRAPH | A backend anomaly already has canonical Job, conversation, commit, and test refs. One compact case tracks dedup/claim/status; no copied bodies, per-kind queue, event table, unchanged-state write, or UI approval is required. |
| 141 | D-MAP, D-PLAN, C-GRAPH, I-LANGGRAPH, I-OPENAI-HITL, I-TEMPORAL, I-INTOTO, I-NIST-RMF | Owner-pinned transfer prevents double spending; plan-bearing trace retention prevents orphaned Run hashes. Runtime uses checkpoint/hash/AuthN-Z, high-risk effects use exact-hash single-use conversation approval, and signed attestation is reserved for real cross-boundary supply chains. |
| 142 | D-MAP, D-PLAN, C-GRAPH, D-IDENTITY, I-LANGGRAPH, I-OPENAI-HITL, I-TEMPORAL | Current activation spans six gate/version reads plus authorization consumption, active-copy insertion, and pointer update. Target activation reads one immutable version and one satisfied Maintenance Case then updates one pointer; final ownership is six Graph tables plus two Agent Flow tables. |

## Release-time evidence rule

The working records above explain semantics but are not release receipts.
Before activation, each implemented change must pin:

- original task ID plus the reviewed question/response turn references;
- repository commit and graph/catalog/product-profile hashes;
- exact test command and result artifact;
- applicable statistical evidence and threshold configuration;
- reviewer/audit decision hash;
- token, context-size, database, and latency measurements required by the
  acceptance matrix;
- rollback target.
