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
`open_discovery` for a user-confirmed market/data/theme/exclusion/budget scope
in which an Agent may create candidates without per-factor confirmation.

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

**Resolution.** All intents share evidence, budget, preregistration, and
validation semantics; role changes create later hypothesis versions.

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

**Pending question.** The exact narrow boundary is proposed below in the live
conversation and remains unresolved until the user accepts or revises it.
