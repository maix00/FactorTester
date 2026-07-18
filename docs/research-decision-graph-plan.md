# Research Decision Graph Implementation Plan

## Status

Working plan, not an ADR. The branch is rooted at
`fix/issue-123-factortester-cli-http` commit
`9f4a0bd7fd9583c9cb6e89641fb0bfaca166f95e`.

This document remains editable while the observed workflow, statistical
semantics, and server control plane are being validated. An ADR is deferred
until the draft graph has passed replay and shadow validation.

The evolving one-question-at-a-time audit record is maintained separately in
[`research-decision-graph-grill-log.md`](research-decision-graph-grill-log.md);
its detailed records and canonical governance language live under
[`research-decision-graph/`](research-decision-graph/). Neither the full index
nor the detailed records are loaded into routine Agent context.

These records are a searchable reconstruction, not a substitute for the
primary conversation. Before implementing a Grill-derived decision, the
implementing Agent must reopen the original task, review the relevant question,
user response, and surrounding corrections, and attach those turn references
to implementation or release evidence. A discrepancy fails closed into a new
document-grounded audit question.

## Objective

Turn the existing FactorTester research harness into an evidence-driven,
versioned research decision graph without replacing the real FactorTester
workspace, RunSpec, job, or artifact lifecycle.

The graph expresses product-neutral research semantics. Product support is a
separate binding concern:

- a factor declares the product groups and data fields for which it has been
  implemented or validated;
- a capability implementation declares the product groups it currently
  supports;
- a product profile supplies market-specific data, timing, accounting, and
  risk invariants;
- FactorTester may add new product profiles without redesigning the research
  graph.

China futures is the first product profile being validated, not a permanent
boundary of FactorTester or of the research architecture.

The system must:

- derive the initial graph from existing research behavior rather than ask the
  human auditor to design a research workflow;
- reassess every node and edge against statistical rules, market semantics,
  data availability, and counterexamples;
- support multiple bounded hypothesis branches and a small number of
  independent review agents;
- keep unaffected research running when one branch encounters a capability or
  policy gap;
- let agents propose and implement graph, Skill, Harness, and code changes;
- reserve the only human user's role for server-side, document-grounded,
  one-question-at-a-time audit of high-risk changes;
- keep Draft Graph changes in replay/shadow mode until activation gates pass.

The primary operational acceptance metric is token efficiency. The graph must
reduce repeated interpretation rather than become another large prompt.

Token control is pre-execution, not merely telemetry:

```text
create budget scope
  -> reserve max input/output before Agent, reviewer, or Skill work
  -> grant or deny atomically
  -> launch only with reservation_id
  -> ingest trusted provider/gateway usage receipt
  -> commit actual usage and release unused reservation
```

Client-reported transition telemetry is diagnostic only. Authoritative budget
usage comes from provider receipts whose HMAC is verified by the configured
gateway adapter. If no trusted adapter is configured, commit fails closed.
Skill-document, artifact-summary, and cache-read tokens are input attribution
subsets; reviewer tokens are added to primary input/output to form team total.

## Fixed Governance Decisions

1. The human is an auditor, not a research-flow author.
2. Agents may build and iterate a Draft Graph autonomously.
3. The auditor may freeze, reject, quarantine, or roll back a change, but never
   edits graph records or source code directly.
4. An agent must turn an audit disposition into a new proposal and rerun the
   relevant review and validation gates.
5. Capability changes use two-stage control:
   - audit the capability intent, permissions, and scope;
   - let agents implement and independently validate it.
6. An implementation that stays inside the approved scope may activate
   automatically. Scope drift, high-risk semantic changes, or reviewer
   disagreement re-enters audit.
7. A graph edge declares a capability contract. A registry resolves a concrete,
   versioned Skill, CLI command, or server feature.
   Product applicability belongs to the factor, data contract, implementation,
   and product profile; it does not define the graph topology.
8. External Skills may be discovered and downloaded into quarantine, but may
   not execute before the applicable audit approval.
9. Existing jobs are durable. A policy or capability gap pauses only affected
   graph branches; unrelated jobs continue.
10. Full local process files remain local. A local agent may submit a bounded
    structured trace with state, decision, evidence references, summaries, and
    hashes.
11. Deterministic code owns topology, guard, capability-binding, job-state,
    hash, and evidence-field checks. LLM review is reserved for semantic
    ambiguity and material change.
12. Runtime agents receive a local context packet, never the full graph or full
    capability catalog by default.
13. Skill metadata uses progressive disclosure. Full `SKILL.md` content is
    loaded only after a trigger matches and any required execution approval is
    present.
14. Document-grounded grill audit applies to graph, statistical-policy,
    first-time Skill execution, and platform changes, not ordinary transitions
    on an already active edge. The graph declares the audit capability by
    description rather than naming a concrete Skill. The local Skill-usage
    ledger records the actual approved implementation.
