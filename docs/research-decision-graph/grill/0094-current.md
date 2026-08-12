# Grill Record: Questions 94 onward

Shared code, document, statistical sources, and per-question acceptance
scenarios are indexed in [the evidence registry](evidence-registry.md).

This reconstruction is not the primary transcript. Every implementation must
reopen the original Codex task and review the relevant question, user response,
and adjacent corrections before treating an entry as executable semantics.

## 94 — User authority over primary scope

**Question/proposal.** Planning recommends and the user confirms selection or
change of the primary factor/family scope. Research autonomously finds
auxiliaries, changes parameters, and constructs conditional variants inside
the package. If an auxiliary becomes a new primary alpha direction, return to
Planning/user.

**User response.** Accepted and requested an Agent flow that can create factors
from zero.

**Resolution.** Future Planning graphification cannot remove user authority
over Workspace Objective and primary scope. Question 95 adds open discovery.

## 95 — Targeted research and open discovery

**Question/proposal.** Add `targeted_research` for identified primary scope and
`open_discovery` for a user-confirmed market/data/theme/permission/exclusion
scope in which an Agent may create candidates without per-factor confirmation.

**User response.** Accepted and asked whether new factors then enter the
existing Active Graph for feasibility testing.

**Resolution.** Yes; discovery produces candidates, not a separate validation
system.

## 96 — Discovery candidate lifecycle

**Question/proposal.** Give each executable discovery candidate its own
hypothesis branch and trial. Permit early stop for absent mechanism, lookahead,
or unavailable data. A backend capability gap is not factor failure.

**User response.** Accepted and proposed reusing the same discovery flow to
find main/auxiliary factors for existing factors.

**Resolution.** Question 97 unifies discovery intents.

## 97 — Unified candidate-discovery intents

**Question/proposal.** Parameterize one `candidate_discovery` node for new
primary, auxiliary for existing factor, primary for an existing state factor,
repair/redefinition, and strategy-condition candidate.

**User response.** “好”.

**Resolution.** All intents share evidence, preregistration, and validation
semantics; role changes create later hypothesis versions. Question 118 later
separates statistical graph rules from Agent Flow resource budgets.

## 98 — Short-circuit discovery

**Question/proposal.** For targeted research with an exact existing factor and
no requested expansion, deterministically register candidate/lineage and enter
preregistration without an Agent search. Activate bounded discovery only for
the applicable intent. Reuse identical discovery input/evidence hashes.

**User response.** “好”.

**Resolution.** A unified graph entry does not imply uniform token cost.

## 99 — MarketStateSnapshot ownership

**Question/proposal.** Deterministic backend code produces a point-in-time
`MarketStateSnapshot` bound to cutoff, data version, product scope, and hash.
The Agent sees a compact summary/reference and may propose a new state as a new
research variable or capability.

**User response.** “接受”.

**Rejected case.** Full-sample ex-post regime labels cannot generate historical
signals or candidate claims.

## 100 — Progressive candidate search

**Question/proposal.** Search current package/state/similar memory first, then
local/other-Agent evidence, data/operators/gaps, installed Skill
name/description/receipt, and only then external literature or new Skills.
Stop when enough candidates exist, but record whether broader/new-factor search
was considered.

**User response.** “可以”.

**Resolution.** Skill bodies load only after a matching trigger and required
approval.

## 101 — Scope-bound factor evidence states

**Question/proposal.** Replace global `validated` with `untested`, `evaluated`,
`supported_in_scope`, `contradicted_in_scope`, `inconclusive`, and
`superseded`, each bound to factor hash, market, period, frequency, strategy,
cost, and evidence.

**User response.** “可以”.

**Resolution.** `$Rev` is separate. Positive and negative evidence coexist;
support raises ranking but never creates a whitelist or permanent-validity
claim.

## 102 — `supported_in_scope` evidence

**Question/proposal.** Require frozen factor/data/RunSpec/design, point-in-time
timing, trial/multiple-selection control, unpolluted OOS/walk-forward, applicable
cost/turnover/margin/accounting, effect size and uncertainty, stability,
coverage, counterexamples, backend receipt, and independent audit. Do not use
one universal IC/Sharpe/p-value threshold.

**User response.** “可以”.

**Resolution.** Numeric thresholds are configured by product and research
type, then validated rather than embedded in graph topology.

## 103 — Old results after semantic defects

**Initial question/proposal.** Suggested new factor/version/hash on repair and
classifying old evidence as invalidated or requiring replay without calling it
factor contradiction.

**User response.** Asked whether results must record family version and warned
that a historically problematic family might still have good results.

**Revised proposal.** Bind every result to family version plus configuration
hash; retain all old results and classify by whether the issue changes formula
attribution, numerical/causal validity, accounting/execution validity, or only
metadata.

**User response.** “接受”.

**Resolution.** A reproducible, causal old formula can remain evidence for that
actual old factor and inspire new work; lookahead/accounting/execution-invalid
results remain audit/inspiration only; evidence never transfers silently to a
new version.

## 104 — Family version versus config hash

**Question/proposal.** Increment semantic family version for formula, parameter
schema, FactorParam semantics, default direction, data fields, timing, or
alignment changes. Parameter values create config hashes; display-only changes
create metadata revisions. Human version is monotonic; AST/content hash is
authoritative.

**User response.** “接受”.

**Acceptance.** Tooling classifies the contract diff; an Agent cannot overwrite
or self-declare the identity class.

## 105 — Versioning without server formulas

**Question/proposal.** Keep source, AST, and formula in the local factor
workspace. Server stores opaque contract/AST hashes, family version, parameter
schema, FactorParam references, and evidence relationships. A temporary worker
may compute a hash/receipt and then delete source/AST.

**User response.** “好”.

**Resolution.** Server comparison and human-readable version allocation do not
require long-term reconstructable formulas.

## 106 — Source-free main/auxiliary relationships

**Question/proposal.** Server may store experiment, primary/auxiliary refs,
declared roles, anonymous integration class, contract hash, and evidence refs,
but not operation order, `tanh`/arithmetic DAG, weights, thresholds, or formula.

**User response.** “接受”.

**Resolution.** Server can learn research-role patterns without reconstructing
private factor source.

## 107 — Agent location and source permissions

**Question/proposal.** Planning and Research Agents run client-side and may see
authorized local factor source but not backend source. Server Maintenance may
see backend/graph source but not user factor source by default. Explicit source
retention permission is exceptional and cannot be a normal maintenance
dependency.

**User response.** “是”.

**Resolution.** Capability implementation must work from a source-free general
contract.

## 108 — Source-free capability-gap contract

**Question/proposal.** Send mathematical/strategy semantics, I/O type and
shape, parameter domain, NaN/Inf/missing/timing rules, batch/incremental
requirements, hand examples, test vectors, counterexamples, anonymous
integration class, and execution surface—never user formula, source, or local
path.

**User response.** “好”.

**Acceptance.** Server conformance tests the general implementation; the client
reruns the private factor and returns only a new semantic difference if needed.

## 109 — Compact Planning conversation

**Question/proposal.** Show one recommended Work Package and a few alternatives
with target, scope, rationale, expected cost, key gaps, and completion
condition. Expand factor/evidence/state references only on request. Hide graph
guards, hashes, receipts, and scheduling fields.

**User response.** “好”.

**Resolution.** The user modifies scope in natural language; Goal creation
follows confirmation.

## 110 — When Research interrupts the user

**Question/proposal.** Ask only for material primary scope change, new
data/cost/permission/source-sync, first execution or changed hash of a Skill,
new primary alpha direction, budget/stopping change, or an irreducible user
preference. Do not interrupt for auxiliary discovery, gap classification,
in-scope trials, job wait/resume, failures, or Provisional Memory.

**User response.** “好”.

**Clarification.** “Do not interrupt Research for backend completion” does not
remove server-side approval; question 111 routes it.

## 111 — Server-side approval routing

**Question/proposal.** Research emits a deterministic Maintenance Case and
checkpoints. Server Maintenance presents a compact diff/plan in its own Agent
conversation, obtains audit, implements, validates, releases, and sends a
capability receipt. Research sees only waiting/available state.

**User response.** “接受”.

**Resolution.** Research context never loads backend source, audit dialogue, or
implementation history.

## 112 — Final first-graph boundary

**Question/proposal.** The factor-research graph contains candidate discovery,
preregistration, node-local capability resolution, data contract, factor
semantics, optional enrichment/backend conformance, validation design, cheap
diagnostics, authoritative backtest, robustness, result audit, and research
decision. Research decision emits compact memory/event references.

**User response.** “接受”.

**Resolution.** Experience generalization, Draft proposal, grill audit, backend
implementation/release, Goal, and heartbeat remain outside the research graph
in Maintenance or Agent Flow.

## 113 — Node-local capability resolution

**Question/proposal.** Candidate discovery resolves only its current
data/factor/method/triggered-Skill needs. Later nodes resolve their capabilities
only when reached and triggered. One missing discovery method pauses only
dependent candidates.

**User response.** “接受”.

**Rejected case.** Startup may not scan the whole graph and report future
bootstrap, multi-test, Skill, or backend gaps as current blockers.

## 114 — Scratch candidate versus formal branch

**Question/proposal.** Keep ideas in local discovery scratch while screening
duplicate, data availability, causal timing, and basic mechanism. Before actual
computation, parameter comparison, or result viewing, preregister and create
the hypothesis branch/trial. Keep brief early-rejection reasons.

**User response.** “接受”.

**Resolution.** An already computed candidate cannot be renamed “draft” to
evade trial count.

## 115 — Attempt and outcome-examined counts

**Question/proposal.** Increment `attempt_count` after a frozen hypothesis
submits computation, including failed/cancelled/no-result work. Increment
`outcome_examined_count` when an Agent first sees IC, future returns, group
results, PnL, or another selection outcome. Log input-quality/computability
diagnostics but do not count them as outcome trials.

**User response.** “好” in the next turn, explicitly interpreted and confirmed
as acceptance before continuing.

**Resolution.** Syntax/backend failures remain immutable attempts but differ
from statistical outcome trials. Multiplicity uses the authoritative count
required by its method; failed records cannot be deleted.

## 116 — Skill-neutral document-grounded audit

**Question/proposal.** Do not hard-code `grill-me` or `grill-with-docs` into
graph semantics. Persist a description requiring domain-document/code/norm
grounding, one-question-at-a-time audit, and decision persistence. Resolve a
local approved Skill by description and record its actual identity in the
local Skill ledger. Audit only high-risk changes, not ordinary edges.

**User response.** “接受”.

**Resolution.** Create a working decision log, not an ADR; backfill recoverable
history; update after accepted questions; keep full audit history outside
routine Agent context.

## 117 — Correcting the first documentation pass

**Trigger.** The first log commit preserved a compact decision index but lost
question wording, user corrections, rejected alternatives, concrete evidence,
scenarios, affected boundaries, and acceptance detail. It also placed
governance terms in the root FactorTester domain context.

**Question/proposal.** Keep the compact table as an index; recover actual
question/response evidence from the local task record; add recommendation,
response, final meaning, rejected alternatives, evidence, scenarios, impact,
acceptance, and revision lineage; record the unnumbered phase honestly; move
governance language into its own context; use a corrective commit rather than
rewriting history.

**User response.** “接受”.

**Resolution.** This detailed record, the pre-numbering record, the Research
Decision Governance context, and the context map implement the correction.
The previous commit remains a traceable index-layer step rather than being
amended.

## 118 — Work Package versus graph and runtime budgets

**Original question/proposal.** The proposal asked how “Work Package
exploration budget and stopping conditions” should be defined, then placed
formal attempt/outcome counts, token, compute, time, concurrency, statistical
early stopping, multiplicity, running-job behavior, and user-approved budget
extension into one answer.

**User response.** “我觉得这些不是work package的语义？是否是active
graph的语义？我不是很明白，你是不是想的太多了”.

**Disposition.** Challenged and not accepted. The original proposal is
withdrawn because it conflated three owners:

- Work Package: user-authorized research scope;
- Factor Research Graph: statistical research and evidence-transition
  semantics;
- Agent Flow: operational resource enforcement and waiting/resume behavior.

**Additional user instruction.** Future records must follow
`grill-with-docs` completely. Existing reconstruction may still be incomplete;
real implementation must return to the original conversation record.

**Revised question/proposal.** The follow-up proposed:

- Work Package owns only user authorization: objective, targeted/open mode,
  factor/product/market/data scope, allowed and forbidden research behavior,
  and expected evidence;
- a Work Package may carry `budget_scope_ref`, but does not own budget values,
  stopping algorithms, or enforcement;
- Factor Research Graph owns trial family, preregistered statistical stopping,
  outcome inspection, multiplicity, and evidence-based branch continuation;
- Agent Flow owns token, compute time, concurrency, fee budget, exhaustion,
  waiting, resume, and routing a resource-change request to the appropriate
  Agent conversation;
- a backend scheduler enforces only the assigned job limit and never decides a
  research conclusion.

The shorthand presented to the user was:

```text
Work Package = 可以研究什么
Active Graph = 证据上应该怎么研究
Agent Flow = 当前还能运行多少以及何时恢复
```

**User response to the revised proposal.** “接受”.

**Final resolution.** The revised three-owner boundary is accepted. It
supersedes only the original combined-budget proposal, not earlier statistical
trial controls or Agent Flow token/database controls. An implementation may
join the three by opaque references for coordination, but may not persist or
evaluate them as one Work Package-owned state machine.

**Concrete counterexample.** If a branch exhausts token budget before an
outcome-aware statistical stopping rule fires, Agent Flow pauses execution; it
does not mark the hypothesis rejected. Conversely, a preregistered futility
rule may end the hypothesis while unused runtime budget remains.

**Acceptance evidence.**

- Work Package schema contains authorization fields and optional references,
  not trial counters or token-reservation logic.
- Graph state owns trial/outcome/multiplicity and research-decision evidence.
- Agent Flow tests resource exhaustion and resume without changing research
  disposition.
- Backend job resource failure is recorded as execution evidence, not factor
  contradiction.

## 119 — TrialPlan versus graph-edge thresholds

**Question/proposal.** Should Active Graph directly store concrete experimental
thresholds and stopping rules? The recommendation was no. Instead,
`validation_design` produces a versioned TrialPlan containing:

- hypothesis and trial family;
- primary and secondary outcomes;
- diagnostic and confirmation samples;
- holdout or walk-forward design;
- planned comparisons;
- outcome-aware stopping rules;
- multiplicity method;
- rejection and revision criteria.

The graph requires a valid `TrialPlanRef` and evaluates the evidence produced
under it. It does not hard-code one universal IC, Sharpe, sample-size, or
stopping threshold. Deterministic code validates fields, version, and hash;
Agent judgment addresses economic/statistical meaning. A plan changed after
outcome inspection becomes a new version with the applicable trial increment.

**User response.** “好”.

**Final resolution.** Accepted. TrialPlan is the branch-specific statistical
contract; Factor Research Graph remains the stable method/evidence topology.
Work Package and Agent Flow retain the separate ownership established by
question 118.

**Rejected alternative.** Putting concrete thresholds directly on graph edges
would make product/research-profile changes graph-version changes and tempt
later runs to mutate one global “correct” threshold.

**Concrete counterexample.** A daily China-futures IC study and an intraday
strategy-return study may share `validation_design → diagnostics` topology
while using different sample roles, outcome definitions, dependence
assumptions, and stopping thresholds. They use different TrialPlans, not
different research graphs solely for those values.

