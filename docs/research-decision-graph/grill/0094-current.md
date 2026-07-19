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