15. The server persists capability/Skill need descriptions and descriptor
    hashes, never the selected Skill name, provider, path, body, or content
    fingerprint. The Agent chooses whether to reuse or load a matching Skill.
16. The local research session keeps a tamper-evident Skill-usage ledger with
    the actual Skill identity, version, content fingerprint, approval
    reference, description-match rationale, load/reuse mode, and token cost.
    This local audit ledger is not uploaded to the server.
17. Model identity is telemetry, not graph semantics. Codex, model, or Skill
    provider changes cannot alter graph hashes or guards. A changed external
    source invalidates the local resolution cache and fails closed until
    conformance review.
18. Capability resolution cache entries are explicitly process-local. They
    avoid duplicate deterministic work only inside one long-lived Agent
    process and are not counted as cross-process or token savings. Cross-command
    Skill reuse is decided from the local research session's hash-chained
    Skill-usage ledger; no server Skill registry or extra cache database is
    introduced.
19. The first Active Graph activates single-factor research, including
    auxiliary inputs used for factor construction or strategy conditioning.
    It does not infer statistical class from the number of output columns.
20. A construction that selects or weights independently predictive signals is
    a multi-factor construction even when it produces one `FactorExpr` column.
    Multi-factor estimation, selection, attribution, spanning, and portfolio
    combination remain an explicit deferred capability and may not be
    silently represented as validated single-factor research.
21. A missing general operator or reusable backend capability required by an
    admissible research hypothesis creates a mandatory platform-completion
    obligation. It is not a factor rejection and may not be closed as
    permanently unsupported merely because the current backend lacks it.
22. Mandatory completion does not bypass change control. The affected branch
    enters `capability_gap`, unrelated jobs continue, a server-maintenance
    Agent implements the bounded change, and the capability becomes available
    only after semantic, numerical, timing, SDK, execution, and release
    conformance evidence passes the existing audit path.
23. A Work Package is a user authorization boundary, not a statistical or
    runtime-budget owner. It records the research objective and mode,
    factor/product/data scope, permissions, exclusions, expected evidence, and
    optional references to separately owned graph and Agent Flow state.

## Work Package, Graph, and Agent Flow Ownership

```text
Work Package
  = what the Research Agent is authorized to study

Factor Research Graph
  = how statistical evidence permits the research branch to proceed

Agent Flow
  = what runtime resources remain and when the Agent waits or resumes
```

The Work Package may carry `budget_scope_ref`, `goal_ref`, and
`graph_entry_ref` identifiers for coordination, but it does not define or
evaluate their semantics. In particular:

- hypothesis/trial families, preregistered statistical stopping,
  outcome-examination accounting, multiplicity, and research-branch decisions
  belong to the Factor Research Graph;
- token, compute-time, concurrency, fee, reservation, exhaustion, waiting, and
  resume behavior belong to Agent Flow and its deterministic scheduler;
- a backend job enforces only its own assigned resource limit and never decides
  whether the research hypothesis is supported.

Changing the authorized research scope creates or revises a Work Package.
Changing statistical design creates a new hypothesis/version or graph-governed
research decision. Changing runtime resources updates the referenced Agent Flow
budget through the applicable Agent conversation. These changes may be
presented together to a user, but must not be persisted as one owner or
evaluated by one state machine.

## Existing Observed Workflow

The current Harness supplies the first observed workflow:

```text
inspect_factor_expr_dsl
  -> prepare_factor_workspace
  -> understand_factor_source
  -> build_validation_slices
  -> create_research_workspace
  -> freeze_configuration
  -> submit_run
  -> observe_jobs
  -> control_jobs
  -> audit_results
```

Existing runtime branches are coarser than the documented workflow:

```text
command failure classified as platform gap
  -> code_improvement_required
  -> resolve all open gaps
  -> research_ready

poor result decision
  -> factor_improvement_required
  -> manually edit factor workspace and rerun diagnostics
```

The sequential research phases are advisory today. The gap states are persisted
locally, but the Harness does not persist a current phase, enforce diagnostic
gates, attach validation slices to RunSpecs, or resume the exact affected
branch.

## Semantic Sources

Each normative node or edge must cite one or more of:

- an existing Harness trace or persisted FactorTester run/job/artifact;
- a FactorTester invariant or accepted ADR;
- a statistical validation rule with an attributable source;
- a market/data contract, including point-in-time availability;
- an independently reproduced empirical result;
- a correctness or safety defect that makes the existing transition invalid.

An agent opinion without evidence is not sufficient to activate an edge.

## Statistical Research Semantics

There is no single industry-standard factor-research state graph. The stable
constraints come from research protocols and statistical methods whose
preconditions differ:

- freeze the hypothesis, selection boundary, holdout role, rejection rule, and
  complete trial family before inspecting selection results;
- count every factor, transform, horizon, universe, slice, parameter, and
  adaptive revision in a trial ledger;
- use false-discovery control only when more than one trial participates in
  selection, never only on the surviving subset;
- create an authoritative, net-of-cost return stream before applying Sharpe
  uncertainty methods;