**Acceptance evidence.**

- graph node/edge schema carries `trial_plan_ref` and evidence requirements,
  not universal numeric research thresholds;
- TrialPlan identity and hash are frozen before selection-relevant outcomes;
- result evidence records the TrialPlan version used;
- post-outcome edits create a new immutable plan and auditable trial-ledger
  effect;
- protocol-specific threshold validation can change without altering graph
  topology.

## 120 — TrialPlan persistence owner

**Question/proposal.** Where should the immutable TrialPlan be stored? The
recommendation was:

- server stores the compact, immutable, audit-executable TrialPlan as the
  authoritative binding for Run and result evidence;
- local research stores full rationale, process explanation, and private
  references;
- server plan excludes factor source, formula, full Agent reasoning, and local
  private paths;
- each plan version is written once; runtime appends bounded attempt/result
  references rather than rewriting the plan;
- backend job submission binds the TrialPlan hash and returned result evidence
  must carry the same hash.

The counterargument to local-only storage was that the server could not
reliably reject an unregistered run or prove which statistical design governed
the observed result.

**User response.** “好”.

**Final resolution.** Accepted. Server owns the compact immutable execution and
audit contract; local research owns explanatory and private detail. The two are
linked by identity/hash rather than duplicated source.

**Rejected alternatives.**

- Local-only TrialPlan cannot provide server-side preregistration enforcement
  or authoritative Run/result binding.
- Persisting full local rationale/source on the server violates the established
  source and context boundary.
- Updating the plan for every progress event would turn statistical design into
  a database hot path and destroy immutability.

**Concrete counterexample.** A result arrives with the correct RunSpec but a
different TrialPlan hash. The server must retain the attempt for audit and
reject the result as evidence under the expected plan; it cannot infer the plan
from local notes after the outcome is known.

**Acceptance evidence.**

- TrialPlan record is immutable and source-free;
- Run submission requires a valid owned plan ID/hash;
- result ingestion verifies the same hash;
- plan creation is one low-frequency write per version;
- progress does not update TrialPlan rows;
- full rationale remains retrievable locally through authorized references.

## 121 — TrialPlan author and reviewer

**Question/proposal.** Who creates and reviews TrialPlan? The recommendation
was:

- Research Agent drafts it from the hypothesis, product profile, and applicable
  statistical protocol;
- deterministic code validates schema, hash, sample roles, required fields,
  and RunSpec consistency;
- a routine plan that exactly conforms to an approved protocol starts no
  reviewer;
- one Statistical Reviewer is invoked only for a non-standard method,
  ambiguous outcome/stopping/dependence semantics, protocol deviation, or a
  configured high-risk design;
- an unchanged input and review hash reuses the prior valid review;
- the user does not design statistics and is asked only when the plan changes
  authorized scope, fee, permission, or irreducible risk preference;
- result-related computation starts only after the plan freezes.

**User response.** “好”.

**Final resolution.** Accepted. TrialPlan authoring is Agent work,
protocol/schema conformance is deterministic work, and specialist LLM review is
exceptional rather than a mandatory node tax.

**Rejected alternatives.**

- Asking the human auditor to construct statistical plans contradicts the
  established auditor role.
- Starting a reviewer for every routine TrialPlan wastes token and repeats
  approved protocol checks.
- Letting Research self-approve a non-standard or ambiguous design removes
  independent evidence where it is materially useful.

**Concrete counterexample.** A standard cross-sectional IC plan exactly
matching an approved protocol passes deterministic predicates with zero
reviewer token. A custom adaptive stopping rule whose dependence assumptions
are not encoded triggers one Statistical Reviewer before freeze.

**Acceptance evidence.**

- routine protocol-conforming fixture freezes with zero reviewer invocation;
- each exceptional trigger starts at most one reviewer initially;
- unchanged review input reuses its receipt/hash;
- reviewer disagreement follows the existing high-risk escalation path;
- no result-related backend job can bind a draft or unvalidated plan.

## 122 — TrialPlan and RunSpec cardinality

**Question/proposal.** What relationship should TrialPlan and RunSpec have? The
recommendation was not one-to-one:

- RunSpec freezes one concrete calculation configuration: factor
  version/parameters, products, data, time window, strategy, and accounting;
- TrialPlan freezes statistical interpretation: sample roles, outcomes,
  comparisons, stopping, and multiplicity;
- one TrialPlan may coordinate multiple RunSpecs for main-only/aux-only/enriched
  comparisons, walk-forward windows, or
  diagnostic/selection/confirmation slices;
- each ResearchRun binds one TrialPlan version/hash, one RunSpec hash, its
  `trial_role`, and `comparison_id`;
- JobAttempt inherits the ResearchRun bindings and cannot modify them;
- TrialPlan references rather than duplicates full RunSpec execution state;
- an unplanned RunSpec cannot be attached after outcomes without a new plan
  version and trial effect.

**User response.** “好”.

**Final resolution.** Accepted. TrialPlan is an immutable statistical
coordination contract over one or more immutable execution specifications.
ResearchRun is the binding seam, and JobAttempt is only an execution attempt
under that seam.

**Rejected alternatives.**

- One TrialPlan per RunSpec cannot express preregistered comparisons or
  walk-forward families without losing their shared statistical identity.
- Copying complete RunSpec payloads into TrialPlan creates conflicting owners.
- Letting JobAttempt choose a different plan, role, or comparison makes failed
  and retried execution statistically ambiguous.

**Concrete counterexample.** A plan preregisters main-only and enriched
RunSpecs. After seeing the enriched result, an Agent creates an aux-only
RunSpec. That new run may inform a new plan/version, but cannot be inserted into
the already exposed comparison family.

**Acceptance evidence.**

- TrialPlan-to-RunSpec relationship supports one-to-many references;
- ResearchRun requires the four binding fields;
- retry/cancel/resume creates JobAttempts with identical inherited bindings;
- result ingestion rejects role/comparison/hash mismatch;
- post-outcome addition produces a new plan version and ledger event.

## 123 — Unified EvidenceEnvelope and Job receipts

**Question/proposal.** Should the externally requested unified
`EvidenceEnvelope` be identical to a Job result? The recommendation was no:

```text
JobEvidenceReceipt
  execution status / exit code
  stdout/stderr refs
  metrics/artifact refs
  RunSpec / TrialPlan / backend hashes

EvidenceEnvelope
  graph node and transition
  JobEvidenceReceipt refs
  factor/data/product identities
  attempt_count / outcome_examined_count
  stopping reason
  required evidence fields
  conflicts and gaps
  research disposition
  decision rationale refs
```

Each JobAttempt creates one immutable receipt. A node creates one immutable
Envelope when it is ready to transition or decide. Later evidence creates a
child Envelope linked by parent hash. Full stdout, curves, tables, and process
files remain behind references. Deterministic guards read bounded fields and
fail closed when exit code, plan hash, stopping reason, or required evidence is
missing.

**User response.** “好”.

**Final resolution.** Accepted initially, then revised by decision 124 after
the deletion test found duplicate persistence ownership.

**Rejected alternatives.**

- Treating a raw Job result as graph evidence omits trial counts, stopping,
  conflicts, gaps, and research rationale.
- One mutable Envelope updated throughout a run breaks replay and lets later
  outcomes rewrite prior evidence.
- Copying complete stdout/results into SQLite violates context and database hot
  path constraints.

**Concrete counterexample.** A Job exits successfully but returns evidence
under the wrong TrialPlan hash. Its receipt truthfully records successful
execution; the EvidenceEnvelope records the hash conflict and cannot satisfy
the transition guard.

**Acceptance evidence.**

- one receipt projection per JobAttempt and one validated evidence shape per
  existing graph trace;
- projection and trace-evidence schemas reject missing required identities;
- graph guards operate without fetching full artifacts;
- stdout/stderr/metric/artifact bodies are not stored in graph trace;
- replay reconstructs the same transition inputs from trace evidence and
  references.

## 124 — Complexity, token, and database-I/O audit

**Question/proposal.** The user asked to audit whether the accepted decisions
had introduced unnecessary complexity. Inspection of the canonical
`research_jobs`, `research_job_artifacts`,
`research_backend_assurance_receipts`, and `research_graph_trace` owners showed
that the persisted objects proposed by decision 123 duplicated existing facts
and event storage. The recommendation was:

- keep `JobEvidenceReceipt` only as a bounded read projection over the
  canonical JobAttempt, artifact metadata, and backend-assurance receipt;
- keep `EvidenceEnvelope` only as the validation schema of the existing
  append-only graph trace's `evidence_json`;
- do not add receipt/envelope tables, duplicate writes, or a parent-hash
  subsystem without a separate concrete tamper threat model;
- read only current-branch canonical rows, reuse facts already in the local
  decision packet, and perform no database write for unchanged state;
- retain TrialPlan as a distinct statistical schema, but do not create a
  separate service or routine reviewer Agent for it;
- treat specialist reviewer names as conditional modes unless they need
  independent identity and output.

**User response.** “好；注意要节省token并且最小化数据库读写”.

**Final resolution.** Accepted. Decision 123 is narrowed from two new
persistence objects to two interfaces over existing owners. Runtime
acceptance now includes token and database-I/O ceilings, not merely compact
JSON payloads.

**Rejected alternatives.**

- Persisting a second receipt per JobAttempt creates another truth owner and
  an avoidable terminal-job write.
- Persisting a second transition envelope duplicates graph trace and requires
  consistency reads or transactions between parallel event stores.
- Loading complete Job, artifact, assurance, or historical trace collections
  to build a routine decision packet saves no token merely because the final
  JSON is small.
- Assigning one persistent Agent per reviewer label repeats context and
  coordination cost.

**Concrete counterexample.** A completed Job already has a canonical
JobAttempt row, artifact hashes, and backend-assurance receipt. The current
branch transition can validate their IDs and hashes and store one bounded
`evidence_json` trace. A new receipt row plus a new Envelope row adds two
writes and later consistency reads without adding a research fact.

**Acceptance evidence.**

- schema migration creates no JobEvidenceReceipt or EvidenceEnvelope table;
- terminal Job completion performs no duplicate evidence-receipt write;
- one transition appends only the existing graph trace and updates its existing
  branch aggregate transaction;
- unchanged heartbeat, progress, or wait state causes zero graph database
  writes and zero Agent wake;
- routine context contains only current-node/current-branch evidence summaries
  and references;
- unchanged projection/trace inputs reuse their cached validation or review
  hash;
- database query-count and token telemetry tests fail when configured ceilings
  are exceeded.

## 125 — TrialPlan minimum persistence and schema freedom

**Question/proposal.** After decision 124 removed duplicate evidence
persistence, where can TrialPlan be frozen before Job submission without
creating another service or hot-path lookup? The proposed minimum shape was:

```text
validation_design graph trace
  compact immutable TrialPlan body + hash, written once
        |
hypothesis branch
  current_trial_plan_hash projection
        |
ResearchRun
  trial_plan_hash + trial_role + comparison_id
        |
JobAttempt
  inherits through ResearchRun
```

Routine submission reuses the already-loaded branch/run packet and does not
scan trace history. Audit/replay alone follows the reference to the compact
plan body. Statistical Reviewer remains a conditional mode.

**User response.** “可以，你要注意现有持久化对象语义不一定最优，你可以优化，
而不是只打补丁”.

**Final resolution.** Accepted with an implementation constraint. The diagram
defines minimum semantic ownership and bounded data flow, not a mandate to add
columns to the present tables. Before implementation, audit Workspace,
ResearchRun, JobAttempt, graph branch, and graph trace using deletion,
owner-locality, query-count, and write-count tests. Refactor or consolidate an
existing object when it yields a deeper owner and lower I/O while preserving
immutable bindings.

**Rejected alternatives.**

- A dedicated TrialPlan table/service adds an owner and lookup before evidence
  cardinality or query requirements justify it.
- Copying the TrialPlan body into every ResearchRun duplicates a one-to-many
  statistical contract.
- Looking up the latest plan by scanning historical traces on every submission
  saves schema work but increases routine reads and weakens explicit binding.
- Treating current tables as untouchable turns the architecture decision into
  incremental patching rather than ownership design.

**Concrete counterexample.** One frozen TrialPlan coordinates three RunSpecs.
Storing its body in three ResearchRun rows wastes space and invites divergence;
storing it once and binding three immutable hashes preserves the comparison.
If the existing branch/run split still requires duplicate owner/workspace
lookups, implementation may deepen or consolidate that split instead of
adding compensating indexes and joins.

**Acceptance evidence.**

- no dedicated TrialPlan table or service is created;
- compact plan body has one canonical write per version;
- a routine submission does not scan graph-trace history;
- JobAttempt does not duplicate the plan body or mutable statistical state;
- schema proposal includes before/after query and write counts for create,
  submit, terminal completion, resume, and replay;
- deletion/owner audit demonstrates that each canonical field has one owner;
- any refactor preserves existing lifecycle semantics or explicitly supersedes
  the affected ADR with migration and compatibility tests.

## 126 — Deepen graph persistence instead of adding parallel objects

**Question/proposal.** Existing graph persistence mixed research state with
Agent Flow resource state: graph instances directly owned token budget, while
graph branches updated multiple token/reviewer aggregate columns on every
transition. The proposed refactor was:

```text
graph instance = persisted Work Package projection
  authorization scope + workspace + pinned graph version
  opaque Agent Flow scope reference

graph branch = Hypothesis Branch
  research node + hypothesis/factor identity
  current TrialPlan hash + trial counters + evidence status

ResearchRun = immutable RunSpec binding for one branch
JobAttempt = one execution attempt
graph trace = one bounded research transition
Agent Flow = resource budget/usage + wait/resume
```

No parallel WorkPackage, Hypothesis, or CoordinationCheckpoint tables are
introduced. Token/compute/time/concurrency/fee budget and reviewer-usage
aggregation move out of graph persistence rather than being copied.

**User response.** “好”.

**Final resolution.** Accepted. Existing physical tables may be migrated or
consolidated to deepen these owners. Graph tables cannot enforce Agent Flow
budgets merely because earlier implementation placed those columns there.

**Rejected alternatives.**

- Adding separate WorkPackage and Hypothesis tables leaves graph
  instance/branch with overlapping identities and joins.
- Keeping token aggregates on graph branch makes every research transition a
  resource-accounting write and violates the accepted layer boundary.
- Mirroring Agent Flow budget state into graph tables creates two enforcement
  owners and reconciliation reads.
- Treating CoordinationCheckpoint as a stored entity duplicates the projection
  of branch, latest trace, active jobs, and Agent Flow state.

**Concrete counterexample.** A Research Agent exhausts its token budget while
a backend Job continues. Agent Flow must pause future Agent wakes without
changing the hypothesis node or statistical status. A token field owned by the
graph branch would incorrectly mix that operational pause with research
evidence.

**Acceptance evidence.**

- no parallel WorkPackage, Hypothesis, or CoordinationCheckpoint table exists;
- graph instance contains only authorization/research references plus an opaque
  Agent Flow scope reference;
- graph branch contains research/statistical state and no resource-budget
  enforcement fields;
- one resource-budget owner performs all reserve/settle/wait decisions;
- backend Job continues when only Agent Flow is token-paused;
- before/after transition write count shows removal of graph token-aggregate
  updates;