- use Deflated Sharpe only after selection among multiple recorded trials;
- use PBO/CSCV only when complete candidate return paths over common partitions
  have been retained; it does not replace a true holdout;
- reject a failed hypothesis without forcing mutation, and treat every revision
  as a new hypothesis version with a trial-ledger increment and explicit
  holdout status.

The Draft Graph therefore follows:

```text
hypothesis preregistration
  -> capability resolution
  -> point-in-time data contract
  -> hypothesis/code/timing semantics
  -> validation and trial-family design
  -> cheap in-sample diagnostics
       -> reject -> independent result audit
       -> revise -> new hypothesis preregistration
       -> authoritative backtest
            -> statistical robustness
                 -> reject -> independent result audit
                 -> revise -> new hypothesis preregistration
                 -> independent result audit
                      -> research decision
```

The audit node has no post-result loop back to statistical robustness. An
omitted or newly invented statistical method is a new research version, not a
license to tune the same holdout result.

Statistical Skills remain guidance or candidate implementations until their
exact method, inputs, outputs, version, and preconditions are approved. Runtime
Agents receive capability descriptions and triggered conditions, not a full
Skill document. The current implementation gaps for the trial ledger,
bootstrap Sharpe, FDR, Deflated Sharpe, and PBO are intentionally visible; the
graph must not silently substitute generic examples.

Factor semantics also require evidence linking the hypothesis hash to the
factor source or AST hash, financial rationale, numerical examples, and
semantic invariants. The terminal decision writes only a bounded reference to
provisional local memory containing the hypothesis, code, data, RunSpec, trial
ledger, result, failure cause, and decision. Full artifacts remain local and
behind hashes; one experiment never promotes itself into a graph edge.

## Single-Factor Enrichment and Deferred Multi-Factor Work

The first Active Graph includes a conditional enrichment path. "Single factor"
means one primary economic alpha hypothesis, not merely one output column. The
graph records three independent dimensions:

```text
economic_hypothesis_count
predictive_input_count
selection_degrees_of_freedom
```

It also records one of these integration classes:

```text
unary_transform
conditional_gate
interaction_composite
additive_composite
strategy_conditioning
neutralization
portfolio_combination
```

Examples:

- `tanh(main / scale)` is a bounded monotone unary transform. In the absence
  of changed ties or missingness it should not improve rank order by itself,
  although it may change magnitude-sensitive sizing, Pearson IC, tail
  exposure, turnover, and net returns.
- `main * tanh(aux / scale)` is a signed conditional interaction. It may be
  treated as conditional single-factor research only when `main` is the sole
  alpha hypothesis and `aux` is a predeclared state, confidence, or exposure
  variable without an independent alpha claim. Negative gate values reverse
  the main signal.
- `main * (1 + tanh(aux / scale)) / 2` is a nonnegative smooth gate. It
  attenuates or restores the main signal without reversing its direction.
- `main + weight * tanh(aux / scale)` is multi-factor construction when `aux`
  carries an independently testable return-prediction claim or when the
  transform, scale, direction, or weight is selected from results. Storing the
  expression as one output column does not change that classification.

Every enrichment attempt freezes the formula or AST hash, main and auxiliary
roles, normalization and fit window, lag and point-in-time availability,
missing/stale policy, sign-reversal permission, parameters, candidate family,
revision budget, and trial-ledger increment before selection results are read.
The validation design compares `main-only`, `aux-only`, and `enriched`
specifications where each comparison is semantically meaningful. It preserves
failed candidates and reports both raw and multiplicity-adjusted evidence.

The conditional local graph path is:

```text
candidate discovery
  -> enrichment hypothesis
  -> enrichment semantic classification
  -> operator capability resolution
  -> enriched factor construction
  -> operator backend conformance
  -> validation design
  -> main/aux/enriched ablation
  -> authoritative backtest
  -> statistical robustness and audit
```

Routine single-factor research that does not propose enrichment does not load
this subgraph or its capability descriptions.

### Deferred multi-factor capability

The following work is recorded as a non-blocking deferred capability, not as
an implemented FactorTester feature:

- jointly select or weight independently predictive factors;
- estimate and stabilize weights out of sample;
- test incremental contribution, spanning, redundancy, and ablation;
- attribute returns and risk to retained component signals;
- control the trial family across signal, transform, weight, horizon, universe,
  and model searches;
- combine the resulting signal with later auxiliary strategy conditioning;
- distinguish signal construction from portfolio combination and risk or
  execution overlays.

The current ability to store multiple factor-family references or run multiple
strategies does not satisfy this contract. Any capability binding that claims
full multi-factor support must be downgraded until real execution and
statistical-conformance tests pass.

### Operator capability backlog

Operator support is execution-surface specific. A capability receipt must
distinguish:

```text
native_batch
native_incremental
external_precomputed_bridge
external_incremental
author_sdk
```

The initial mandatory completion set is:

- `tanh`;
- a public and typed `where` API;
- explicit time-series or rolling standardization suitable for point-in-time
  gate scaling;
- first-class clipping with a declared boundary and missing-value contract;
- explicit finite-value and missing/stale handling.

The next reusable enrichment set includes sigmoid/logistic gates,
signed-log/signed-power transforms, rolling percentile or rank, winsorization,
median/MAD robust scaling, and volatility scaling. Residualization,
neutralization, splines, regime switching, and mixture-of-experts are separate
high-freedom capabilities rather than aliases for scalar operators.

The list is a capability backlog, not a fixed operator zoo. When an admissible
conditional single-factor hypothesis or another reusable research method needs
a missing general operator, the resolver must:

1. retain the hypothesis and classify the exact missing semantics;
2. pause only affected graph branches and create a mandatory backend-completion
   work item;
3. reject silent fallback to a merely similar operator;
4. route implementation to an authorized server-maintenance Agent;
5. publish the capability, Author SDK change, and receipts after conformance;
6. resume the original branch from its immutable checkpoint.

The obligation is unconditional with respect to current backend availability.
Execution remains conditional on the established audit, isolation, testing,
and release gates. Unsafe arbitrary code, a result-selected one-off operator,
or a request that contradicts point-in-time or market-accounting invariants is
not a general operator; it must be reclassified or rejected with evidence.

### Graph-driven operator discovery

The Active Graph must preserve research affordances rather than present a
closed operator checklist. At `enrichment_semantic_classification`, the Agent
describes the intended effect and constraints before choosing syntax:

```text
economic role: primary alpha | state | confidence | exposure | cost | risk
integration class: unary transform | conditional gate | interaction
                   | strategy conditioning | neutralization | combination
desired properties: bounded | monotone | signed | nonnegative | robust
                    | rank-preserving | smooth | sparse | reversible
scope: pointwise | cross-sectional | time-series | rolling | strategy state
timing: input availability, fit window, lag, warm-up, execution alignment
missingness: propagate | mask | explicit fallback | stale rejection
```

Deterministic capability resolution then returns a small set of matching
descriptors:

```text
research purpose and mathematical effect
declared semantic constraints
implementation support by execution surface
available | composable | partially exposed | missing
evidence and approval references
```

The full backend operator catalog is a derived audit and discovery view, not
the normative boundary of research. Routine Agent context contains only
descriptors matched to the current node. It does not contain the full catalog,
operator source, tests, or Skill documents.

If no existing descriptor satisfies the declared research effect, the Agent
does not conclude that the method is unavailable. It must:

1. search approved local descriptions and relevant industry or statistical
   semantics for a suitable method;
2. determine whether the requirement is a scalar expression, a reusable
   factor operator, strategy conditioning, risk/execution behavior, or a
   multi-factor method;
3. propose an exact capability contract and counterexamples;
4. route a reusable missing backend capability to mandatory completion;
5. add the accepted descriptor to the Draft Graph or capability registry so
   later Agents can discover it without repeating the semantic search.

This discovery step may consider, without being limited to, bounding and tail
control, normalization, ordering, missingness, conditional gating,
interactions, temporal transforms, cross-sectional relations, exposure
control, and strategy conditioning. These are prompts for semantic review, not
a finite list of permitted operators.

Known implementations and known gaps should still be queryable so an Agent
does not waste time rediscovering them. The query must include missing
capabilities as well as callable ones. Selecting a missing descriptor creates
the mandatory completion path; proposing a genuinely new descriptor creates a
Draft capability change and the same bounded implementation path. Neither path
may silently substitute a nearby operator or discard the research hypothesis.

### Factor-role discovery and conditional improvement

The local context for candidate discovery, factor diagnostics, and factor
improvement must explicitly tell the Agent that it may:

- search the authorized workspace for primary, auxiliary, reference, control,
  state, exposure, liquidity, cost, and risk factors;
- start from a proposed primary factor and seek auxiliary inputs, or start from
  a useful state or auxiliary factor and discover which primary hypothesis it
  can condition;
- write a new experimental factor in its own branch;
- combine one primary hypothesis with multiple bounded auxiliary inputs when
  the integration semantics and complexity budget permit it;
- condition factor construction or an applicable trading strategy;
- reclassify a proposed construction as multi-factor, strategy, risk, or
  execution work when the evidence no longer supports conditional
  single-factor semantics;
- request mandatory completion of a missing reusable operator or backend
  policy without treating the gap as a negative factor result.

These are research affordances, not automatic instructions to modify every
factor. The Agent must first identify a falsifiable mechanism and preserve the
main-only baseline. Multiple auxiliaries require a bounded candidate set,
complexity and revision budgets, an authoritative trial count, incremental
addition, leave-one-auxiliary-out ablation, and independent out-of-sample or
walk-forward evidence.

The graph separates observation from prescription:

```text
market state or backtest result pattern
  -> diagnose plausible failure mechanism
  -> retrieve candidate conditioning families
  -> propose a falsifiable conditional hypothesis
  -> freeze a new trial and holdout status
  -> construct and validate the enriched factor
  -> retain success, failure, and boundary evidence
```

Result patterns that may trigger diagnosis include, without implying a fixed
answer:

- alpha or IC sign changes across volatility, trend, liquidity, carry,
  inventory, seasonality, or other point-in-time market states;
- strong average IC with weak quantile monotonicity or unstable tail groups;
- performance concentrated in a small product, regime, or time slice;
- acceptable gross evidence erased by turnover, fees, spread, impact, margin,
  or capacity;
- unstable magnitude with mostly stable rank evidence;
- missingness, stale data, sparse coverage, asynchronous sessions, or changing
  universe composition;
- decay, horizon mismatch, lag sensitivity, or execution-alignment failure;
- high correlation or redundancy with an existing factor;
- excessive exposure to a known risk, sector, curve, beta, or liquidity
  dimension;
- a conditional strategy that improves execution outcomes while leaving the
  underlying factor values unchanged.

For each pattern the Agent may retrieve one or more candidate mechanisms, such
as scaling, bounding, robust tail treatment, state-dependent gating,
interaction, lag or horizon adjustment, exposure control, strategy
conditioning, or an explicit decision not to enrich. The graph stores why a
mechanism might apply, its counterexamples, and its required evidence. It does
not assert that a symptom proves the mechanism or that one operator is the
unique remedy.

Post-result adaptation always creates a new hypothesis version. A consumed
holdout cannot be reused as pristine evidence for the enriched factor.
Diagnostics may nominate a path, but may not tune an operator, auxiliary,
threshold, scale, weight, horizon, or product subset against the same holdout
and then report that result as confirmation.

### Evidence-driven graph evolution

The Active Graph learns from research through a controlled promotion pipeline:

```text
experiment evidence envelope
  -> provisional local decision memory
  -> retrieval by similar mechanism, market state, and result pattern
  -> repeated-use and counterexample review
  -> Draft edge or descriptor proposal
  -> statistical and market-semantic review
  -> replay and shadow comparison
  -> independent grill audit
  -> activate, revise, quarantine, or reject
```

A provisional record includes:

- hypothesis, factor roles, integration class, formula or AST hash, and
  capability receipts;
- point-in-time market-state definition and data-availability contract;
- frozen RunSpec, product profile, selection/holdout roles, and trial count;
- main-only, auxiliary-only where meaningful, enriched, and ablation result
  references;
- gross and net results, coverage, turnover, effective sample size, stability,
  uncertainty, and multiplicity treatment;
- observed applicability boundary, failure mechanism, counterexamples, and
  decision;
- exact Skill usage in the local audit ledger and only bounded evidence
  references in server records.

One successful experiment is not a graph edge. A proposal may be made earlier
when an attributable industry, statistical, market, or accounting rule already
supports the transition; otherwise it requires repeated independent use with
retained failures and counterexamples. Repetition count alone is not proof:
the Graph Curator must test whether apparently similar cases share the same
causal timing, product semantics, execution layer, and statistical design.

Promoted edges remain conditional and falsifiable. They describe:

```text
applicability predicates
candidate mechanism families
required evidence
known counterexamples
risk level
revision and trial-budget effects
backend capabilities
rollback target
```

They do not hard-code a profitable formula or expose user factor source.
Normal research follows an already approved edge deterministically. A new or
materially changed edge is reviewed as a diff; the Agent receives only the
local subgraph and bounded evidence summaries. Process mining, graph curation,
and audit presentation are output modes of the maintenance Agent by default,
not three continuously running LLM reviewers.

Graph evolution is evaluated against both research value and operational cost:

- whether the edge improves out-of-sample decision quality, rejects weak ideas
  earlier, or prevents a known invalid analysis;
- whether it preserves failures, multiplicity, causal timing, market
  accounting, and scope distinctions;
- whether it reduces repeated semantic search without suppressing novel
  methods;
- whether context bytes, Agent/reviewer tokens, database statements, latency,
  and cache behavior remain inside their frozen budgets.

If an edge increases cost without producing useful evidence or creates
premature routing, it remains Draft, is revised, or is removed. Active Graph
evolution must make factor research more effective and more economical, not
merely make the graph larger.

### Enrichment acceptance gates

An enriched operator or integration path is only available after all applicable
gates pass:

- contract: stable operator key, arity, parameter domain, shape, structural
  hash, serialization, LaTeX or display metadata, and explicit support matrix;
- mathematics: hand-computed oracles plus boundedness, monotonicity, symmetry,
  saturation, broadcasting, ties, constants, `NaN`, infinity, and invalid
  domain tests as applicable;
- timing: prefix invariance, future-shock invariance, publication/effective
  timestamps, warm-up, session boundaries, and next-tradable-position rules;
- execution: batch versus incremental parity, native precomputed versus live
  path parity, bridge-payload correctness, and explicit rejection of execution
  surfaces that are not supported;