- migration/replay tests preserve graph, branch, run, job, and trace identity.

## 127 — Per-Agent UI limit and Agent Flow enforcement

**Question/proposal.** The initial proposal used multiple Agent execution,
reservation, provider-receipt, and budget objects. The user questioned why a
token budget needed database persistence and proposed that UI set a total
limit for each Research Agent. The revised proposal separated configuration,
enforcement, and research state:

```text
UI Agent Profile setting
  total token limit
        |
Agent Flow under claimed research_agent_id
  compact limit + used + temporary reservation + revision
        |
Factor Research Graph
  no token-budget field or enforcement
```

Persistence is required only to keep a hard total valid across process restart
or Agent-ID reclaim. Active counters may be cached. A real model call performs
at most one atomic reservation and one settlement; cache hits, unchanged
heartbeat, backend Job execution, and graph transition perform no budget
writes. Agent Flow accounting is isolated from the FactorTester result
database. Reviewer calls are charged to their sponsoring Research Agent unless
they use another explicitly budgeted profile.

**User response.** “接受；每个agent 调用的token数量记录在ui里边？用户可以看
到什么任务调用了多少token，还剩多少token限额，是否重置给它的限额？”

**Final resolution.** Accepted. UI is the configuration and observation
surface; Agent Flow is the durable accounting and enforcement owner. The
follow-up task-attribution, remaining-balance, and reset semantics are decided
in question 128.

**Rejected alternatives.**

- Memory-only accounting cannot enforce a total after restart or Agent-ID
  reclaim.
- Per-graph or per-branch budgets conflate research semantics with Agent
  orchestration.
- Writing streaming token updates or heartbeat counters creates unnecessary
  database traffic.
- Mirroring budget state into UI/browser storage, graph tables, and Agent Flow
  creates multiple truth owners.

**Concrete counterexample.** A Research Agent consumes most of its limit,
restarts, and reclaims the same Agent ID. Memory-only accounting incorrectly
restores the full allowance; one compact persisted Agent Flow row preserves
the remaining limit without touching graph or backtest storage.

**Acceptance evidence.**

- UI can set or disable a total limit for every managed Agent Profile;
- Agent Flow enforces the limit by claimed Agent ID;
- restart and Agent-ID reclaim preserve used and remaining amount;
- a model invocation performs at most two budget-state transactions;
- cache hit, heartbeat, graph transition, and backend Job produce zero budget
  writes;
- Research and FactorTester tables contain no token-budget owner fields;
- token-accounting latency and database contention are measured separately
  from the FactorTester result path.

## 128 — UI usage visibility and budget reset

**Question/proposal.** The user asked whether UI could show which task used how
many tokens, how much remained, and whether an Agent's allowance could be
reset. The proposal kept UI observational and Agent Flow authoritative:

- UI displays per-Agent limit, used, temporary reservation, remaining amount,
  current period, and pause state;
- usage is grouped by task and may show model/runtime, purpose, time, status,
  input/output/cache/charged counts, and actual-versus-estimated quality;
- reviewer calls appear as child usage under the sponsoring Research Agent;
- one compact usage item is appended in the existing settlement transaction;
- usage items contain references and counts, never prompt, complete context,
  factor source, or response body;
- changing a current limit preserves used amount;
- manual reset creates a new immutable budget period and preserves history;
- a reset requested during an active invocation takes effect after settlement;
- v1 has no automatic daily/weekly/monthly reset scheduler.

**User response.** “好”.

**Final resolution.** Accepted. UI is a task-attributed budget dashboard and
configuration surface, not an accounting store. Historical periods remain
auditable without creating another write transaction per invocation.

**Rejected alternatives.**

- Browser-local accounting is lost on refresh and cannot enforce a hard cap.
- Updating one UI/task row for streamed token increments creates a hot write
  path.
- Resetting `used=0` in place destroys historical auditability and can
  misattribute an invocation active across reset.
- Adding an automatic scheduler before recurring-reset demand exists increases
  operational and database complexity.

**Concrete counterexample.** A reviewer invocation starts under period A while
the user clicks reset. It settles into period A, then Agent Flow opens period B
with the configured allowance. UI retains the task and reviewer usage in A and
shows the full remaining amount in B without double charging.

**Acceptance evidence.**

- UI task totals equal the sum of compact settled usage items;
- remaining equals limit minus used minus active reservation;
- settlement writes budget state and usage item in one transaction;
- prompts, full context, source, and response bodies are absent;
- limit decrease below used pauses future calls without rewriting history;
- reset creates a new period and retains old task usage;
- active-invocation reset applies only after settlement;
- v1 creates no recurring-reset scheduler or periodic budget write.

## 129 — Budget exhaustion without research-state pollution

**Question/proposal.** The proposed exhaustion behavior was:

```text
remaining allowance cannot cover a safe invocation reservation
  -> Agent Flow refuses model execution
  -> local Research Agent checkpoint remains
  -> graph node and hypothesis status remain unchanged
  -> submitted backend Jobs continue
  -> UI changes limit or opens a new period
  -> one deduplicated budget-revision event wakes the Agent
```

`used + reserved >= limit` derives the pause and requires no extra pause row.
CLI/runtime receives provider-neutral `agent_budget_exhausted`. Unaffected
Agents, branches, and Jobs continue. Provider usage beyond reservation blocks
new calls and creates a metering anomaly without changing research evidence.

**User response.** “好”.

**Final resolution.** Accepted. Resource exhaustion remains entirely within
Agent Flow and does not become a Capability Gap, factor failure, graph edge, or
backend cancellation.

**Rejected alternatives.**

- Moving a branch to `capability_gap` on token exhaustion confuses resource
  availability with missing research capability.
- Cancelling an already-running Job wastes completed computation and changes
  research execution for an Agent-only constraint.
- Persisting a separate pause row duplicates a state derivable from the budget
  aggregate.
- Polling budget state or keeping an LLM heartbeat alive consumes the resource
  whose absence is being awaited.

**Concrete counterexample.** A Research Agent reaches its token limit while an
IC Job is running. The Job completes and its terminal facts remain available.
The branch stays at its current node. After UI opens a new budget period, one
revision event wakes the Agent to inspect the completed result.

**Acceptance evidence.**

- insufficient budget prevents model invocation before provider call;
- no graph transition, capability gap, factor-status change, or new pause row
  occurs;
- running backend Job reaches its normal terminal state;
- unchanged exhausted state causes zero polling, writes, and Agent wakes;
- one budget revision produces at most one matching Agent wake;
- restart preserves checkpoint and exhaustion state;
- over-reservation anomaly blocks later calls without rewriting research
  evidence.

## 130 — Lazy bounded UI usage reads

**Question/proposal.** To show complete token attribution without making the
settings page a database read hotspot:

```text
open settings
  -> read Agent Profile + current budget aggregate only

expand task usage
  -> fetch compact usage by agent + period + settled-time cursor
```

Invocation rows are grouped at read time. A budget revision event identifies
one Agent and refreshes only that aggregate. UI does not poll a full list or
scan invocation history. Version 1 adds no materialized daily/task summary,
scheduled compaction, automatic retention, or cleanup worker; those require a
measured threshold later.

**User response.** “好”.

**Final resolution.** Accepted. Complete task history remains inspectable, but
the routine settings path has constant-bounded reads independent of history
size.

**Rejected alternatives.**

- Loading all usage when settings opens makes ordinary configuration latency
  grow with audit history.
- Polling every Agent aggregate and task list repeats unchanged reads.
- Maintaining summary tables on every settlement duplicates aggregates before
  measured query pressure exists.
- Adding compaction/retention schedulers in v1 creates writes and lifecycle
  failure modes without current evidence.

**Concrete counterexample.** An Agent has 100,000 historical invocation rows.
Opening settings still reads one profile and one current aggregate. Only an
explicit task-history expansion reads the first bounded page; later pages use
the returned cursor.

**Acceptance evidence.**

- settings initial load performs constant-bounded queries independent of usage
  row count;
- collapsed task history returns no usage rows;
- expanded history is cursor-paginated with a configured page bound;
- one budget event refreshes only the referenced Agent aggregate;
- UI runs no full-history poll;
- v1 creates no usage-summary, compactor, retention, or cleanup scheduler;
- query-count and latency tests cover initial load, expansion, pagination, and
  settlement.

## 131 — Provider-neutral accounting across model/runtime changes

**Question/proposal.** Because provider usage and cache fields differ, a
budget cannot hard-code one model/runtime receipt. The proposed deterministic
adapter emits:

```text
input_tokens
output_tokens
cache_read_tokens
charged_tokens
measurement = actual | estimated | reserved_fallback
charging_policy_version
```

Agent ID remains the budget identity across model/runtime changes. Each budget
period pins one charging policy. Default charged amount uses normalized total
input plus output; cache-read is visible but not double charged when already a
subset of input. Deterministic preflight estimation plus maximum output creates
the reservation. If no reliable actual usage arrives, settlement charges that
reservation and labels the fallback. Historical usage is never recomputed
after adapter changes. The adapter is ordinary code, not an Agent or
context-loaded Skill.

**User response.** “好”.

**Final resolution.** Accepted. Codex and other current or future Agent
runtimes use the same accounting contract without becoming core semantic
dependencies or blocking work on an unfamiliar receipt shape.

**Rejected alternatives.**

- Binding budget identity to model/runtime resets or fragments one Agent's
  allowance after a provider change.
- Hard-coding one provider's cache fields can double charge or undercount.
- Recomputing history under a new adapter changes prior audit facts.
- Starting an Agent/Skill to interpret routine usage receipts wastes token and
  makes enforcement non-deterministic.
- Allowing unmetered execution when usage is absent violates the hard cap.

**Concrete counterexample.** A Research Agent changes runtime midway through
period A. The new runtime omits actual usage. Agent Flow safely reserves and
settles the fallback under the same Agent/period balance. UI shows the new
runtime and fallback quality while preserving earlier actual rows unchanged.

**Acceptance evidence.**

- model/runtime change retains Agent ID, period, used, and remaining amount;
- normalized cache fields cannot be double charged;
- charging policy is immutable within a period;
- adapter upgrade does not update historical usage rows;
- missing actual usage charges no more and no less than the accepted safe
  reservation fallback;
- unfamiliar runtime receipt does not prevent Agent startup;
- normalization invokes no LLM, sub-agent, or context-loaded Skill.

## 132 — Consolidate Agent execution and token persistence

**Question/proposal.** Existing persistence separated Agent execution, token
budget, reservation, and provider usage receipt into four tables even though
they describe two lifecycles. The proposed replacement was:

```text
AgentBudgetPeriod
  agent/period + limit/used/reserved + policy/revision + open/close

AgentInvocation
  task/purpose + runtime/model + principal/lineage/input hashes
  reservation + normalized usage + measurement quality
  provider request/attestation hash + status/timestamps
```

The pre-call transaction inserts a reserved invocation and updates its period.
Settlement updates the same invocation and period. An unfinished invocation is
the recoverable reservation. UI paginates settled invocation rows. The objects
belong to an independent Agent Flow Module/store rather than
`research_graphs.py`. Overlapping legacy tables are migrated and removed
without indefinite dual write.

**User response.** “好”.

**Final resolution.** Accepted. The deeper AgentInvocation retains security
principal, lineage, launcher/provider attestation, and usage auditability while
eliminating separate execution/reservation/receipt owners and joins.

**Rejected alternatives.**

- Four shallow tables require cross-table consistency checks for every call.
- Removing provenance merely to reduce table count breaks the trusted
  execution chain.
- Keeping old and new schemas in dual-write compatibility mode doubles writes
  and creates reconciliation failure.
- Leaving Agent accounting inside the Graph Module preserves the wrong
  ownership boundary.

**Concrete counterexample.** A process crashes after reservation but before
provider settlement. The single reserved AgentInvocation identifies exactly
what must be conservatively settled or released under policy. A separate
execution row, reservation row, and absent receipt add no recovery fact.

**Acceptance evidence.**

- Agent Flow schema has one period owner and one invocation owner;
- principal/lineage/input and provider attestation remain auditable;
- reserve and settle each use one transaction;
- crash recovery finds unfinished reservations from invocation status;
- UI task history requires no execution/reservation/receipt join;
- Graph Module has no Agent budget/execution tables after migration;
- migration tests preserve balances, provenance, completed usage, and pending
  recovery while eliminating dual writes.

## 133 — Bounded context-cost breakdown

**Question/proposal.** Total input/output usage cannot reveal avoidable context
cost. The deterministic context assembler can attach one bounded breakdown to
the existing AgentInvocation settlement:

```text
base instructions
conversation
local graph packet
evidence summaries
Skill documents
review material
output
```

Only fixed categories, counts, and measurement quality are stored. Prompt,
complete context, file names, artifact bodies, and per-Skill/evidence rows are
forbidden. UI shows totals by default and reads the breakdown only when one
invocation is expanded. Task aggregation happens at read time. No LLM
classifies usage, no graph field mirrors it, and no extra transaction is
created.

**User response.** “好的；这个是否要存在ui对应的客户端数据库里？”

**Final resolution.** Accepted. The placement question is separated into
decision 134: the breakdown belongs to the AgentInvocation owner, while UI
remains a read surface.

**Rejected alternatives.**

- Totals alone cannot distinguish repeated Skill loading from conversation or
  evidence-summary growth.
- Per-document usage rows increase write volume and risk leaking local names.
- Saving full context for later diagnosis violates source/privacy and storage
  constraints.
- Asking an LLM to classify its own context adds the cost being measured.

**Concrete counterexample.** Two calls each use 10,000 input tokens. One spends
8,000 on repeated Skill documents; the other spends 8,000 on a long
conversation. Fixed-category counts reveal different remediation without
storing either document or conversation.

**Acceptance evidence.**

- breakdown has a fixed schema and serialized size ceiling;
- no prompt, content, file name, artifact body, or per-document row is stored;
- context assembler produces counts without LLM execution;
- settlement transaction count is unchanged;
- collapsed UI does not read breakdown;
- task aggregation identifies dominant context category;
- graph persistence contains no copied token breakdown.

## 134 — Usage follows the Agent Flow owner

**Question/proposal.** The user asked whether token breakdown should live in a
UI client database. The proposed boundary was:

```text
local Research Agent
  -> local Agent Flow store -> local manager API -> UI

Server Agent
  -> server Agent Flow store -> server API -> UI
```

UI routes budget commands to the execution owner and merges read views. It has
no independent accounting database, browser-persisted usage, or enforcement
state. Version 1 keeps only an in-memory page cache and does not default-sync
local invocation history to the server. Cross-device summary synchronization
is deferred until explicitly required.

**User response.** “好”.

**Final resolution.** Accepted. Local usage is client-side persistence in the
sense that its Agent Flow owner is local, but it is not UI-owned data.

**Rejected alternatives.**

- A browser/UI database creates a third balance and usage owner.
- Copying every local invocation to the server adds network/database writes and
  contradicts local research-process ownership.
- Letting UI enforce a balance makes refresh, cache clear, or client upgrade a
  budget-safety event.
- Adding cross-device synchronization in v1 introduces conflict resolution
  before a concrete requirement exists.

**Concrete counterexample.** The browser cache is cleared while a local
Research Agent has used most of its allowance. The local Agent Flow store
retains the balance and invocation history; UI reconstructs its view without
granting new allowance or asking the server to replay local calls.

**Acceptance evidence.**

- clearing browser/UI state does not change Agent balance or history;
- local Agent usage is readable through the local manager API;
- Server Agent usage is readable through the server API;
- UI settings mutate only the selected Agent Flow owner;
- no usage row is written to both local and server stores by default;
- v1 has no cross-device sync/conflict machinery;
- UI page cache is disposable and never participates in enforcement.

## 135 — Optimize context without a standing optimizer Agent

**Question/proposal.** Context-cost breakdown should improve the system without
creating another recurring LLM consumer:

```text
AgentInvocation breakdown
  -> deterministic diagnostic
  -> single anomaly: UI mark only
  -> repeated/hard-threshold breach: one deduplicated proposal
  -> semantic-preserving cache/config action, or Maintenance Case
```

Token diagnostics remain in Agent Flow and never become factor-research edges.
No reviewer/optimizer Agent runs per invocation. Deterministic automation is
limited to semantics-preserving configuration/cache behavior. Context
assembler, Skill condition, reviewer policy, code, or Agent Flow semantic
changes enter Maintenance; high-risk changes use document-grounded grill.
Before/after evaluation includes task completion, effective evidence, token,
and database I/O.

**User response.** “好”.

**Final resolution.** Accepted. Telemetry can improve the framework, but the
optimization loop cannot cost more Agent work than the context waste it
addresses or sacrifice research evidence merely to lower token count.

**Rejected alternatives.**

- A standing Token Optimizer Agent consumes token on routine successful work.
- Turning token symptoms into research graph edges confuses orchestration with
  statistical semantics.
- Automatically changing Skill/reviewer conditions can silently alter research
  quality and authorization behavior.
- Optimizing only total token can remove evidence needed for valid decisions.

**Concrete counterexample.** One unusually large Skill document appears once;
UI marks it and no Agent wakes. The same unchanged document is unnecessarily
loaded across many equivalent calls; one deduplicated proposal recommends
cache/context reuse. A change to invocation conditions still enters
Maintenance rather than silently editing the research graph.

**Acceptance evidence.**

- routine invocation triggers zero optimizer/reviewer calls;
- identical diagnostics deduplicate to one open proposal;
- a one-off anomaly changes no runtime policy;
- automatic action demonstrably preserves semantics and authorization;
- code/Skill/reviewer/flow semantic changes route to Maintenance;
- evaluation compares completion, effective evidence, token, and database I/O;
- Factor Research Graph contains no token-cost transition.

## 136 — Role-specific small startup/resume packet

**Question/proposal.** To let an Agent start authorized work without first
understanding infrastructure, a deterministic provider-neutral resume contract
returns:

- Research: profile/budget summary, current Work Package scope, one current
  branch/node and candidate edges, TrialPlan ref, changed Job refs, node-local
  capability descriptions/reuse hints, and next action;
- Planning: pending scope decisions and bounded workspace-factor summary;
- Server Maintenance: unresolved Maintenance Cases and compact diffs.

It omits complete graph, factor/Skill catalogs, historical trace, usage
history, Job output, and future-node gaps. It uses no LLM. Repeating the same
checkpoint/revision returns identical content and writes nothing. Profiles are
unlimited until UI sets a cap. An exhausted profile can inspect deterministic
status/checkpoint but cannot start a model call. No Agent must open UI,
configure paths manually, or read architecture documents before beginning.

**User response.** “好”.

**Final resolution.** Accepted. Client/server command names may differ, but the
small-packet semantics and role boundaries are runtime-neutral.

**Rejected alternatives.**

- Returning the entire graph/catalog/history recreates the token problem the
  graph is meant to solve.
- Requiring budget setup before first work makes an optional user control a
  startup blocker.
- Asking an LLM to assemble its own resume context spends token before useful
  work and can omit deterministic state.
- Requiring UI/path/architecture setup from every Agent exposes infrastructure
  trivia and reduces portability.

**Concrete counterexample.** A Research Agent resumes after one backend Job
completed. It receives the unchanged current node plus that one changed Job
reference and the next guard/action. It does not reload the complete factor
workspace inventory, graph, Skill catalog, or previous Job outputs.

**Acceptance evidence.**

- startup packet has a configured serialized-size ceiling;
- role packets contain no other role's pending queues;
- future-node gaps and full catalogs/history/output are absent;
- assembler invokes no model;
- unchanged resume performs zero write and returns stable content/hash;
- unconfigured profile starts without budget friction;
- one changed Job produces one changed reference rather than full output;
- Agent can perform the first authorized action without UI/path/doc setup.

## 137 — Skill-neutral server packet and auditable local reuse

**Question/proposal.** Server startup packets retain only capability
description/hash. The local manager may add:

```text
opaque local Skill ref
content hash
approval scope/hash
runtime compatibility
context-cache availability
```

Matching description/content/approval/runtime state lets the Agent reuse an
implementation without rediscovery, download, or duplicate approval. A fresh
runtime context still follows its Skill-loading contract and cannot pretend
instructions are remembered. With no match, the Agent may search locally or
online. Download/inspection is not execution. First execution or changed
content/authority requires approval in the relevant Agent conversation; UI can
only display completed approvals. Real Skill name/source/version/hash,
approval, execution, and result references stay in the local research audit
and never enter server graph/catalog/hash state.

**User response.** “接受”.

**Final resolution.** Accepted. Local reuse guidance avoids repeated discovery
without turning Skill identity into server knowledge or weakening execution
approval.

**Rejected alternatives.**

- Putting Skill names in the server catalog causes identity pinning and
  repeated name-driven loading.
- Treating a prior load as remembered across a fresh model context violates
  runtime Skill contracts.
- Reapproving an unchanged Skill every time adds user friction with no new
  authority decision.
- Letting download imply execution bypasses the explicit approval requirement.
- Omitting local actual-use records makes research replay and audit impossible.

**Concrete counterexample.** A capability description matches an approved
local Skill with the same content and authority hash. A new Agent runtime can
resolve that local ref and follow its required load mechanism without searching
the internet or asking approval again. If the provider updates the Skill
content hash, reuse is rejected and execution requires a new conversation
approval.

**Acceptance evidence.**

- server graph/catalog/startup packet contains no actual Skill identity;
- unchanged compatible local match performs zero discovery/download/approval;
- fresh context still satisfies the runtime's full Skill-loading rule;
- changed content or authority cannot reuse execution approval;
- download/inspection cannot trigger execution;
- UI has no approval action;
- local audit records exact Skill identity/version/hash/approval/execution/result
  refs;
- Skill body is absent from default startup context.

## 138 — Deterministic backend assurance in Job terminalization

**Question/proposal.** Existing backend-assurance receipt persistence
duplicated RunSpec, ExecutionPlan, backend, result, and artifact facts already
owned by JobAttempt. The proposed deletion/deepening was:

```text
JobAttempt terminalization
  -> deterministic BackendAssuranceValidator
  -> same terminal transaction stores bounded assurance summary
```

The summary contains policy hash, backend revision, checks bitmap, anomaly
codes, result-summary/artifact-manifest hashes, and disposition. The validator
does not rerun computation. Conforming evidence is trusted by default and
included in the existing Job decision packet, with no reviewer wake or
assurance-table read. Concrete anomaly/hash conflict, implausible result, or
evidence-backed Agent suspicion opens Maintenance. Ordinary users cannot
access/modify backend source. Historical Jobs retain their original policy
hash when assurance policy changes.

**User response.** “好”.

**Final resolution.** Accepted. Keep the reliability capability while removing
its second persistence owner and normal-path database read/write.

**Rejected alternatives.**

- A separate receipt table repeats canonical terminal facts and creates another
  write/read.
- Rerunning every result for assurance doubles computation and does not prove
  independent correctness.
- Starting a backend reviewer for every conforming Job wastes token.
- Rewriting old Job assurance under a new policy changes historical audit
  facts.
- Allowing ordinary users or client Agents without source access to propose
  direct backend edits violates code-visibility boundaries.

**Concrete counterexample.** A Job terminates with matching RunSpec,
ExecutionPlan, backend revision, result hash, artifact manifest, and invariant
checks. Assurance is stored in the same terminal update and Research consumes
it from the changed Job packet. No assurance row, query, or Agent wake occurs.

**Acceptance evidence.**

- terminal Job transaction stores the bounded assurance summary;
- no independent backend-assurance receipt table/write remains after migration;
- conforming result adds zero reviewer calls and zero assurance lookup;
- validator performs no backtest rerun;
- anomaly opens one deduplicated Maintenance Case;
- ordinary source-inaccessible client cannot enter backend modification path;
- policy upgrade leaves historical summaries unchanged;
- graph transition consumes assurance already present in the Job packet.

## 139 — Preserve, quarantine, review, and rerun backend anomalies

**Question/proposal.** A Job assurance anomaly should preserve execution facts,
isolate only dependent evidence, and never rewrite history:

```text
anomalous immutable JobAttempt
  -> derived evidence-ineligible guard
  -> one deduplicated Maintenance Case
  -> deterministic evidence review
  -> conditional source-authorized Backend Reviewer
  -> false-positive disposition, or fix/new backend revision/new JobAttempt
```

No branch-pause row is added. Only transitions requiring that Job wait;
unaffected branches and Jobs continue. A case deduplicates by
Job/policy/anomaly hash. At most one Backend Reviewer runs only when
calculation semantics remain unresolved, and backend code access is limited to
Server Agent or source-authorized local Agent. False-positive disposition
references but does not rewrite the old assurance. A confirmed code defect is
fixed/tested/released on its owner branch and rerun as a new attempt; old and
new results coexist.

**User response.** “好”.

**Final resolution.** Accepted. Reliability review changes eligibility and
future execution, never historical Job facts.

**Rejected alternatives.**

- Deleting or overwriting the anomalous Job hides the failure and breaks replay.
- Pausing the entire Work Package wastes independent computation.
- Writing a separate branch pause duplicates a blocker derivable from canonical
  assurance/case state.
- Starting a Backend Reviewer before deterministic checks wastes token.
- Treating a fixed backend revision as if it produced the old result creates
  false provenance.

**Concrete counterexample.** One IC Job has a result-manifest mismatch while
two independent diagnostics are running. Only the transition consuming that IC
evidence waits. Maintenance confirms a writer defect, releases a new backend
revision, and creates a new attempt. The diagnostics complete; both IC attempts
remain auditable.

**Acceptance evidence.**

- anomalous Job row and artifacts remain immutable/queryable;
- evidence blocker is derived without a branch-pause write;
- duplicate anomaly hash creates no second case;
- unaffected branches/Jobs continue;
- deterministic checks precede any reviewer invocation;
- source-inaccessible Agent cannot inspect or modify backend;
- false-positive disposition does not rewrite Job assurance;
- confirmed fix produces new revision/new attempt and preserves both results.

## 140 — One minimal durable Maintenance Case queue

**Question/proposal.** Maintenance needs restart-safe claim/resume/dedup, but
must not become another project-management or event-sourcing platform. The
proposed single object contains case/kind, descriptor hash, status, bounded
affected/change refs, conversation ref, claimed Agent, latest result ref, and
timestamps.

All maintenance kinds share one table. Job, graph proposal, approval
conversation, Git commit, and test artifacts remain in their own owners; the
case only references them. There is no per-kind queue or case-event table.
Only material open/claim/block/resolve/reject changes write. Heartbeat,
duplicate observation, and unchanged resume write nothing. UI may inspect and
filter but cannot approve/disposition. Resolution wakes affected work once.

**User response.** “接受；最近你的问题我都同意了，你有没有不一样的问题，
或者把多个问题合并在一起问我”.

**Final resolution.** Accepted. Subsequent grill switches from incremental
single-detail confirmations to grouped questions only where genuine tradeoffs
or conflicts remain, as explicitly requested by the user.

**Rejected alternatives.**

- One queue per maintenance kind duplicates claim/resume/dedup logic.
- A case event-sourcing subsystem duplicates canonical conversation/Git/Job
  history.
- Storing complete diffs/logs/source in the queue increases database and
  context cost.
- UI approval controls violate the accepted conversation-only approval
  boundary.

**Concrete counterexample.** A backend anomaly already references its immutable
Job, approval conversation, fix commit, and test artifact. One case row tracks
current claim/status and those refs. A second event table would repeat history
that the canonical owners already preserve.

**Acceptance evidence.**

- exactly one Maintenance Case table serves all kinds;
- duplicate descriptor hash creates no second open case;
- no case-event or per-kind queue table exists;
- case rows contain refs, not copied source/diff/log/approval/test bodies;
- unchanged observation/heartbeat/resume performs zero write;
- UI exposes no approve/disposition action;
- one resolution emits at most one affected-work wake;
- restart restores open/claimed/blocked cases from the compact queue.

## 141 — Grouped unresolved tradeoffs: portability, retention, and trust

**Question/proposal.** At the user's request, three genuine conflicts were
grouped rather than continuing incremental implementation confirmations:

- **A — Agent portability:** owner-pin profiles in v1; allow seamless
  model/runtime changes within one Agent Flow owner, but require explicit
  atomic profile/budget/checkpoint transfer and old-owner claim revocation
  across owners. The alternative is a global broker read/write on every call.
- **B — TrialPlan retention:** retention-pin graph traces containing a
  TrialPlan while dependent runs/jobs/conclusions exist. Explicit deletion of
  the full dependent history releases the pin. The alternative is a separate
  TrialPlan store.
- **C — Graph governance threat model:** choose between a proportional
  single-developer control model and adversarial multi-tenant
  nonce/signature/attestation infrastructure.

**User response.** “AB都接受；C要检查一下行业语义以及晚上现有的图结构仓库”.
“晚上” is interpreted as “网上” from context.

**Final resolution.** A and B accepted. After reviewing current repository
gates plus LangGraph, OpenAI Agents SDK, Temporal, in-toto, LangSmith AuthN/Z,
and NIST AI RMF semantics, C was revised and accepted:

- ordinary runtime uses canonical checkpoint/history, deterministic hashes,
  and resource-level AuthN/AuthZ without per-transition HMAC;
- high-risk effects bind an authenticated conversation approval event to the
  exact action/diff/content hash and consume it once;
- independent signatures/attestations are required only when code/artifacts or
  actors cross a real software-supply-chain trust boundary;
- same-process/same-database launcher, capability, provider, and human HMAC
  layers are removed rather than treated as protection against compromise of
  that same process/database.

**User follow-up.** “接受；继续审计是否可以减少数据库对象”.

**Concrete counterexamples.**

- A: copying one local profile to two clients without transfer would let both
  spend the same remaining allowance.
- B: deleting a plan-bearing trace while preserving a dependent ResearchRun
  would leave only an unverifiable hash.
- C: an HMAC generated and verified by the same process/database does not
  defend against that process/database being compromised, while a remote
  untrusted build artifact may genuinely require signed provenance.

**Acceptance evidence for A/B.**

- cross-owner transfer atomically revokes the old claim before enabling the
  new owner;
- no global per-call broker is introduced in v1;
- referenced plan-bearing trace cannot be deleted independently;
- full dependent-history deletion releases the retention pin;
- branch close and graph activation do not delete retained TrialPlan evidence.

**Acceptance evidence for C.**

- ordinary transition requires no secret, signature, nonce, or provider-specific
  trusted receipt;
- AuthN and per-resource AuthZ prevent unauthorized graph/code/Skill actions;
- high-risk approval is exact-hash-bound, authenticated, unique, and
  single-use;