- authoring: generated `.pyi` and package exports followed by real Pyright in a
  clean generated factor workspace, including positive and negative consumer
  examples;
- research governance: authoritative append-only trial count, holdout seal,
  preregistered main/aux/enriched comparisons, out-of-sample or walk-forward
  evidence, costs, coverage, effective sample size, turnover, and stability;
- graph and assurance: a missing surface becomes a scoped capability gap,
  normal receipts use zero reviewers, an actual mismatch starts at most one
  independent verifier, and sibling jobs continue;
- cost: factor evaluation performs no per-observation database writes and no
  LLM work; routine context remains current-node-only and within its frozen
  token and database-statement budgets.

Passing these gates proves conformance to the frozen research and execution
contract. It does not by itself prove economic validity, future alpha, or
profitability.

The graph also borrows cross-domain research controls without copying
domain-specific publication workflows:

- [OSF Preregistration](https://www.cos.io/initiatives/prereg) supplies the
  planned-versus-unplanned distinction and permits predeclared conditional
  analyses. A branch may adapt, but the condition and alternate path must be
  frozen before the selection result is observed.
- [Registered Reports](https://www.cos.io/initiatives/registered-reports)
  supply the separation between method review and outcome review. This maps to
  proposal/reviewer/grill approval before evidence-generating execution, not to
  publication machinery.
- The
  [ASA Statement on P-Values](https://www.amstat.org/asa/files/pdfs/p-valuestatement.pdf)
  prevents a single threshold from becoming a research conclusion. Decisions
  retain effect magnitude, uncertainty, assumptions, multiplicity, economic
  meaning, and implementation evidence.
- W3C provenance standards supply execution lineage as described below.

These are complementary controls, not one universal standard. Clinical
reporting checklists and journal-specific rules are not imported as factor
research requirements.

Primary semantic sources:

- Arnott, Harvey, and Markowitz,
  [A Backtesting Protocol in the Era of Machine Learning](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3275654);
- Harvey, Liu, and Zhu,
  [The Cross-Section of Expected Returns](https://academic.oup.com/rfs/article-abstract/29/1/5/1843824);
- Bailey and López de Prado,
  [The Deflated Sharpe Ratio](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551);
- Bailey et al.,
  [The Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf);
- GIM,
  [XALPHA](https://arxiv.org/abs/2607.08332), used for the
  hypothesis-to-code and provisional-experiment-memory loop rather than as a
  statistical standard.

## Decision Graph versus Knowledge Graph

The Active Graph is not a general knowledge graph. Its normative core is a
versioned executable state graph: nodes are research states, while edges carry
deterministic guards, evidence requirements, risk, authorization, and bounded
side-effect rules. A knowledge graph answers semantic relationship and
provenance queries; it does not replace transition authorization.

Knowledge-graph standards are useful only as a compact metadata vocabulary:

- map immutable artifacts and graph versions to `Entity`, research execution
  to `Activity`, and human or software reviewers to `Agent`, following
  [W3C PROV-O](https://www.w3.org/TR/prov-o/);
- retain equivalents of `used`, `wasGeneratedBy`, `wasDerivedFrom`,
  `wasAssociatedWith`, and `wasRevisionOf` in evidence envelopes;
- use the constraint-oriented idea from
  [W3C SHACL](https://www.w3.org/TR/shacl/) when validating bounded evidence
  shapes, without introducing RDF or SPARQL into the runtime hot path.

The server continues to store normalized JSON, hashes, receipts, and bounded
references. It does not serialize the whole research history as RDF, load an
ontology into every Agent context, or ask an LLM to infer routine transitions.
If cross-project semantic discovery later becomes necessary, a read-only
knowledge projection can be derived from the authoritative state/evidence
records. It must not become a second source of transition truth.

## Graph Protocol

The first protocol version uses plain JSON and pure Python validation. It does
not require an agent framework.

### Graph

```yaml
schema_version: 1
graph_id: factor-research
version: 1
lifecycle: observed | draft | active | retired
parent_version: 0
research_semantics: product_neutral
content_hash: sha256
nodes: []
edges: []
provenance: {}
```

### Node

```yaml
node_id: inspect_factor_expr_dsl
kind: research | validation | execution | audit | capability_gap
purpose: Confirm operator semantics and causal visibility.
enforcement: advisory | deterministic | audited
required_capabilities: []
entry_evidence: []
exit_evidence: []
```

### Edge

```yaml
edge_id: inspect_factor_expr_dsl__prepare_factor_workspace
from_node: inspect_factor_expr_dsl
to_node: prepare_factor_workspace
edge_type: recommended | conditional | failure | recovery
guard: {}
required_evidence: []
counterexamples: []
risk_level: L1 | L2 | L3 | L4
```

### Capability contract

```yaml
capability_id: statistical-validation.block-bootstrap
contract_version: 1
input_schema: {}
output_schema: {}
semantic_invariants: []
permissions: []
```

Concrete implementations belong to a separate registry and bind the contract
to an exact CLI version, server feature, or code revision. For Skills, the
registry supplies reviewed descriptions and local load-time conformance data;
the Agent selects the actual runtime Skill by description. The server receives
only the capability description and descriptor hash. Each implementation also
declares `product_scopes`; the resolver reports an explicit gap when no
approved implementation supports the selected product group.

`graph capabilities` returns only compact bindings and gaps by default.
`--include-contracts` is an explicit human-audit option. Conditional
capabilities remain separate from mandatory node requirements until their
predicate matches.

### Runtime context packet

The default Agent handoff is bounded to:

```json
{
  "graph": "factor-research@v3",
  "branch": {"status": "running", "product_group": "china_futures"},
  "node": {"node_id": "cheap_factor_diagnostics"},
  "available_edges": [],
  "required_capabilities": [],
  "conditional_capabilities": [],
  "evidence_refs": [],
  "open_gaps": [],
  "token_telemetry": {}
}
```

Full artifacts, graph history, source, traces, and capability contracts stay
behind references and explicit inspection commands.

The packet also carries the fixed compact policy
`reuse_matching_runtime_skill_else_load_after_trigger_and_approval`. It does
not carry a Skill name. Exact usage is appended only to the local
`skill-usage` audit chain.

## Server Ownership

The server will own:

- immutable observed, draft, active, and retired graph versions;
- one active-version pointer per graph;
- proposals, independent reviews, validation evidence, and audit dispositions;
- capability descriptions and approval receipts, never concrete Skill identity;
- shadow replay reports and activation decisions.

The existing `user -> ResearchWorkspace -> ResearchRun -> JobAttempt` ownership
remains unchanged. Graph state must reference these identities rather than
becoming another job owner.

## Agent Roles

Use roles only when their outputs are independently useful:

- **Process Miner**: converts existing traces into an Observed Graph.
- **Semantic Reviewer**: checks market and data meaning.
- **Statistical Reviewer**: checks causal alignment, selection, multiple
  testing, sample sufficiency, and robustness.
- **Counterexample Reviewer**: searches for invalid transitions and missing
  alternatives.
- **Graph Curator**: merges evidence into a versioned proposal.
- **Capability Agent**: investigates missing Skills, CLI surfaces, data, or
  code.
- **Implementation Agent**: changes the owning branch within approved scope.
- **Audit Presenter**: produces the bounded document-grounded audit diff and
  appends the accepted disposition to the Grill Decision Log.

Do not spawn every role for every edge. L1/L2 changes may use one proposer and
one independent reviewer only when deterministic checks are insufficient.
L1 ordinary transitions use no reviewer. L3/L4 semantic or capability changes
use the minimum relevant specialist reviewers and may enter human audit.

## Delivery Slices

### Slice 1: Observed graph protocol

- define graph, node, edge, evidence, and capability-contract validation;
- deterministically project the existing Harness plan and persisted gap states
  into an Observed Graph;
- expose human-readable and JSON CLI inspection;
- prove content hashes are stable and invalid references fail loudly.

### Slice 2: Server draft/active registry

- store immutable graph versions in the existing cache SQLite database;
- expose authenticated read APIs for observed/draft/active versions;
- expose proposal and validation APIs without adding a new login or port;
- add FactorTester CLI commands using the existing authenticated session.

### Slice 3: Evidence-conditioned transitions

- turn checklist rules into explicit guards and required evidence;
- separate diagnostic jobs from expensive backtest branches;
- bind slice plans and hypothesis counts to frozen RunSpecs;
- pause only branches whose guards or capabilities are unsatisfied.
- return only current-node state through `research-graph context`;
- make `research-graph next` a distinct deterministic readiness interface with
  candidate edges, missing guard/evidence fields, blockers, and explicit Agent
  judgment triggers;
- record per-transition input, output, cache-read, Skill-document, artifact
  summary, and reviewer token telemetry.

### Slice 4: Capability contracts

- register capability descriptions plus concrete CLI/server implementations;
- persist only capability descriptions on the server while keeping actual
  Skill usage in the local audit ledger;
- invalidate local binding caches when a provider source fingerprint changes;
- keep research semantics independent from factor and implementation product
  scopes;
- resolve the selected product profile without changing graph topology;
- create a CapabilityGap when no approved implementation satisfies a contract;
- preserve running unrelated branches;
- require audited permission before executing a newly acquired Skill.

### Slice 5: Proposal, review, and audit

- persist proposer and independent reviewer records;
- detect reviewer disagreement and scope drift;
- create document-grounded, one-question-at-a-time evidence diffs for the
  server auditor;
- persist accepted, rejected, revised, and superseded audit decisions in the
  working Grill Decision Log without making that log part of routine Agent
  context;
- support freeze, reject, quarantine, rollback, and re-proposal dispositions.

### Slice 6: Replay and shadow activation

- import structured historical research traces;
- replay observed and draft graphs without submitting duplicate live work;
- compare paths, blocked states, evidence coverage, cost, and outcomes;
- activate only when declared gates pass.

## Acceptance Matrix

| Requirement | Authoritative evidence |
|---|---|
| Branch derives from issue-123 | merge-base and parent commit output |
| Existing Harness behavior preserved | old Harness unit and subprocess tests |
| Default context is token-bounded | context schema excludes full graph, contracts, artifacts, and history |
| Routine packet size is bounded | `routine_context_bytes <= 6000` activation gate |
| Context and next have distinct leverage | context returns state; next deterministically returns readiness, blockers, and judgment triggers |
| Next packet is also bounded | server measures final serialized next packet and rejects anything above 6000 bytes |
| Runtime resolution is node-local | no untriggered conditionals or future-node gaps in context |
| Full contracts are opt-in | CLI subprocess test for `--include-contracts` |
| Reviewer use is risk-bounded | L1/L2 default zero; L3 one specialist; L4 proposer plus one reviewer, third only on disagreement |
| Token cost is attributable | per-node/role/Skill/artifact telemetry aggregation |
| Token regression blocks activation | graph shadow token total cannot exceed the recorded baseline |
| Shadow comparison is like-for-like | distinct owned graph/baseline run IDs must share one immutable RunSpec hash |
| Shadow totals are real and non-zero | server derives both totals from committed provider usage; `0/0` cannot activate |
| Token budget preserves work | over-budget context disables new reviewers and keeps backend jobs running |
| Work cannot start beyond budget | Agent execution requires a live pre-execution reservation |
| Usage cannot be self-reported as authoritative | commit requires a trusted provider/gateway receipt |
| Attribution does not double count | Skill/artifact/cache subsets cannot exceed input tokens |
| Context has a real response cap | server measures final serialized packet and rejects anything above 6000 bytes |
| Request hot paths are schema-free | startup migration runs once; traced graph requests execute 0 DDL and 0 `PRAGMA table_info` |
| Context database cost is history-independent | branch aggregates are updated atomically; routine context performs 0 trace-history scans |
| Context reads have a fixed upper bound | warm-cache context uses three SELECTs: owner/branch JOIN, current resolution, and token budget |
| Routine transition has bounded I/O | warm-cache zero-token transition uses two SELECTs, one branch UPDATE, and one trace INSERT |
| Immutable graph reads are cached safely | cache key includes database path, graph ID, version, and content hash; callers receive defensive copies |
| Unchanged resolution does not write | content-addressed UPSERT reports zero changed rows for identical semantics |
| Graph protocol deterministic | stable hash tests over canonical JSON |
| Invalid graphs rejected | public validator tests |
| CLI is agent-readable | installed-command JSON subprocess tests |
| Server graph is authenticated | Flask route tests with distinct users |
| Active graph immutable/versioned | SQLite service tests and API history |
| Unaffected jobs continue | integration test with two independent branches |
| Skill cannot execute unapproved | capability registry and execution-gate test |
| Server stores no Skill identity | SQLite persistence inspection and server input rejection tests |
| Local Skill usage is auditable | hash-chained session ledger records identity, approval, load/reuse, and tokens |
| Provider updates fail closed | source fingerprint mismatch invalidates cache and creates an explicit gap |
| Cache scope is truthful | capability output declares `cache.scope=process`; separate installed CLI calls do not claim a hit |
| Model replacement is semantics-neutral | model/Codex telemetry changes do not change semantic cache or graph hash |
| Provider roots are relocatable | environment-root conformance tests for Codex and external providers |
| Scope drift re-enters audit | proposal lifecycle integration test |
| Auditor cannot edit graph directly | API authorization/transition tests |
| Draft does not constrain live work | shadow-mode integration test |
| Active graph can roll back | activation-pointer and audit-trace test |
| Historical replay is non-mutating | run/job count and artifact integrity test |
| Real backend remains authoritative | end-to-end CLI against FactorTester API |

Activation validation must include:

```json
{
  "token_efficiency_passed": true,
  "token_measurement_refs": {
    "routine_instance_id": "shadow-instance-id",
    "routine_branch_id": "shadow-branch-id",
    "baseline_run_id": "baseline-research-run-id"
  }
}
```

The server requires distinct graph and baseline research runs with the same
RunSpec hash. It recomputes context bytes, conditional/gap leakage, Agent
execution count, and both non-zero token totals. Token totals come only from
committed provider usage receipts; client-submitted metric values are ignored.
Activation accepts only evidence marked `server_derived`.

## Deferred Decisions

These are empirical engineering questions for agents to resolve, not questions
for the auditor:

- whether orchestration eventually uses LangGraph, OpenAI Agents SDK, or a
  smaller internal runner;
- the exact statistical edge library shared across products and the
  product-profile overlays needed by China futures;
- activation thresholds for replay coverage and reviewer agreement;
- whether semantic retrieval needs FTS only or later benefits from embeddings;
- which capability gaps justify a Skill versus a FactorTester code change.