- replaying an approval for a different diff fails;
- server restart/runtime/model change does not require a provider-specific
  attestation adapter;
- signed provenance is tested only at configured cross-trust-boundary release
  points;
- removal of same-server HMAC tables/reads does not weaken the stated
  single-developer threat model.

## 142 — Reduce 20 Graph tables to six Graph plus two Agent Flow owners

**Question/proposal.** A deletion and owner-locality audit of the 20 tables
created by `server/services/research_graphs.py` produced this target:

```text
Graph Module
  graph_versions
  active_graphs
  graph_instances / Work Packages
  graph_branches / Hypothesis Branches
  graph_trace
  maintenance_cases

Agent Flow Module/store
  agent_budget_periods
  agent_invocations
```

The reduction folds:

- Agent execution/budget/reservation/provider receipt into the two Agent Flow
  owners;
- backend assurance into JobAttempt terminalization;
- current node capability resolution into graph branch;
- validation/proposal/review/audit/high-risk approval into bounded Maintenance
  Case gates and canonical external refs;
- rollback into an approved active-pointer change;
- capability execution approval into local conversation/audit state;
- same-server secrets/HMAC receipts out of the runtime.

Graph activation no longer copies draft JSON into a second active definition.
Graph content/version is immutable; activation and rollback update the active
pointer after one exact-hash-approved Maintenance Case. The six migration
batches independently cover Agent Flow, assurance, branch resolution, graph
governance, activation/rollback, and final shadow cleanup.

**User response.** “继续；我接受”, followed by “继续”.

**Final resolution.** Accepted. Stop incremental implementation-detail grill
after recording this target and perform a whole-plan coverage/contradiction
audit before implementation.

**Rejected alternatives.**

- Keeping twenty tables preserves duplicate owners and joins without a matching
  threat or lifecycle boundary.
- Merging branch and trace loses current-projection versus immutable-history
  semantics.
- Merging Work Package and Hypothesis Branch loses one-to-many research paths.
- Scanning graph versions instead of keeping an active pointer increases the
  routine read path.
- Moving Maintenance Case into research trace mixes platform governance with
  statistical research.
- Long-lived old/new schema dual write doubles I/O and creates reconciliation.

**Concrete counterexample.** Current activation reads proposal, reviews,
validation, audit, authorization, and graph version; consumes authorization,
inserts an active graph copy, and updates the pointer. The target reads one
immutable version and one satisfied Maintenance Case, then updates one pointer.

**Acceptance evidence.**

- final Graph Module schema contains exactly the six named owners;
- Agent Flow store contains exactly period and invocation owners for the
  accepted accounting scope;
- Job terminalization has no second assurance insert;
- current-node resolution requires no separate table read;
- activation reads one version and one bounded case, then changes one pointer;
- rollback creates no rollback row or graph-definition copy;
- each migration batch has a separate commit and rollback target;
- before/after SQL read/write/transaction counts and replay results are pinned;
- shadow migration proves equivalent current packets and decisions;
- legacy tables/APIs are removed after cutover rather than dual-written.

**Whole-plan coverage audit addendum.** The post-acceptance audit found four
canonical-document remnants from superseded designs:

- the opening token policy still required a provider HMAC receipt;
- server ownership and delivery slices still implied separate proposal/review
  persistence;
- Process Miner, Graph Curator, Capability Agent, Implementation Agent, and
  Audit Presenter were still described as persistent roles rather than modes
  or bounded tasks;
- acceptance tests still required separate branch token aggregates, token
  budget reads, and node-resolution persistence.

Those remnants were removed from the working plan and governance context.
Historical question text remains unchanged as decision-evolution evidence.
The executable migration map now accounts for every current table exactly
once, and restores the previously accepted order:

1. Agent Flow hard budget and execution ownership;
2. JobAttempt terminal assurance;
3. Maintenance Case governance and proportional trust;
4. branch-local context and resolution;
5. immutable version/active-pointer activation and rollback;
6. compatibility removal plus measured database hot-path floor.

This addendum introduces no new semantic choice. It makes decision 142
consistent with accepted decisions 118 and 124–141 and supplies the deletion,
conversion, test, and rollback coverage required before implementation.

## 143 — Research Obligation Cycle

**Final resolution.** Accepted through Grill 143.6 and the subsequent legacy
access refinement.

Factor research uses scoped Research Claims, extensible Verification
Obligations, factual Evidence Envelopes, paired atomic adjudication, and
defeasible bounded closure. These semantics reuse the existing Work
Package/Hypothesis Branch, graph trace, Maintenance Case, capability, and local
Skill-audit owners. They do not create a second graph or dedicated persistence
services.

Legacy Evidence Envelopes are privileged historical audit records and are
unavailable to Research Agents, Reviewers, Skills, and ordinary Agent
retrieval. Deterministic compatibility sees only bounded
version/hash/eligibility metadata; reopened work creates new current-schema
evidence.

The complete question-by-question record, source qualifications,
counterexamples, accepted ownership, and implementation boundary are preserved
in
[`0143-cognitive-obligation-cycle.md`](0143-cognitive-obligation-cycle.md).
Delivery batches and gates are defined in
[`research-obligation-cycle-work-package.md`](../research-obligation-cycle-work-package.md).

## 147 — FTClient primary navigation and nested destinations

**Question/proposal.** Treat the application sidebar as the unified launcher
for every available business module, with Home only as a duplicate shortcut
surface and the opened-items section as the sole representation of active
worksites.

**User response.** Revised: “左侧只展示主要功能快捷入口，首页作为主入口；有些打开时候是
web，有些打开是另一个左侧导航栏，注意这个左侧的宽度不要太长；左下部分地背景色不要
和别的地方不同”.

**Final resolution.** Home is the complete primary launcher. The application
sidebar contains only the small set of major shortcuts plus active opened
worksites; it is not a duplicate catalog of every server module. A destination
may be an embedded Web module or an original native management surface with
its own compact secondary sidebar. Nested sidebars must have a bounded narrow
width and may not displace the primary work content. Account and Settings stay
at the lower edge of the application sidebar but share its continuous
background and visual treatment rather than appearing as a separately colored
footer block.

**Evidence and affected boundary.** User correction of the proposed
information architecture; affects FTClient navigation, module registry
projection, embedded Web routing, native split-view sizing, and UI acceptance
tests. It does not change server module ownership or Factor Research Graph
semantics.

**Acceptance evidence.**

- Home exposes all authorized modules and remains their canonical discovery
  surface.
- The application sidebar exposes only the agreed major shortcuts and active
  worksites; it does not mirror the entire server module manifest.
- Both embedded Web destinations and native destinations with a compact
  secondary sidebar open and remain usable.
- Secondary sidebars have an explicit compact width contract and do not grow
  with long labels.
- Account and Settings use the same continuous sidebar material/background as
  the rows above them.

## 148 — Separate factor authoring from Profile research records

**Question/proposal.** Keep the Profile factor worktree limited to factor
source, authoring metadata, typed stubs, and authoring tools. Move reports,
trials, obligations, evidence references, checkpoints, and other process
records under the Profile's `research/` root; retain `local-data/` and
`adapters/` as separate Profile-owned roots and remove the obsolete empty
`workspaces/` layer.

**User response.** Accepted, then asked whether this changes the Active Graph
intermediate-report storage-address semantics.

**Final resolution.** Accepted. It changes report ownership and reference
resolution, not graph topology. The Factor Research Graph and server
projections retain only bounded stable report/artifact references. They must
not persist a device-specific absolute path. The local Profile manager resolves
those references inside that Profile's `research/` root. The factor worktree
contains authoring inputs only and may no longer be the storage owner for
research reports or mutable process state.

**Evidence and affected boundary.** The current deterministic renderer already
writes below a caller-supplied `workspace_root/research/`, while old imported
factor worktrees still contain `research_reports/`. This decision makes the
caller root explicitly the Profile root and requires migration of legacy
reports. It affects local layout, report-reference resolution, migration,
backup/delete safety, UI lookup, and release acceptance; it does not add a
Graph node, table, or absolute-path field.

**Acceptance evidence.**

- generated factor worktrees contain no mutable research-process owner;
- every new report and report index resolves below the owning Profile's
  `research/` root;
- graph/server payloads contain stable bounded refs rather than local absolute
  report paths;
- moving the entire per-user root preserves report lookup after deterministic
  rebinding;
- legacy `research_reports/` content is inventoried and migrated without
  overwriting or silently merging reports from different Profiles;
- obsolete empty `workspaces/` directories and contracts are removed after
  compatibility audit.

## 149 — Work Package and Hypothesis Branch report hierarchy

**Question/proposal.** Make one UI-visible research correspond to one
user-authorized Work Package. Store a compact deterministic index and aggregate
report at that research root, with branch-level intermediate reports nested by
Hypothesis Branch and report assets kept separately. Trial Plans, obligations,
claims, evidence, and graph transitions remain structured references rather
than being flattened into Markdown.

**User response.** Accepted.

**Final resolution.** The local Profile research hierarchy is:

```text
research/<work-package-id>/
  INDEX.json
  REPORT.md
  branches/<hypothesis-branch-id>/REPORT.md
  assets/
```

`INDEX.json` is a bounded deterministic UI projection, not a new canonical
event store. The Work Package report is a derived aggregate; branch reports are
derived intermediate projections. Canonical state remains with the accepted
Graph/Agent Flow/Job owners and stable refs. Adding PDF or other render targets
later does not change this hierarchy or make a rendered document authoritative.

**Evidence and affected boundary.** User acceptance plus existing report
renderer behavior, which currently writes a flat
`research/branches/<branch-id>/REPORT.md`. A Work Package can own multiple
Hypothesis Branches, so the current flat path loses the UI-visible research
owner. This affects deterministic report rendering, local reference
resolution, profile research UI, migration, and report tests; no Graph node or
database object is added.

**Acceptance evidence.**

- two Work Packages may contain branches with the same local label without a
  path collision;
- branch changes incrementally regenerate only their branch report and the
  affected bounded Work Package index/aggregate;
- unchanged inputs cause no report rewrite or database write;
- UI can navigate research → branch → Trial/obligation/evidence/report section
  through structured refs;
- moving the user root preserves all relative references;
- Markdown, later PDF, and assets can be deleted and regenerated without
  losing canonical research state.

## 150 — Data storage follows source ownership, not Agent Profile

**Question/proposal.** Move large market-data bundles out of Profile roots and
share them once under the user root, while keeping only dataset references and
authorization scope in each Profile. Keep research-specific derived scratch
inside its Work Package. Install Adapter executables once; retain configuration
in local manager state and credentials in Keychain.

**User response.** Accepted, then clarified that the server currently manages
the Local Bundle and asked whether server-source wide tables must remain on the
server.

**Final resolution.** Accepted after ownership refinement. A data source is not
moved into `users/<principal>/data` merely because a client-side Research Agent
uses it. Server-managed sources, including the current Local Bundle and any
server-built minute wide tables, retain their canonical raw and derived storage
on the server. Client Profiles receive only bounded source identities,
availability/coverage projections, authorization, RunSpec bindings, and result
or artifact references. `users/<principal>/data` is reserved for data owned or
registered by that user on that client. Profiles reference those shared user
sources and do not duplicate their bytes. Research-specific temporary derived
data may live below the owning Work Package and is not promoted to a source
without explicit registration.

**Evidence and affected boundary.** The present FactorTester backend resolves
LocalCNFutures from its configured provider storage root; Profile `local-data/`
directories are empty migration scaffolding. This affects data-source
registration, Data Availability Profile, client settings, local layout,
connector policy, export/cache policy, and migration. It does not make an
Agent Profile, Work Package, or Active Graph the storage owner of market data.

**Acceptance evidence.**

- creating MaxA or MaxB performs no server dataset or wide-table copy;
- a server-managed source is represented locally by bounded identity,
  availability, authorization, and references only;
- a user-owned local source is stored once below the user's data root and may
  be referenced by multiple Profiles subject to authorization;
- no Profile `local-data/` or `adapters/` directory is created without a real
  Profile-owned payload;
- source identity and data revision, rather than a device path, bind RunSpec
  and evidence;
- client export or cache of server data remains a separate policy decision and
  cannot silently change the source owner.

## 151 — Unified data-source management with owner-routed actions

**Question/proposal.** Add one Data Sources management destination that groups
server-managed sources, user-owned local sources, and external connectors while
preserving their distinct authority and storage boundaries. Make it a Home
module and one of the small set of major sidebar shortcuts.

**User response.** Accepted.

**Final resolution.** FTClient exposes one unified Data Sources surface. A
server-managed source shows bounded identity, product/frequency/time coverage,
revision, update status, availability, and current-user authorization. Ordinary
users may inspect and select it; only a server-authorized operator may trigger
server updates, wide-table rebuilds, or disablement, and server filesystem paths
are never exposed. A user-owned local source may be registered, removed,
coverage-checked, and authorized to Profiles by that user. An external
connector exposes market, stream mode, latency/delay declaration, entitlement,
connection state, and heartbeat; secrets remain in Keychain and persistence of
its observations requires a separate explicit local-source setting.

The Data Sources page owns source lifecycle and availability. A Profile page
owns only that Profile's source grants. The Planning Agent consumes the grants
through a bounded Data Availability Profile and cannot broaden product or data
authorization. UI actions route to the actual source owner rather than
presenting one fake universal CRUD API.

**Evidence and affected boundary.** User acceptance, server-provider ownership,
local Profile layout, and the previously accepted Data Availability Profile
semantics. Affects Home/module registration, primary shortcuts, source APIs,
role/entitlement guards, connector status, Profile grants, and UI tests. It adds
no research-graph state or duplicate dataset catalog.

**Acceptance evidence.**

- one page clearly separates server, user-local, and connector sources;
- a non-admin cannot invoke server update/rebuild/disable actions;
- no response exposes a server raw path or credential;
- local-source registration stores bytes once below the user data root;
- Profile grants reference source identities and create no copy;
- Tiger-like connectors distinguish live, delayed, paper, disconnected, and
  unknown rather than collapsing them to `available`;
- Planning receives only authorized bounded availability facts.

## 152 — Atomic Profile initialization binds metadata and local source truthfully

**Question/proposal.** Replace the current visually separate Profile creation,
server-library binding, and factor-worktree setup with one atomic guided
initialization. The Profile is always bound to the currently authenticated
principal; the user selects an authorized registered factor-library projection,
while the client independently verifies whether the corresponding editable
canonical source exists locally. A server metadata projection may not be
presented as materialized source.

**User response.** Accepted. The user additionally required every UI capability
to be available through FactorTester CLI so non-macOS users are not excluded.

**Final resolution.** Profile initialization binds two explicit facts:

1. an authorized server factor-library metadata/evidence projection; and
2. an editable local canonical repository plus a Profile branch/worktree, when
   local source is actually available.

The creation surface has no principal picker. It uses the authenticated
principal and defaults to that principal's own authorized library. If the
canonical source is absent, initialization truthfully reports metadata-only
status and routes to explicit import or source-sync configuration; it does not
generate an apparently editable worktree from non-reconstructable server
metadata. When both facts exist, the operation produces one verified Profile
identity, initialization-source binding, factor-worktree binding, and claimable
Agent identity. MaxA and MaxB may share principal `18717974771` and one canonical
Git object store while retaining `agent/maxa` and `agent/maxb` worktrees.

**Evidence and affected boundary.** Current Swift creation immediately creates
a worktree for the authenticated principal, while the separate initialization
view binds a source-free server projection. Current CLI correctly declares
`source_materialized: false`; the UI currently obscures this distinction.
Affects Profile wizard, CLI transaction/rollback, receipts, source import/sync,
claim readiness, and UI/E2E tests.

**Acceptance evidence.**

- no UI or CLI create command accepts a different principal from the active
  authenticated session;
- metadata-bound and editable-source-ready are distinct visible statuses;
- metadata-only initialization creates no fake factor source;
- one successful full initialization of MaxA and MaxB yields distinct branches
  and worktrees sharing the same verified canonical repository;
- failure at any stage either leaves no new Profile or produces an explicit
  resumable receipt, never a silently half-ready Profile;
- a successful Profile exposes a compact one-command Agent claim/resume surface.

## 153 — CLI-first functional parity for every business capability

**Question/proposal.** Require every business query and mutation visible in
FTClient to have a stable FactorTester CLI equivalent with machine-readable
output. Permit the native UI to call the same HTTP/SSE/artifact surface directly
where interaction or performance requires it, but forbid Swift-only business
rules. Exempt only device-local presentation preferences that change no
business fact.

**User response.** Accepted.

**Final resolution.** FactorTester CLI is the cross-platform public capability
surface. Every business capability exposed by FTClient must have a documented,
scriptable, non-interactive CLI path with stable JSON output, explicit exit
status, bounded introspection, and equivalent authorization/validation. Local
lifecycle UI normally invokes the packaged CLI. Embedded Web and live views may
use the same HTTP API, SSE, or artifact references directly, but an equivalent
CLI command must exist and both surfaces must share the same backend semantic
owner. FTClient cannot implement Profile, source, research, report, update,
sync, authentication, or authorization policy independently in Swift.

Window geometry, current tab, sidebar expansion, language, theme, and similar
display-only device preferences need no CLI command. Login/logout, password
change, update-channel selection, Profile initialization/claim, source
management/grants, research progress, report lookup, and source sync are
business or operational capabilities and require CLI coverage.

**Evidence and affected boundary.** User requirement for non-macOS access and
the `cli-anything` methodology: real backend use, JSON introspection, installed
command subprocess tests, and truthful output verification. Affects command
inventory, shared service ownership, Swift adapters, public-client packaging,
Windows/Linux usability, and release gates.

**Acceptance evidence.**

- a generated manifest maps every non-presentation UI action to a public CLI
  capability and fails release validation on an unmapped action;
- no Swift code directly owns a business invariant that is absent from the CLI
  backend/service;
- the installed CLI completes representative Profile, data-source, research,
  report, authentication, and update workflows from an arbitrary working
  directory;
- each mapped command has stable JSON, non-zero failure status, and clear
  remediation without requiring a display;
- CLI and UI conformance tests produce the same resulting authoritative state;
- absence of FTClient does not prevent Linux/Windows users from performing any
  supported business workflow.

## 154 — Separate Agent Profile management from Work Package research sites

**Question/proposal.** Remove Trial Plans, obligations, Evidence, reports, and
live research navigation from the Profile management page. Keep the Profile
page focused on identity and execution environment, while Research Progress
lists Work Packages directly and opens each Work Package as an independent
application tab with a compact secondary sidebar.

**User response.** Accepted, with the requirement that every research surface
records and displays which Agent Profile owns the research.

**Final resolution.** An Agent Profile is a managed Agent identity and local
execution environment. Its page owns status, authenticated principal,
claimable Agent identities, factor-worktree initialization, data-source grants,
resource limits/usage, Adapter/runtime state, and a bounded research-summary
link. A Research Site is one Work Package and opens independently of Profile
settings. Its compact secondary navigation owns Overview, Hypothesis Branches,
Trial Plans, Claims/obligations, Evidence/Run/Job references, reports/assets,
and Capability Gap or Maintenance status.

Every Research list row, open tab, detail header, and rendered report must carry
the owning Agent Profile identity. Agent ID or model/runtime identity alone is
insufficient. One Profile may own multiple concurrent Work Packages. Disabling
a Profile prevents new execution but does not hide or delete its existing
read-only research history.

**Evidence and affected boundary.** Current `ProfileWorkspaceView` mixes six
research sections into Profile management, while `ProfileResearchOverview`
only jumps back to a Profile. This contradicts the accepted one-Work-Package
research hierarchy. Affects navigation, research projection, Profile summary,
report headers, filtering, disabled-state behavior, CLI commands, and UI tests.

**Acceptance evidence.**

- Profile management can be used without loading full research details;
- Research Progress lists Work Packages, not only Profiles, and supports
  Profile/status/product filters;
- each Work Package opens in its own top-level tab with a bounded narrow
  secondary sidebar;
- all research and report surfaces visibly identify the owning Profile;
- Profile disable/delete safety preserves attributable research history;
- CLI can list/open the same Work Packages and Profile attribution without UI.

## 155 — Preserve Profile attribution across explicit research handoff

**Question/proposal.** Give each Work Package an immutable creating Profile and
a current owning Profile. Retain the acting Profile on each transition,
invocation, Run/Job submission, and report revision. A handoff occurs only at an
explicit checkpoint and never rewrites old history or moves old reports.

**User response.** Accepted, with the requirement that the research-report
checkpoint display the handoff information.

**Final resolution.** `created_by_profile_ref` is immutable and
`current_owner_profile_ref` changes only through an explicit checkpointed
handoff. Existing graph trace, Agent invocation, and execution actor references
are used for step attribution rather than a parallel Profile-event store.
Profile display names may change, but stable Profile refs and historical
display snapshots keep records understandable. A handoff atomically revokes the
old execution claim, binds the new owner, and resumes from a hash-verified
checkpoint; it does not rewrite old transitions, Jobs, branches, or reports.

The research timeline and the derived report section for that Coordination
Checkpoint display the source Profile, destination Profile, effective time,
checkpoint/resume reference, and bounded authorization reference. They do not
embed the full conversation or approval body. When creator and current owner
are identical, ordinary UI shows one concise owner label; when different, it
shows both creator and current owner plus the latest acting Agent identity.

**Evidence and affected boundary.** User acceptance and explicit report
checkpoint requirement; consistent with owner-pinned Agent identities and
atomic cross-owner transfer. Affects Work Package projection, Agent Flow claim,
trace actor metadata, report snapshot schema, UI timeline/header, CLI handoff
commands, and restart/replay tests. It adds no dedicated handoff event table.

**Acceptance evidence.**

- no two Profiles can execute the same Work Package claim after a completed
  handoff;
- failed handoff leaves the old owner active and creates no partial report;
- old steps and Jobs retain their historical actor Profile;
- the checkpoint and report show MaxA → MaxB with bounded refs after a sample
  transfer;
- report regeneration produces the same handoff section from canonical refs;
- CLI and UI expose the same current owner, creator, and handoff history.

## 156 — Hard-delete only unused Profiles; archive attributable identities

**Question/proposal.** Permit physical deletion only for a never-used Profile
with no research, execution, branch, budget, or audit reference. A referenced
Profile is archived: its claims are disabled, its history remains resolvable,
and its clean local worktree may be released without deleting retained Git
history or research records.

**User response.** Accepted.

**Final resolution.** Profile lifecycle distinguishes empty hard deletion from
historical archival. Hard deletion fails closed if any Work Package, branch,
transition, invocation, Run/Job, report, budget period, Git binding, handoff, or
audit reference exists. Archival revokes new claim/execution authority and hides
the Profile from default active views while preserving stable identity and all
attribution. A clean local worktree may be removed only through a verified
space-reclamation operation; canonical branches/commits and research records
remain. Archived Profiles are filterable and may be restored without changing
their stable identity.

UI wording must not imply that archival erases history. Deleting or archiving a
Profile never cascades to Work Packages, reports, Jobs, evidence, or usage
history. CLI provides inspect, delete-plan, archive, restore, worktree-release,
and verify equivalents with JSON and explicit refusal reasons.

**Evidence and affected boundary.** User acceptance and the Profile attribution
requirements of decisions 154–155. Affects lifecycle guards, worktree cleanup,
Git retention, UI filters/actions, CLI parity, and migration. It reuses existing
canonical references and adds no tombstone-event table.

**Acceptance evidence.**

- a truly empty Profile can be deleted and then cannot be claimed;
- a referenced Profile hard-delete is refused with bounded blocking refs;
- archival disables execution while all old research/report attribution remains
  readable;
- dirty or unpushed worktree state blocks space reclamation;
- releasing a verified clean worktree retains its branch commits and reports;
- restore reactivates the same Profile ID and does not duplicate usage/history.

## 157 — Distinguish and aggregate local and server factor libraries

**Question/proposal.** Separate Settings-owned local storage/canonical-repository
management, server factor-library metadata/evidence, and Profile worktree
management into distinct UI owners. The initial proposal treated the Factor
Library entry as the server catalog only.

**User response.** Revised the Factor Library part. The FTClient Factor Library
must be a newly built local factor-library surface. The existing Web factor
library remains the server-stored catalog. They may share one entry, but must be
clearly distinguished and organized factor family → user/Profile. Versions of
one family across Profile Git histories must be grouped and navigable backward
and forward, with version, parameters, applicability, and research evidence.

**Final resolution.** Settings → Local Storage and Workspaces owns physical user
root/canonical-repository registration, migration, capacity, health, and linked
worktree repair. Profile owns its branch/worktree, source grants, and sync
policy. Neither responsibility belongs to a Factor Library catalog.

FTClient's Factor Library becomes a native, CLI-backed aggregate with explicit
source facets:

- **Local** indexes the authenticated user's canonical factor repository and
  authorized Profile worktrees without uploading source;
- **Server** renders the existing source-free server registration, parameters,
  applicability, and research evidence;
- **Combined** groups matching identities under one factor-family tree while
  preserving Local/Server badges, user/Profile attribution, editable-source
  availability, Git/semantic identity, and visibility permission.

The primary hierarchy is Factor Family → semantic version/lineage → owning user
and contributing Profile revisions → parameter configurations and scope-bound
evidence. Matching local and server projections may appear as one version row
with multiple provenance badges; nonmatching hashes must remain separate and
must never be merged by display name alone. The existing Web page remains a
server-only view and must be labelled as such when opened from the aggregate.

**Evidence and affected boundary.** User correction and code inspection: current
`ClientTab.factorLibrary` opens only the server Web route; no native local Git
family/version catalog exists. Affects local indexing CLI, factor identity and
lineage projection, native UI, server projection merge, source/privacy guards,
research deep links, and release tests. It does not move source to the server.

**Acceptance evidence.**

- the Factor Library entry visibly distinguishes Local, Server, and Combined;
- local indexing works offline and reads canonical/worktree source without
  modifying Git or uploading content;
- server-only entries never expose or imply local editable source;
- families with matching verified identity group together across user/Profile
  and provenance, while same-name/hash-mismatch entries remain visibly split;
- version, parameters, applicability, Profile/user attribution, and evidence
  are accessible without loading all source or reports;
- all local indexing, filtering, version navigation, comparison, and server
  projection queries have CLI equivalents.

## 158 — Navigate complete factor lineage and multiple classification axes

**Question/proposal.** Initially proposed semantic-version rows with previous /
next navigation, canonical monotonic versions, and Profile Draft Revisions shown
as sibling branches until promoted. Parameter configurations remain below a
family version and evidence never transfers across version identity silently.

**User response.** Revised the navigation: it must display a tree like Git
branch divergence, not only previous/next. In addition to factor-family-name
indexing, navigation and filtering must support user-defined categories and
tags plus the Web convention that derives a category from the first CamelCase
component.

**Final resolution.** Factor history is a lineage graph rendered with a compact
Git-like branch navigator. It shows common ancestors, independent Profile
Draft Revisions, canonical promotion, supersession, and merge ancestry where
present. Previous/next remains only a keyboard or detail shortcut along a
selected lineage; it is never the complete model. A version record carries
stable family identity, semantic contract/hash, Git commit, contributing
Profile/user, and one or more explicit parent version refs. The UI does not
infer false total order from commit timestamps or display names.

Only formula, parameter schema, default direction, data-field, timing, or
alignment semantic changes create a Factor Family version. Report/comment/
unrelated Git changes do not. Canonical promoted versions receive user-library
monotonic numbers; unpromoted Profile changes remain visibly attributed Draft
Revisions until promotion. Parameter values are configurations below a version,
and scope-bound evidence binds version plus configuration hash.

The Factor Library supports simultaneous, composable navigation/filter axes:

- Factor Family name and text search;
- user-defined categories;
- user-defined tags;
- deterministic first-CamelCase-component grouping using the existing shared
  `factor_group_key` convention (`MmVolWgtRet` → `Mm`);
- user, Profile, Local/Server provenance, version/draft state, applicability,
  and evidence availability.

The CamelCase group is derived and read-only. It does not replace an explicit
category or tag and does not alter factor identity. The same grouping function
and test vectors are shared by Web, CLI, and native UI rather than reimplemented
three times.

**Evidence and affected boundary.** User correction plus current code
inspection: Web/server already derive the first CamelCase group through
`factor_group_key`, while current FTClient has no local lineage navigation.
Affects local Git index, factor-version contract, native lineage renderer,
classification/filter CLI, combined Local/Server projection, and conformance
tests. It does not treat the factor lineage as the Factor Research Graph.

**Acceptance evidence.**

- a canonical v7 with MaxA and MaxB child drafts renders one forked lineage,
  not a fake v8/v9 sequence;
- a promoted or merged revision retains explicit parent linkage and all
  version-specific evidence;
- non-semantic commits create no new Factor Family version;
- name, custom category, tag, CamelCase group, user, and Profile filters compose
  and return the same identities in CLI and UI;
- shared test vectors prove identical CamelCase grouping in server/Web, CLI,
  and FTClient;
- lineage loading is bounded/paginated and does not scan every repository or
  load source bodies on each selection.

## 159 — Separate derived, declared, and user-organizational classification

**Question/proposal.** Distinguish deterministic CamelCase grouping, the
factor's declared `category` metadata, and user-owned organizational categories
and tags. Store user organization once at user scope rather than separately in
every Profile. Default it to the Factor Family, allow explicit version/Draft
targets, retain source provenance, and make metadata-only server publication an
explicit action that never uploads source.

**User response.** Accepted. The user then identified a research-process gap:
factor correction or enhancement may require a category change, and the
existing revision flow does not explicitly adjudicate classification or when
enhancement requires a new factor.

**Final resolution.** Classification has three independent axes:

- `derived_group` is the shared read-only first-CamelCase grouping;
- `declared_category` is versioned descriptive factor metadata; a category-only
  correction creates a metadata revision rather than a calculation version;
- user categories/tags are a user-scoped catalog overlay, applied to a Factor
  Family by default and explicitly targetable to a version or Profile Draft.

The overlay is stored once in the user-local catalog, not in each Profile or
factor source body. Profile-originated changes retain acting-Profile
attribution. Local and server classifications keep provenance and do not
overwrite each other automatically. Explicit metadata-only publication may
send selected categories/tags to the server without source, expression, or
local paths. Every operation has a CLI command and atomic local update.

**Evidence and affected boundary.** User acceptance, existing source-level
`category` metadata, and the deterministic Web prefix grouping. Affects local
catalog schema, filter/index CLI, native UI, optional metadata-only sync, and
classification provenance. The research identity/classification delta raised
by the user is deferred to decision 160 rather than hidden inside catalog UI.

**Acceptance evidence.**

- changing a user tag does not alter Factor Family or configuration identity;
- a declared-category-only edit creates no semantic factor version;
- one user overlay is immediately visible from MaxA and MaxB without duplicate
  files or database rows;
- version/Draft-specific tags do not leak to sibling lineage nodes;
- server and local tags show provenance and conflicting values side by side;
- metadata-only publication is explicit, source-free, CLI-backed, and
  reversible without modifying factor Git history.

## 160 — Adjudicate factor identity and classification together on revision

**Question/proposal.** Add a required identity disposition and classification
delta to existing factor-semantics, improvement, and new-hypothesis paths rather
than creating a classification node. Distinguish metadata correction,
same-family semantic version, and new-family derivation by economic meaning,
input/output contract, and comparability—not category change alone.

**User response.** Accepted.

**Final resolution.** Every factor revision proposal that affects declared
classification carries:

```text
identity_disposition = metadata_revision
                     | same_family_new_version
                     | new_family
classification_delta
reason_refs
```

A category/tag-only correction with unchanged computation is a metadata
revision. An implementation defect corrected back to the same declared economic
meaning remains the same family but creates a new immutable semantic version;
the old version and evidence are retained. An enhancement that preserves the
core hypothesis and comparable output normally creates a same-family version.
An enhancement that materially changes prediction target, economic mechanism,
input domain, trading role, output interpretation, or preserves both old and
new factors as independently meaningful creates a new family with explicit
`derived_from` lineage. User catalog organization never changes factor identity.

“Directly modify” therefore permits editing the same family source path but
never overwriting a tested version identity or transferring its evidence. The
current `factor_semantics`, `factor_improvement_required`, and
`start_new_hypothesis_lineage` protocol validates the disposition, semantic
hash/parent refs, classification delta, and new-trial consequences. An ambiguous
material identity decision may invoke one semantic reviewer; routine metadata
changes use deterministic validation and no reviewer.

**Evidence and affected boundary.** User acceptance, decisions 62–66 and
103–106, and current graph edges/guards. Current `factor_revision_refs` only
require resolved status and omit identity/classification disposition. Affects
factor-semantics evidence schema, server guards, lineage catalog, research
report, local factor-version CLI, and conformance/replay tests. It adds no graph
node, database object, or routine LLM call.

**Acceptance evidence.**

- a category-only change leaves semantic factor/config hashes unchanged and
  creates only a metadata revision;
- a corrected bug creates a child version in the same family and leaves old
  evidence attached to the old version;
- an auxiliary enhancement preserving the hypothesis can remain a same-family
  child, while a changed mechanism creates a derived family;
- ambiguous new-family decisions require one bounded reviewed warrant;
- missing or inconsistent disposition/classification delta blocks the existing
  semantics/new-hypothesis edge;
- replay and UI lineage reproduce the accepted disposition without loading
  source into the server.

## 161 — Promote Profile Drafts through conversation approval and CLI execution

**Question/proposal.** Let FTClient inspect and compare a Profile Draft and
initiate an Agent-conversation request, but never approve or directly merge a
factor-source promotion. After exact-hash conversation approval, FactorTester
CLI verifies the Draft, lineage, semantic/classification disposition, typing,
tests, and Git state, then promotes it to canonical and allocates the formal
version. Ordinary user catalog tags/categories remain direct metadata actions.

**User response.** Accepted.

**Final resolution.** A Draft promotion is an exact-content high-risk action:

```text
Profile Draft
  -> bounded CLI diff and identity/classification proposal
  -> Agent conversation grill/approval for the exact hash
  -> deterministic CLI verification and canonical integration
  -> formal version allocation and lineage refresh
```

FTClient may display source-available diff summaries, formula/parameter schema/
classification/applicability deltas, Pyright/test status, evidence status, and
pending/accepted/rejected/promoted/conflicted state. It may route or copy one
compact command into an Agent conversation. It has no approve/merge bypass and
cannot collapse sibling Profile branches automatically. Test success does not
replace research-semantic review.

CLI promotion binds Draft commit/patch hash, parent family version,
`identity_disposition`, `classification_delta`, validation results, and the
authenticated single-use conversation-approval reference. It refuses stale,
dirty, mismatched-parent, scope-expanded, or unapproved content. Successful
integration updates the canonical repository, allocates a formal version, and
refreshes the local/server lineage projection as authorized. User catalog
category/tag edits do not mutate source or require this promotion path.

**Evidence and affected boundary.** User acceptance, conversation-only approval
policy, decisions 141 and 157–160, and Profile Git worktree semantics. Affects
factor-library comparison UI, Agent routing, promotion CLI, exact-hash approval,
Git integration, version allocation, lineage projection, and release tests. It
adds no UI approval authority or second merge service.

**Acceptance evidence.**

- UI cannot produce a canonical source change without the CLI and a valid
  exact-hash conversation approval;
- changing the Draft after approval makes promotion fail;
- sibling MaxA/MaxB Drafts remain distinct until an explicitly reviewed
  integration resolves them;
- dirty worktree, parent mismatch, Pyright failure, or semantic-test failure
  blocks promotion without mutating canonical;
- success allocates one formal version with correct parent/merge lineage and
  retains the Profile Draft provenance;
- tags/categories can change independently without invoking source promotion.

## 162 — Checkpoint-driven structured reports with polished interaction

**Question/proposal.** Materialize report projections only at meaningful
research checkpoints, update bounded structured indexes first, write Markdown
only when the content hash changes, and make the native UI an interactive
bidirectional view between timeline steps and report sections. Markdown/PDF are
secondary render targets; charts are lazy views over existing Job artifacts.

**User response.** Accepted, with an explicit requirement that the resulting UI
be visually polished. The user then corrected factor-worktree UI ownership:
FTClient does not edit factor source code; humans and Agents edit their
respective workspaces with an external IDE, while structured factor metadata
and synchronization remain FTClient responsibilities.

**Final resolution.** Report projection runs on Hypothesis/TrialPlan freeze,
trusted Job Evidence, Claim/obligation adjudication, Profile handoff,
Capability Gap/Maintenance disposition, bounded closure, reopen, or final
research decision. Heartbeat, percentage progress, polling, and ordinary page
refresh do not regenerate reports. `INDEX.json` is updated atomically as a
bounded local projection; a branch report and affected Work Package aggregate
are written only on changed source hash. This creates no report table or routine
database write.

FTClient renders a polished structured research site: selecting a timeline
checkpoint highlights its Trial, obligation, Claim, Evidence, Run/Job, handoff,
and report sections; selecting a report section navigates back to its producing
checkpoint. Provisional, accepted, superseded, blocked, and unavailable states
are visually distinct without relying on raw status strings alone. Markdown is
an optional full-text artifact and future PDF is another render target for the
same snapshot. Charts load or render lazily from verified Job artifacts only on
explicit view/report demand and never on unchanged polling.

**Evidence and affected boundary.** User acceptance and visual-quality
requirement, report decisions 148–149/155, and current deterministic renderer/
structured-detail UI. Affects checkpoint projection, report index/renderers,
asset loading, native interaction and visual acceptance. The worktree correction
is resolved separately in decision 163.

**Acceptance evidence.**

- ordinary progress/heartbeat causes zero report writes and zero chart render;
- each listed checkpoint produces at most one changed index/report projection;
- timeline → report and report → checkpoint navigation is deterministic and
  preserves Profile/handoff attribution;
- Markdown/PDF/assets can be regenerated from bounded canonical refs;
- unavailable/unauthorized assets remain truthful rather than blank or fake;
- screenshot and UI automation cover compact hierarchy, typography, spacing,
  loading/empty/error states, long labels, light/dark appearance, and Chinese/
  English layouts at supported window sizes.

## 163 — No embedded source editor; structured contract editing remains in UI

**Question/proposal.** Keep all Python/factor-expression source editing outside
FTClient. Let FTClient display the source-derived parameter schema and edit only
its permitted default-value and descriptive annotations, together with declared
category, factor description, and user tags through FactorTester CLI. Provide
CLI-backed synchronization in FTClient, while leaving Profile branch Git
operations to the owning Agent.

**User response.** The user explicitly corrected the boundary: UI must not edit
factor source; users and Agents edit in their corresponding workspace using
VS Code or another IDE. UI synchronization is required. The user then refined
the parameter boundary: parameter schema itself is not editable in UI; only
default values and descriptions may be changed.

**Final resolution.** FTClient has no embedded
Python, formula, or raw-expression editor. It may open the human canonical
workspace in an external IDE and expose a bounded command/cwd for an Agent to
resume its Profile worktree. Parameter names, types, required/optional status,
constraints, and structural relations are source-derived and read-only in UI;
changing them requires an external source edit followed by CLI rediscovery and
validation. UI may edit only the permitted default-value layer and descriptive
annotations. Category, factor description, and tags follow their existing
metadata/version rules.

UI synchronization defaults to source-free factor identity/version metadata,
parameter annotations, category/description/tags,
applicability, and research evidence. It never turns the Profile worktree into
a UI-managed Git branch. Source handling follows the explicit three-mode policy
in decision 170: metadata-only, persistent private source synchronization, or
one-Run transient upload.

**Acceptance evidence.**

- UI and CLI reject attempts to add/delete/rename/retype parameters or change
  constraints;
- source schema changes appear only after external edit plus deterministic
  rediscovery/validation;
- permitted default and description edits round-trip through CLI and UI;
- default metadata synchronization sends no source, formula, secret, or
  absolute path;
- persistent and transient source modes obey the distinct authorization,
  retention, provenance, and deletion rules in decision 170;
- Profile Git operations remain Agent-owned and are not triggered by catalog
  synchronization.

## 164 — Source fallback versus versioned research defaults

**Question/proposal.** Distinguish the fallback value declared by executable
factor source from a UI-managed, versioned recommended research default. Resolve
each Run parameter as explicit TrialPlan value, then recommended default, then
source fallback. Validate recommended defaults against the immutable discovered
schema, bind them to a factor version, and preserve every historical Run's fully
resolved parameter snapshot.

**User response.** Accepted.

**Final resolution.** FTClient does not rewrite source-declared fallbacks.
Through the same CLI capability it may maintain a recommended-default overlay
for an exact factor version. The overlay is rejected when its name, type, or
value violates the source-discovered schema. TrialPlan construction resolves
and freezes effective values using this precedence:

```text
TrialPlan explicit value
  > versioned recommended research default
  > source-declared fallback
```

Changing a recommendation does not mutate factor source, old TrialPlans,
RunSpecs, Jobs, or evidence. A Run records the resolved values and the hashes of
the schema, recommendation overlay, and factor version. This is an existing
configuration/metadata projection, not a new graph node or database owner.

**Acceptance evidence.**

- invalid names/types/constraints are rejected before persistence or Run;
- changing a recommendation affects only subsequently constructed TrialPlans;
- an explicit TrialPlan value always wins;
- absent explicit/recommended values deterministically use source fallback;
- replay uses the historical resolved parameter snapshot and hashes rather
  than current UI defaults;
- metadata synchronization never edits factor source.

## 165 — Work Package is the Research identity; Branch is its child

**Question/proposal.** Correct the existing projection so a Graph instance is
one Work Package and one UI Research, while Graph branches are Hypothesis Branch
children. Use a stable Work Package ref, attach aggregate reports and Profile
ownership to it, and retain branch-scoped Trials/evidence/reports beneath it,
without introducing another persistence object.

**User response.** Accepted.

**Final resolution.** `graph_instances` is the existing canonical Work Package
owner and projects one Research entry. `graph_branches` remains its collection
of Hypothesis Branches. APIs, CLI, local report paths, and FTClient use
`work-package:<instance-id>` when referring to the whole research; a branch ref
never substitutes for that identity. The Work Package owns immutable creator
Profile, mutable checkpoint-controlled current owner, aggregate report ref, and
branch collection. TrialPlan, obligation, transition, evidence, and branch
report attribution remains branch-specific and records the actual acting
Profile.

This is a schema/API semantic correction over existing owners, not a new table,
event stream, or routine write. Compatibility may read an old
`graph-branch:<instance>:<branch>` reference only to deterministically recover
its parent Work Package; new records and Agent contexts emit the corrected refs.

**Acceptance evidence.**

- a Work Package with multiple branches appears once in the Research list;
- its detail deterministically lists all and only child Hypothesis Branches;
- aggregate and branch reports resolve to their respective owners;
- Profile creation/current ownership is Work-Package scoped while every action
  retains Branch and acting-Profile attribution;
- old branch-shaped research refs migrate/project without duplicating research;
- query/write-count tests show no new persistence owner or per-view write.

## 166 — Profile lifecycle fails closed on authoritative references

**Question/proposal.** Before deletion or archive, have a server-backed
`profile delete-plan` return bounded reference counts, disposition, and a plan
hash. Revalidate that hash on mutation; if the server is unavailable or the
plan is stale, perform no lifecycle mutation. After confirmed archive, release
only a verified clean local worktree through a separate deterministic action.

**User response.** Accepted.

**Final resolution.** FTClient never decides Profile deletion from local
directory state. The FactorTester CLI requests the authoritative server plan,
which checks Work Package, Job/Run, Evidence, usage, handoff, invocation, and
other retained references using their existing indexes/owners. Zero references
may permit hard delete; any retained history forces archive. Mutation consumes
and revalidates the bounded plan hash so a newly created reference makes the
operation fail without partial effects.

Server outage, authorization failure, or expired/stale plan disables only the
lifecycle action; it does not pause unrelated Agent research. Archive and local
worktree release are separate. Release requires confirmed archived state plus
a clean, reconstructable worktree/branch check; dirty or unverifiable content
is preserved. UI merely renders and invokes the same CLI plan and does not scan
the database, cache an authority decision indefinitely, or add a reference
summary table.

**Acceptance evidence.**

- an unreferenced Profile can hard-delete with a current matching plan hash;
- every tested retained-reference kind changes disposition to archive-only;
- a reference inserted between plan and apply invalidates the mutation;
- offline/unauthorized/stale cases make no server or filesystem mutation;
- unrelated research remains usable when lifecycle planning is unavailable;
- dirty worktree release fails without data loss, while a clean archived one
  releases and can be reconstructed from retained branch history;
- the hot research/read path incurs no extra lifecycle query or write.

## 167 — Git ancestry and semantic factor lineage have distinct authority

**Question/proposal.** Use Git as authority for source commits, forks, and merge
ancestry, while the factor-version manifest and exact-hash promotion records
decide which commits are semantic factor versions. Render Profile heads as
Draft Revisions until promotion, derive the local graph on demand, and sync only
source-free version/provenance metadata to the server.

**User response.** Accepted. The user additionally asked whether FTClient may
have its own locally managed database; that boundary is handled in decision
168.

**Final resolution.** Raw Git topology is not itself the factor-version graph.
Git authoritatively proves commit identity and ancestry. Existing version
metadata and approved promotion records identify semantic versions, their
parent/derived/merge relationships, classification disposition, and exact
source hash. Report, formatting, or unrelated commits create no factor version.
A Profile branch head relative to its promoted base is a Draft Revision and
remains distinct even when sibling Profiles touch the same family.

The local CLI joins bounded version metadata with on-demand Git ancestry for the
lineage UI; it does not persist every commit as database rows. Server sync sends
only factor/version identity, parentage, classification, applicability, and
evidence/provenance refs, never source. Local/server disagreement is surfaced as
a provenance conflict and cannot silently overwrite either side.

**Acceptance evidence.**

- a report-only or formatting commit does not add a semantic factor version;
- Profile sibling branches appear as separate Drafts from their exact base;
- promotion binds the reviewed commit hash and creates exactly one formal
  semantic version relationship;
- merge and derived-family ancestry remain navigable without conflation;
- server projection contains no source while retaining verifiable identity;
- mismatched local/server hashes render a conflict and block automatic merge.

## 168 — One minimal FTClient database with explicit authority boundaries

**Question/proposal.** Let FTClient own one local SQLite database under macOS
Application Support. Use it as authority only for device-local bindings and
preferences, and as a bounded incremental cache for server projections. Keep
source, Git history, reports/assets, Graph facts, and secrets in their existing
owners; avoid polling/heartbeat writes.

**User response.** Accepted by continuing the grill.

**Final resolution.** FTClient stores
`~/Library/Application Support/FTClient/ftclient.sqlite`, partitioned by server
identity and authenticated principal. Device-local workspace/worktree bindings,
local-source registrations and grants, UI preferences, opened destinations,
update channel, sync cursor/outbox state, and local usage projection may be
locally authoritative. Server Profile/authz, Work Package/Branch/Trial/
obligation/Job, server catalog, evidence, and approval state are cached
projections only and always retain server revision/hash provenance.

Factor source and complete Git history remain in Git workspaces; report text,
PDF, charts, and large artifacts remain files/object artifacts; the complete
Active Graph remains server-owned; secrets remain in Keychain. SQLite contains
only bounded refs, summaries, hashes, and material synchronization state. Page
render, heartbeat, unchanged polling, and cache hits perform no write. CLI owns
the business operations and schema contract so FTClient is not a second backend.

**Acceptance evidence.**

- database partitions cannot leak one server/principal's projection into
  another;
- logout preserves allowed device state but removes live credentials; Keychain
  remains the only secret owner;
- deleting the projection cache does not lose source, research truth, reports,
  Jobs, approvals, or server state;
- unchanged refresh/poll/heartbeat produces zero SQLite writes;
- incremental sync reads/writes only rows after the stored cursor and detects
  server-revision conflicts;
- database-size and query-count tests cover large research/factor lists without
  importing complete Git histories or artifacts.

## 169 — Recoverable two-phase Profile initialization

**Question/proposal.** Implement Profile initialization as an idempotent,
recoverable two-phase operation across server state, Git/filesystem, and local
SQLite. Keep a reserved Profile unclaimable while the client prepares and
verifies a temporary worktree; activate it only after the final binding and
verification summary, and resume safely with the same idempotency key after a
crash.

**User response.** Accepted.

**Final resolution.** A deterministic plan binds principal, Profile identity,
canonical repository, Profile branch and path, authorized server catalog
projection, schema/stub revision, and relevant hashes to one idempotency key.
The server reserves an `initializing` Profile that cannot be claimed. The client
creates the worktree and generated workspace support in a temporary location,
verifies Git ownership, configuration, imports, Pylance/Pyright, and permissions,
then atomically promotes the directory and commits its local binding. Only a
matching final verification summary may move the reserved Profile to `active`.

The local database keeps one bounded, expiring initialization journal; the
server reuses Profile lifecycle state and stores no general operation table.
Retry with the same key resumes or returns the same result without duplicating
Profile, branch, or worktree. A pre-activation unrecoverable operation cleans
only its verified temporary resources and releases the reservation. General
cleanup cannot remove an already active Profile, which follows decision 166.

**Acceptance evidence.**

- failure injection at every boundary leaves no claimable partial Profile;
- same-key retry after each injected crash converges to exactly one Profile,
  branch, worktree, and local binding;
- a changed plan input invalidates reuse rather than silently rebinding;
- Profile claim fails throughout `initializing` and succeeds only after the
  exact verified activation;
- generated canonical/Profile workspaces pass the real Pylance/Pyright
  zero-error acceptance check;
- expired failed reservations and verified temp directories clean safely, while
  active or unrelated paths are never removed;
- initialization adds no server operation table or hot-path polling write.

## 170 — Three explicit user-source synchronization modes

**Question/proposal.** Distinguish metadata-only synchronization, authorized
persistent private source synchronization, and one-Run transient source upload.
Expose all three through the same CLI-backed UI policy, make metadata-only the
default, and truthfully report source availability and synchronized version.

**User response.** The user rejected restricting authorized source sync to
transient upload: when a user agrees to synchronize source, the source must
actually synchronize. The revised three-mode proposal was accepted.

**Final resolution.** Source policy is user/principal scoped and has three
explicit modes:

1. `metadata_only` synchronizes source-free identity/version, discovered schema,
  descriptions, classification, applicability, provenance,
   and evidence;
2. `persistent_private_source` synchronizes authorized source into that user's
   access-controlled server factor library, retains and versions it, and makes
   the exact synchronized version available to the backend;
3. `transient_run_source` uploads source only into the isolated execution scope
   of an authorized Run and destroys the payload after terminal cleanup while
   retaining the Job, source hash, resolved inputs, and execution evidence.

Enabling a mode in UI through CLI is continuing authorization and does not
require repetitive per-Run confirmation. Disabling persistent sync stops future
sync but does not silently erase retained versions or evidence; deletion is a
separate explicit CLI action with impact/retention checks. Profile worktree Git
operations remain Agent-owned. Server-built-in implementations retain distinct
provenance from every user-source mode.

**Acceptance evidence.**

- default sync transfers no source and presents the factor as metadata-only;
- persistent opt-in transfers the exact authorized version, retains private
  version history, and backend execution resolves the matching hash;
- transient mode destroys source payload after success and injected failures
  while retaining the Job and verifiable source hash;
- UI and CLI report mode, availability, last synchronized version/hash, and
  failure/conflict state consistently;
- disabling sync performs no deletion; explicit deletion reports impacted
  versions/Jobs before mutation;
- cross-user access and source/hash substitution tests fail closed.

## 171 — Machine-checkable UI-to-CLI capability parity

**Question/proposal.** Assign every FTClient business query/mutation a stable
action ID backed by the FactorTester CLI capability registry. Expose a generated
`capabilities ui --json` manifest containing command and schema contracts, let
FTClient use the same HTTP/SSE backend without mandatory subprocess overhead,
and make CI prove equivalent results/errors for every non-presentation action.

**User response.** Accepted.

**Final resolution.** Login/session, account, Profile, workspace, data-source,
factor-library, source synchronization, research, report, usage/budget, update,
and other business actions declare stable action IDs. The CLI registry is the
single schema/authority/effect owner and generates the compact manifest; Swift
does not maintain a duplicate business schema or hidden implementation. The
native client may call the shared service transport directly for performance,
but it identifies the same action and consumes the same versioned input/output
and error contract.

Purely local presentation behavior—window geometry, open tabs, sidebar state,
language, theme—does not require a CLI command. Missing/incompatible capability
is rendered truthfully and cannot fall back to a Swift-only business mutation.
Stable action IDs are provider/model/Skill neutral. The manifest is generated
on request/cached by version hash and is not a database owner or injected whole
into routine Agent context.

**Acceptance evidence.**

- an automated inventory finds zero FTClient business actions without a CLI
  capability and zero undocumented Swift-only mutation paths;
- shared conformance vectors produce semantically equal success and error
  envelopes through installed CLI and native transport;
- the installed CLI works from an arbitrary cwd and emits stable JSON/exit
  codes without importing FTClient;
- presentation-only exemptions are an explicit bounded allowlist;
- missing, old, unauthorized, and offline capabilities render the declared
  state and perform no fallback mutation;
- ordinary UI startup fetches only the compact versioned manifest or a cache
  hit, not full contracts or Skill documents.

## 172 — One-time migration; no legacy layout compatibility layer

**Question/proposal.** The initial proposal distinguished new commands from
legacy commands and retained compatibility aliases for old default paths.

**User response.** Rejected as unnecessary complexity. The user asked what
“new/old commands” and “recreating deprecated layout” meant, and directed that
the old directory structure be migrated once and then deleted completely.

**Final resolution.** “Old commands” referred only to current development CLI
entry points whose defaults could still create the pre-unification
`personal-workspace` or Profile-local copies. They are not a released public
contract and receive no compatibility layer. Implementation changes every
supported path owner and command to the unified per-principal layout, performs
one deterministic migration, verifies the migrated canonical repository,
Profile worktrees, branches, research projections, support files, and hashes,
then removes all old roots and migration quarantine. Old paths are not exposed
to Agents, UI, CLI, configuration, or future code.

Migration fails before deletion if any source, Git ref, research artifact,
binding, or reconstruction check is unresolved. A success marker records only
migration version and verification hashes in local client state; it is not a
permanent legacy-path registry. Startup does not repeatedly scan deleted roots.
Tests and source search must prove no supported default can recreate them.

**Acceptance evidence.**

- a fixture of every known old-root shape migrates exactly once into the unified
  principal layout with matching content/Git/research identities;
- failure injection before final verification leaves the original intact and
  creates no partially active destination;
- successful verification removes old roots and quarantine completely;
- second startup performs no migration scan/write and changes nothing;
- repository search and integration tests find no production default, UI path,
  claim context, or CLI command capable of creating/referencing an old root;
- MaxA/MaxB still claim their unified worktrees and pass Pylance/Pyright after
  old-directory removal.

## 173 — Canonical UI sync versus Agent-owned Profile Draft sync

**Question/proposal.** Make the user-level FTClient sync action operate on the
canonical personal workspace. Do not let UI silently synchronize Profile
worktrees. Permit a claimed Profile Agent to synchronize its own exact Draft
commit through CLI under the selected source policy, retaining Draft/Profile
provenance and never treating synchronization as promotion.

**User response.** Accepted.

**Final resolution.** FTClient's normal factor-source synchronization selects
formal versions from the authenticated user's canonical personal factor
library. It may display all Profile Draft synchronization states but does not
perform Git or source synchronization from a Profile worktree on the user's
behalf. A claimed Agent may invoke the same provider-neutral CLI capability for
its authorized Profile and exact commit. The server records that payload as a
private Profile Draft with Profile, branch, base version, commit/source hash,
and source-policy provenance.

A synchronized Draft may support an authorized remote Trial/Run, but it remains
a Draft and cannot update canonical lineage, allocate a formal version, or
overwrite a sibling Profile. Decision 161 promotion remains the only route to a
formal canonical version. After promotion, ordinary user-level UI sync can
synchronize that formal version under decision 170.

**Acceptance evidence.**

- user-level UI sync never reads a Profile worktree or changes its Git state;
- an unclaimed or wrong Profile cannot synchronize another Profile's Draft;
- Agent Draft sync binds exact branch/base/commit/source hashes and renders as
  Draft in local/server lineage;
- remote Run resolves the exact authorized Draft without promoting it;
- sibling Drafts cannot overwrite or collapse one another;
- promotion then canonical sync produces one formal version with retained Draft
  provenance.

## 174 — No metadata concurrency subsystem for the single local workspace

**Question/proposal.** The initial proposal introduced field-level optimistic
concurrency for simultaneous UI/Agent edits to defaults, descriptions,
classification, and tags.

**User response.** Rejected as based on the wrong ownership model. A user has
one local canonical workspace. Even when more than one UI process exists,
recommended parameter values live in the UI-managed local database and are
changed only through UI/CLI. Agents change their separate Profile worktrees, so
their source edits do not concurrently mutate the canonical metadata owner.

**Final resolution.** Do not add a field-conflict protocol, CRDT, metadata event
table, or Agent merge path for this case. UI and local CLI use the same FTClient
database owner and ordinary SQLite transactions/locking. Profile Agents own
separate Git worktrees and their changes remain separate Drafts until the
existing promotion path. Git/promotion handles source convergence; the local
database serializes its own settings. A coarse server revision check may still
reject a stale synchronization request, but it does not justify a new local
concurrency model.

Whether recommended defaults are purely device-local or included in server
metadata synchronization is clarified separately in decision 175.

**Acceptance evidence.**

- no field-conflict/CRDT/event-table implementation is introduced;
- concurrent FTClient processes use SQLite locking and cannot corrupt the one
  local metadata database;
- UI and installed local CLI observe the same committed recommended value;
- MaxA/MaxB edits remain isolated in their own Git Drafts;
- canonical mutation still requires the established promotion path rather than
  a metadata concurrency subsystem.

## 175 — Recommended parameter values are device-local research preferences

**Question/proposal.** Treat recommended parameter values as local FTClient
research preferences rather than synchronized server factor-version metadata.
Have all UI processes and the installed local CLI share the same client
database, let TrialPlan construction read and freeze these values, and keep
description/classification/tags as the synchronizable metadata layer.

**User response.** Accepted.

**Final resolution.** A recommended parameter value lives in the current
client installation's SQLite partition for the server/principal/factor version.
Multiple FTClient processes and the local CLI read/write that same owner under
ordinary SQLite transactions. It is neither source fallback nor synchronized
factor metadata, and different devices may intentionally recommend different
values. Parameter names/types/constraints remain source-discovered and
read-only; descriptions, declared classification, and user tags remain eligible
for metadata synchronization.

When a Planning Agent constructs a TrialPlan on that client, precedence remains
explicit TrialPlan value, local recommendation, then source fallback. The
resolved value and relevant schema/factor hashes are frozen in TrialPlan/RunSpec
so remote execution and replay do not depend on the originating UI database.
Decision 163's sync payload and decision 170's `metadata_only` mode therefore
exclude recommended parameter values.

**Acceptance evidence.**

- UI and local CLI processes observe one serialized local recommendation;
- metadata synchronization payloads contain no recommended values;
- a second client may hold a different recommendation without conflict;
- the produced TrialPlan freezes the chosen effective value and remote Run
  needs no access to client SQLite;
- source fallback and historical Runs remain unchanged after a recommendation
  edit;
- source-discovered schema structure stays read-only.

## 176 — First-principles autonomy and an Occam gate for remaining work

**User direction.** The Agent must decide from first principles which functions
materially help factor research. Everything else is governed by Occam's razor;
the user should not be asked to adjudicate every implementation detail.

**Final resolution.** The detailed UI/folder grill ends here. Further design
questions are resolved by the responsible Agent unless they change user
authority, authorize source/data disclosure, cause irreversible loss, or impose
a genuinely ambiguous product-policy choice. A proposed function survives only
when it materially improves at least one of:

- research-semantic or statistical correctness;
- reproducibility and exact-input replay;
- evidence/obligation/decision auditability;
- reliable access to an actually needed backend/data/Skill capability;
- continuity of useful Agent work across restart, handoff, or failure;
- truthful and efficient human understanding of research progress/results.

Otherwise it is removed, deferred, or implemented as a projection over an
existing owner. New tables, graph nodes, agents, approvals, background writes,
and token-bearing context require evidence that an existing deterministic
object cannot provide the capability. UI polish supports comprehension and
trust but does not justify duplicating research truth or backend logic.

Implementation proceeds in independently testable/committable batches. The
Agent records assumptions and evidence, revisits the user only at the authority
boundary above, and does not continue grilling routine engineering choices.
