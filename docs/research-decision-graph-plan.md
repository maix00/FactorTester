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

Token control is pre-execution, not merely telemetry, and belongs to Agent
Flow rather than the Factor Research Graph:

```text
load current Agent Budget Period, if capped
  -> create one reserved Agent Invocation and update the period atomically
  -> invoke the model only when the deterministic reservation fits
  -> normalize provider usage when available
  -> settle the same invocation and period atomically
  -> conservatively charge the reservation when actual usage is unavailable
```

Client-reported transition telemetry is diagnostic only. Authoritative budget
usage is the provider-neutral settlement recorded by the Agent Flow owner,
including its measurement quality and charging-policy version. No
provider-specific receipt, HMAC, trusted launcher, or configured cap is a
prerequisite for an Agent to start: profiles are unlimited until UI sets a
cap, and unavailable actual usage settles as `reserved_fallback`.
Skill-document, artifact-summary, and cache-read counts are attribution
subsets rather than separate budgets; reviewer calls are ordinary sponsored
Agent Invocations.

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
24. Concrete statistical design belongs to an immutable, versioned TrialPlan,
    not to Work Package or hard-coded graph-edge thresholds. The graph requires
    a valid `trial_plan_ref` and evaluates evidence governed by that plan.

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

## TrialPlan Boundary

The `validation_design` node produces a versioned TrialPlan containing at
least:

```text
hypothesis and trial family
primary and secondary outcomes
obligation-driven ordered sample stages and their immutable scope identities
planned comparisons
outcome-aware stopping rules
multiplicity method and dependence assumptions
rejection, revision, and continuation criteria
```

The Factor Research Graph declares that a valid `trial_plan_ref` and its
required evidence must exist. It does not embed one universal IC, Sharpe,
sample-size, or stopping threshold in graph topology. Product and research
profiles may validate different TrialPlan contracts without creating different
research graphs.

Deterministic code checks the TrialPlan schema, identity, version, hash,
required fields, and whether result evidence was produced under the bound
version. Agent judgment supplies and reviews economic/statistical meaning only
where the applicable protocol does not decide it. Once selection-relevant
outcomes have been inspected, a child version may not replace frozen sample
partitions, RunSpecs, comparisons, outcomes, criteria, or
stopping/multiplicity rules. A factor or trial-design change creates a new
hypothesis and TrialPlan lineage with the trial-ledger consequences required
by decisions 114–115. The server releases the old current-plan binding only
when the branch crosses the declared new-hypothesis edge. It does not rewrite
the old plan, ResearchRuns, sample exposure, or evidence; the replacement plan
starts at version 1 under a new plan identity.

The server persists the compact immutable TrialPlan as the authoritative
run/result binding. It contains the executable statistical contract and opaque
evidence references, but no factor source, reconstructable formula, full Agent
reasoning, or private local paths. The local research record retains full
rationale and permitted private references.

A TrialPlan version is written once. Run submission freezes its hash, and
result evidence must return the same hash. Execution progress does not rewrite
the plan; attempts and results append their own bounded references. This lets
the server reject an unbound or mismatched run without adding TrialPlan writes
to the database hot path.

The minimum accepted persistence shape does not introduce a `trial_plans`
table or service. The `validation_design` transition stores the compact plan
once in existing append-only graph-trace evidence. The current hypothesis
branch keeps a current-plan hash and compact stage projection needed for
constant-bounded validation. The stage projection contains only plan/version,
current stage, completed mask, plan-bound execution node, and frozen commitment
hashes; it is not another research state owner. A ResearchRun binds the plan
hash, server-derived sample stage, comparison-arm `trial_role`, and
`comparison_id`; JobAttempts inherit through the run rather than duplicating
the plan. Routine submission reuses one branch read to reject a non-current
stage, wrong execution node, or protected-sample reuse and does not scan
historical traces.

A graph trace containing a TrialPlan body is retention-pinned while any
ResearchRun, JobAttempt, or accepted research conclusion references its plan
hash. Closing a branch or activating a new graph version does not delete it.
Explicit deletion of the complete dependent research history may release the
pin. This preserves one canonical plan body without creating a second
TrialPlan store.

This is a semantic ownership decision, not a requirement to preserve the
current physical schema. Before implementation, apply deletion, read-path,
write-path, and owner-locality audits to the existing Workspace, ResearchRun,
JobAttempt, graph branch, and graph trace structures. Refactor or consolidate
an existing persistence object when that produces a deeper owner and fewer
reads/writes; do not mechanically add fields merely because the current table
exists. Any alternative physical layout must preserve the same immutable
bindings and demonstrate no greater routine query/write count.

The existing graph persistence must also be refactored to respect the
three-layer boundary. A graph instance is the persisted Work Package
projection: user authorization scope, workspace, and pinned graph version,
plus an opaque Agent Flow scope reference. It does not own a token budget. A
graph branch is the Hypothesis Branch: current research node, hypothesis and
factor identities, current TrialPlan hash, statistical trial counters, and
factor-evidence status. It does not own token, compute, concurrency, fee, or
reviewer-usage aggregates.

ResearchRun remains the immutable RunSpec execution binding for one branch;
JobAttempt owns one execution attempt; graph trace owns one transition's
bounded evidence. Agent Flow owns resource budgets, usage aggregation, and
wait/resume. Existing graph-instance and graph-branch tables should be
deepened or migrated to those meanings instead of adding parallel WorkPackage,
Hypothesis, or CoordinationCheckpoint tables.

Token limits are configured per Agent Profile through UI and enforced by Agent
Flow under the claimed `research_agent_id`, not per graph instance. Planning,
Research, and Server Maintenance profiles have independent limits. Calls made
by conditional reviewers are charged to the sponsoring Research Agent unless
they execute under another explicitly budgeted profile.

For a hard restart-safe limit, Agent Flow persists only the compact budget
state needed for atomic enforcement: agent identity, limit, used amount,
temporary reservation, and revision. Active state may be cached in memory.
Before a real model invocation Agent Flow atomically reserves the maximum
charge; after termination it settles actual usage. Cache hits, unchanged
heartbeats, backend Job execution, and graph transitions create no budget
writes. Budget state should be isolated from the FactorTester backtest/result
database so these low-frequency writes cannot contend with computation.

Agent Flow appends one compact usage item in the same settlement transaction
so UI can group usage by Agent Profile and task. The item contains only task,
Work Package/branch references where applicable, invocation purpose,
runtime/model identity, input/output/cache/charged counts, status, timestamp,
measurement quality, and budget-period identity. It contains no prompt,
complete context, factor source, or response body.

UI displays limit, used, temporary reservation, remaining amount, current
period, pause state, and grouped task/invocation usage. Changing the current
limit does not erase usage. Reset starts a new immutable budget period and
retains historical usage; if an invocation is active, reset becomes effective
after that invocation settles. Version 1 supports manual reset only, avoiding
another scheduler and recurring database activity.

Budget exhaustion is a derived Agent Flow pause, not research evidence or a
new persisted pause object. Agent Flow refuses a call before model execution
when remaining allowance cannot cover its safe reservation, preserves the
local checkpoint, and returns a provider-neutral
`agent_budget_exhausted` result. The graph node and hypothesis status remain
unchanged, and submitted backend Jobs continue.

Increasing the limit or opening a new budget period changes the budget
revision. One deduplicated revision event wakes the affected Agent once; no
polling Agent or LLM heartbeat waits for it. Unaffected Agents, branches, and
Jobs continue. Provider usage beyond a reservation blocks subsequent calls and
records a metering anomaly, but does not alter research evidence.

UI token reads are lazy and bounded. Opening settings reads only Agent Profile
and current budget aggregate. Task usage is fetched only when expanded, by
Agent, budget period, and settled-time cursor. The UI groups invocation rows at
read time; v1 creates no materialized daily/task summary, scheduled compactor,
or retention worker. A budget revision event identifies one Agent and refreshes
only that aggregate rather than polling or rescanning usage history.

Token accounting is runtime- and provider-neutral. A deterministic usage
adapter normalizes provider facts into input, output, cache-read, charged-token,
measurement-quality, and charging-policy fields. The Agent ID remains the
budget identity when model or runtime changes. Each immutable budget period
pins one charging-policy version; historical rows retain their original
model/runtime, measurement quality, and policy and are never recomputed.

The default policy charges provider-normalized total input plus output while
showing cache-read separately and never double charging a cache subset already
included in input. Before invocation, deterministic tokenization/estimation
plus maximum output determines the safe reservation. When actual provider
usage is unavailable, settlement conservatively charges the reservation and
marks `reserved_fallback`. This preserves a hard upper bound without blocking
a newly claimed Agent merely because its runtime exposes a different receipt
shape. The adapter is code, not an Agent or context-loaded Skill.

Agent Flow persistence uses two deep lifecycle objects rather than separate
execution, reservation, provider-receipt, and budget tables:

- `AgentBudgetPeriod` owns one Agent's immutable period identity, limit,
  used/reserved amounts, charging policy, revision, and open/close times;
- `AgentInvocation` owns execution provenance, principal/lineage/input hashes,
  task/purpose, runtime/model, reservation, normalized settlement,
  measurement quality, provider request/attestation hash, status, and
  timestamps.

The pre-call transaction inserts one reserved invocation and updates its
period. Settlement updates that same invocation and period. An unfinished
invocation is the recoverable reservation; no separate reservation row is
needed. UI paginates settled invocations. These objects live in an independent
Agent Flow Module/store, not `research_graphs.py`. Existing overlapping tables
are migrated and removed without a long-lived dual-write compatibility path.

Each AgentInvocation may carry one bounded context-cost breakdown produced by
the deterministic context assembler: base instructions, conversation, local
graph packet, evidence summaries, Skill documents, review material, and
output. It stores counts and measurement quality only—never prompt/content,
file names, artifact bodies, or per-Skill/evidence rows. UI hides the breakdown
until an invocation is expanded and may aggregate the fixed categories by
task. The breakdown is settled in the existing invocation transaction and is
not copied into graph state.

Agent Flow usage follows its execution owner. Local Research Agents persist
periods and invocations in the local Agent Flow store exposed by the local
manager API; Server Agents persist them in the server Agent Flow store. UI
routes settings to the owner and merges read views, but has no browser/UI
accounting database and never enforces a balance. Version 1 uses only
in-memory page caching, does not default-sync local invocation history to the
server, and defers cross-device summary synchronization until explicitly
required.

Agent Profiles are owner-pinned in v1. An Agent ID may change model/runtime
seamlessly within the same Agent Flow owner. Moving it to another client/owner
requires an explicit atomic transfer of profile, current budget period,
checkpoint, and necessary hashes; the old owner loses claim authority before
the new owner can invoke a model. Version 1 does not add a global per-call
budget broker merely to provide zero-coordination cross-device roaming.

Context-cost telemetry is optimized inside Agent Flow, not by adding Factor
Research Graph edges or a standing Token Optimizer Agent. Deterministic rules
may detect repeated Skill loads, oversized local packets/evidence summaries,
or disproportionate reviewer cost. A single anomaly is a UI diagnostic.
Repeated or hard-threshold breaches produce one deduplicated Agent Flow
optimization proposal.

Only semantics-preserving configuration/cache actions may run
deterministically. Changes to context assembly, Skill conditions, reviewer
policy, or Agent Flow semantics become a Maintenance Case; high-risk changes
use document-grounded grill. Every optimization compares completion rate,
effective evidence, token, and database I/O before/after rather than minimizing
tokens alone.

Agent startup/resume is a deterministic, provider-neutral local-context
operation. It returns a role-specific small packet rather than infrastructure
documentation. Research receives Agent/profile and remaining-budget summary,
current Work Package scope, one current branch/node with candidate edges,
TrialPlan reference, changed Job references, node-local capability
descriptions, local Skill-reuse hints, and one next action. Planning receives
only pending scope decisions and bounded workspace-factor summary. Server
Maintenance receives only unresolved cases and diffs.

The packet omits complete graph, factor/Skill catalogs, historical trace,
usage history, Job output, and future-node gaps. It is assembled without an
LLM. Identical checkpoint/revision returns identical content with zero write.
Profiles are unlimited until the user configures a cap, so missing budget
configuration cannot block work. An exhausted profile can inspect deterministic
status/checkpoint but cannot start another model invocation. No role must open
UI, configure paths manually, or read architecture documents before its first
authorized action.

Server graph/capability state remains Skill-neutral: it provides only a
capability description and hash. The local manager may enrich the current
task's packet with an opaque local reuse reference, content hash, approval
scope/hash, and context-cache availability derived from local audit state.
Matching description/content/approval/runtime state lets the Agent reuse the
local implementation without rediscovery, download, or duplicate approval.

A fresh runtime context still follows that runtime's Skill-loading rules; reuse
must not pretend the model remembers absent instructions. When no matching
local implementation exists, the Agent may search locally or online. Download
or inspection is not execution. First execution and changed content/authority
require approval in the corresponding Agent conversation. UI displays
completed approvals but cannot grant them. Actual Skill name/source/version,
hash, approval, execution, and result refs remain in the local research audit
and are never graph/catalog/hash inputs.

Backend assurance is a deterministic validation Module, not a separate
persistence owner. During the existing JobAttempt terminal transaction it
checks RunSpec/ExecutionPlan/backend identities, terminal facts, compact result
and artifact-manifest hashes, and configured numerical/structural invariants.
Its bounded policy hash, backend revision, checks bitmap, anomaly codes, hashes,
and disposition are stored inside the JobAttempt terminal summary.

The validator never reruns the backtest. A conforming summary is trusted by
default and travels in the existing Job decision packet; no reviewer wake or
assurance-table lookup occurs. Only a concrete anomaly/hash conflict,
implausible calculation, or explicit evidence-backed Agent suspicion opens a
Maintenance Case. Backend policy changes do not rewrite historical Jobs, which
retain their original policy hash. Independent assurance receipt persistence is
migrated away rather than dual-written.

An anomalous JobAttempt remains immutable and queryable. Its assurance and any
open Maintenance disposition make its evidence ineligible through a derived
guard; no branch-pause row is written. Only transitions that require that
evidence wait. Unaffected branches and Jobs continue. One case is deduplicated
by Job/policy/anomaly hash.

Maintenance first gathers deterministic bounded evidence. It invokes at most
one Backend Reviewer only when computation semantics remain unresolved, and
only a Server Agent or source-authorized local Agent may inspect/change backend
code. A false-positive disposition references but does not rewrite the old
Job. A confirmed defect is fixed and validated on the backend owner branch,
released under a new backend revision, and rerun as a new JobAttempt. Old and
new attempts coexist; no historical result is promoted to the new revision.

Maintenance coordination uses one durable object across backend anomaly,
capability gap, graph/platform change, and context optimization. A
MaintenanceCase owns only kind, dedup descriptor hash, current status, bounded
affected/change references, conversation ref, claimed Agent, latest result ref,
and timestamps. It does not copy source, diffs, logs, approval text, Job facts,
graph proposals, commits, or tests from their owners.

There is no separate case-events table or per-kind queue. Case status changes
only on material open/claim/block/resolve/reject transitions; heartbeat,
duplicate observation, and unchanged resume write nothing. UI may inspect and
filter cases but cannot approve or disposition them. Approval remains in the
corresponding Agent conversation. Resolution emits one deduplicated wake to
affected work.

Graph governance uses proportional trust controls. Ordinary research runtime
relies on canonical checkpoint/history, deterministic hashes, and resource-level
authentication/authorization; it does not require per-transition HMAC,
provider-specific receipts, or a trusted launcher adapter. High-risk effects
bind one authenticated conversation approval event to the exact
action/diff/content hash and consume that event once.

Independent cryptographic provenance is required only where actors, builders,
code, or release artifacts cross a configured software-supply-chain trust
boundary. Same-process/same-database launcher, capability, provider, backend,
and human HMAC layers do not protect against compromise of that same owner and
must not remain as startup or transition dependencies. This preserves
fail-closed authorization while allowing runtime/model replacement and
reducing database/secret machinery.

## Minimal Persistence Target

The current twenty-table Graph Module is a migration source, not the target.
After the accepted deletion audit, the Graph Module has exactly six semantic
owners:

1. immutable graph versions;
2. one active-version pointer per graph;
3. graph instances as Work Package projections;
4. graph branches as Hypothesis Branch owners;
5. append-only graph transition trace;
6. one cross-kind Maintenance Case queue.

Agent Flow has exactly two accounting/execution owners in an independent
store: Agent Budget Period and Agent Invocation. JobAttempt owns terminal
backend assurance. Graph branch owns only its current node capability
resolution. Maintenance Case owns bounded validation/review/grill/approval
gate facts and refs. Rollback is an approved active-pointer change, not a
separate record type, and activation does not copy graph JSON into a second
active definition.

Migration proceeds in independent commits:

1. move/consolidate Agent Flow;
2. merge backend assurance into JobAttempt;
3. consolidate graph governance and exact-hash approval into Maintenance Case;
4. deepen branch resolution and remove resource aggregates;
5. simplify activation/version/rollback;
6. shadow-compare and remove legacy tables/APIs.

This order preserves the previously accepted dependency: establish hard
resource enforcement and the trust/evidence chain before changing routine
context semantics, then measure and minimize the database hot path only after
the owner schemas are stable.

### Migration deletion map

The current twenty-table schema is mapped once; no table is retained merely
because an API currently exposes it:

| Current persistence object | Final owner or disposition | Migration batch |
|---|---|---:|
| `research_graph_versions` | Graph Version | 5 |
| `active_research_graphs` | Active Graph Pointer | 5 |
| `research_graph_instances` | Work Package projection | 4 |
| `research_graph_branches` | Hypothesis Branch plus current node resolution and TrialPlan hash | 4 |
| `research_graph_trace` | bounded append-only transition evidence | 4 |
| `research_graph_validations` | bounded Maintenance Case gate/ref | 3 |
| `research_graph_proposals` | bounded Maintenance Case gate/ref | 3 |
| `research_graph_reviews` | bounded Maintenance Case gate/ref; calls live in Agent Invocation | 3 |
| `research_graph_audits` | bounded Maintenance Case grill disposition/ref | 3 |
| `human_activation_authorizations` | exact-hash, authenticated, single-use approval fact in Maintenance Case | 3 |
| `research_agent_executions` | Agent Invocation | 1 |
| `research_token_budgets` | Agent Budget Period | 1 |
| `research_token_reservations` | reserved lifecycle state in Agent Invocation and Period | 1 |
| `research_provider_usage_receipts` | normalized settlement fields in Agent Invocation | 1 |
| `research_backend_assurance_receipts` | JobAttempt terminal-assurance summary | 2 |
| `research_graph_node_resolutions` | current projection on Hypothesis Branch | 4 |
| `research_capability_receipts` | current branch resolution or Maintenance Case conformance ref; no generic receipt owner | 3/4 |
| `research_capability_approvals` | local conversation approval and local Skill audit; rejected from server Graph persistence | 3 |
| `research_graph_rollbacks` | approved active-pointer change referenced by Maintenance Case and graph trace | 5 |
| `research_graph_server_secrets` | delete; no same-owner HMAC trust boundary | 3 |

Batch 1 introduces the independent Agent Flow Module behind an Interface that
can read legacy rows during the migration command, writes only the two target
owners, switches all callers in the same commit, and deletes the four legacy
accounting tables after verified conversion. Batch 2 extends the canonical
JobAttempt terminal Interface, converts assurance summaries, switches readers,
and deletes the receipt table in the same commit. Batch 3 creates the sole
Maintenance Case owner, converts still-live governance state and bounded
references, switches high-risk gates, then deletes the old governance,
approval, and secret tables.

Batch 4 changes the branch schema and local context resolver together. It
converts only current projections, preserves immutable history in trace, and
removes the separate resolution table and resource aggregates. Batch 5 makes
the immutable Graph Version plus Active Pointer the sole activation Interface;
it migrates only the current pointer and bounded case/trace history, never an
active graph copy or rollback row. Batch 6 removes compatibility reads and
obsolete APIs, then pins the final eight-owner schema and measured query/write
floor.

Every batch must run forward migration, compatibility fixture replay, target
API tests, restart/resume, rollback-to-parent, and SQL trace measurement before
its commit. A failed batch rolls back to its parent commit and pre-migration
database backup; later batches do not begin. Compatibility is an offline/read
adapter inside the migration command, not a long-lived runtime dual-write
seam.

Every batch pins before/after schema count, SQL read/write/transaction count,
latency, replay/resume equivalence, compatibility behavior, and rollback
target. No batch introduces long-lived dual write.

The Research Agent drafts the TrialPlan from the hypothesis, product profile,
and applicable approved statistical protocol. Deterministic validation checks
schema, identity/hash, sample-role separation, required fields, protocol
predicates, and consistency with referenced RunSpec state. A conforming routine
plan requires no LLM reviewer.

One Statistical Reviewer is invoked only when the design uses a non-standard
method, leaves outcome/stopping/dependence semantics ambiguous, deviates from
an approved protocol, or crosses the configured independent-review risk level.
An unchanged input/protocol/review hash reuses the prior valid review. The user
does not design the statistical plan; user confirmation is required only when
the proposal changes authorized research scope, fees, permissions, or an
irreducible risk preference. Result-related computation cannot start until the
plan is frozen.

TrialPlan and RunSpec are complementary rather than one-to-one:

- RunSpec freezes one concrete execution configuration, including factor
  version/configuration, products, data, time window, strategy, and accounting;
- TrialPlan freezes the statistical interpretation and may coordinate multiple
  RunSpecs, such as main-only/aux-only/enriched comparisons or multiple
  walk-forward and diagnostic/selection/confirmation slices;
- each ResearchRun binds exactly one TrialPlan ID/hash, one RunSpec hash, one
  server-derived sample stage, one comparison-arm `trial_role`, and one
  `comparison_id`;
- every JobAttempt inherits those bindings and cannot change them;
- TrialPlan references RunSpec identity and role without copying the complete
  execution configuration.

A RunSpec not present in the frozen initial plan cannot be attached to the
current lineage after outcomes are known. A child version cannot replace
RunSpecs or comparison membership. Adding or changing either requires a new
hypothesis and TrialPlan lineage with the corresponding trial-ledger effect.

## Evidence Interface

Execution evidence and graph-decision evidence use two bounded read interfaces
over existing persistence owners:

```text
JobEvidenceReceipt projection
  execution status and exit code
  RunSpec / TrialPlan / backend hashes
  stdout / stderr references
  metric / artifact references

EvidenceEnvelope schema in research_graph_trace.evidence_json
  graph node and proposed transition
  existing JobAttempt terminal-assurance references
  Contract / methodology identity for semantics evidence
  TrialPlan / RunSpec identity for trial-derived evidence
  factor / data / product references
  attempt_count / outcome_examined_count
  stopping reason
  conflicts and capability gaps
```

`JobEvidenceReceipt` is not a new table or write path. It is a source-free
projection from the canonical JobAttempt terminal summary and artifact
metadata. `EvidenceEnvelope` is not a second event store. It is the validated
bounded schema of the existing append-only graph trace evidence. Full stdout,
result tables, curves, source, and local process files remain in their owning
artifact/local stores. It contains facts only; disposition, rationale, Claim,
and obligation changes belong to the separate adjudication protocol. Local
`control_command` envelopes audit CLI execution and are not admissible research
evidence.

Deterministic graph guards read only bounded structured fields, identities,
hashes, and references. An Agent follows a reference only when semantic review
requires the underlying evidence. Missing execution status/exit code, RunSpec
or TrialPlan hash, stopping reason, or node-required evidence fails the
transition closed. Routine graph execution must not add receipt/envelope
writes or tables. It reads only the current branch's required canonical rows,
reuses data already present in the local decision packet, and performs no
database read for unchanged heartbeat or progress state.

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

Operator support is execution-surface specific. A capability conformance
result must distinguish:

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
5. publish the capability, Author SDK change, and bounded conformance
   reference after validation;
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
validated graph-trace evidence
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
  capability descriptor and resolution references;
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
the Server Maintenance Agent in graph-curation review mode must test whether
apparently similar cases share the same causal timing, product semantics,
execution layer, and statistical design.

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
  conforming JobAttempt assurance uses zero reviewers, an actual mismatch
  starts at most one independent verifier, and sibling jobs continue;
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
  `wasAssociatedWith`, and `wasRevisionOf` in bounded graph-trace evidence;
- use the constraint-oriented idea from
  [W3C SHACL](https://www.w3.org/TR/shacl/) when validating bounded evidence
  shapes, without introducing RDF or SPARQL into the runtime hot path.

The server continues to store normalized JSON, hashes, bounded evidence and
authorization references, and canonical state. It does not serialize the
whole research history as RDF, load an ontology into every Agent context, or
ask an LLM to infer routine transitions. If cross-project semantic discovery
later becomes necessary, a read-only knowledge projection can be derived from
the authoritative state/evidence records. It must not become a second source
of transition truth.

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
required_research_evidence: []
required_transition_facts: []
counterexamples: []
risk_level: L1 | L2 | L3 | L4
```

The immutable Graph may retain `required_evidence` as the exact concatenation
of the two typed arrays for protocol compatibility. Routine Agent packets omit
that ambiguous field.

Research Cycle discovery, adjudication, and closure at `research_decision` use
one declared self-edge. The ordinary atomic transition writes the existing
trace and checkpoint while keeping `from_node == to_node`; a server-derived
guard rejects an empty event list. This avoids another API, node, table, or
replay path. Accepted creation or reopening of a decision-blocking obligation
invalidates accepted and pending closure within that same replay event;
rejected or non-blocking deltas preserve closure.

The routine packet contains only Claim refs/types and bounded open-obligation
question summaries with criterion and detail refs. When an Agent needs one
full body, the explicit cycle-object read resolves that ID from the latest
checkpoint with one primary-key join. It does not scan trace history or add a
persistence object.

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
- graph instances, hypothesis branches, and bounded append-only transition
  evidence;
- one cross-kind Maintenance Case queue containing bounded proposal,
  validation, review, grill, approval, and activation facts or references;
- capability descriptions and descriptor hashes, never concrete Skill
  identity;
- shadow replay references and approved active-pointer changes.

The existing `user -> ResearchWorkspace -> ResearchRun -> JobAttempt` ownership
remains unchanged. Graph state must reference these identities rather than
becoming another job owner.

## Agent Roles

Persist only principals whose ownership must survive a restart:

- **Planning Agent** owns workspace-wide research planning and asks the user
  to confirm or revise Work Package scope.
- **Research Agent** owns one claimed Work Package and its authorized factor
  research.
- **Server Maintenance Agent** owns claimed Maintenance Cases and is the only
  ordinary server-side principal allowed to coordinate graph, capability,
  statistical-policy, or backend changes.

Process mining, semantic/statistical/counterexample review, graph curation,
capability investigation, implementation, and audit presentation are bounded
tasks or output modes. They do not create standing Agent identities, queues,
profiles, or continuously running reviewers. A specialist reviewer is an
ephemeral Agent Invocation sponsored by the relevant Research or Server
Maintenance Agent.

L1 uses deterministic execution and zero reviewers. L2 defaults to zero and
may invoke one reviewer only for evidence conflict or semantic uncertainty.
L3 invokes at most one relevant specialist. L4 uses one proposer plus one
independent reviewer; a third is allowed only to resolve an actual
disagreement. Existing valid review hashes are reused when inputs and policy
are unchanged.

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
  summary, and reviewer token attribution by reference to the sponsoring
  Agent Invocation; graph state does not duplicate usage rows.

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

- persist one bounded Maintenance Case with proposal, independent-review,
  validation, audit, and exact-hash approval facts or references;
- persist actual proposer/reviewer model calls only as Agent Invocations;
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
| Routine packet size is bounded | graph-version calibration records all local anchors, observed maximum and at least 10%/512-byte semantic headroom |
| Context and next have distinct leverage | context returns state; next deterministically returns readiness, blockers, and judgment triggers |
| Next packet is also bounded | server measures final serialized next packet and rejects anything above the graph-version calibrated ceiling |
| Runtime resolution is node-local | no untriggered conditionals or future-node gaps in context |
| Full contracts are opt-in | CLI subprocess test for `--include-contracts` |
| Reviewer use is risk-bounded | L1/L2 default zero; L3 one specialist; L4 proposer plus one reviewer, third only on disagreement |
| Token cost is attributable | Agent Invocation stores one bounded category breakdown and sponsoring task/branch refs without graph usage rows |
| Token regression blocks activation | graph shadow token total cannot exceed the recorded baseline |
| Shadow comparison is like-for-like | distinct owned graph/baseline run IDs must share one immutable RunSpec hash |
| Shadow totals are real and non-zero | Agent Flow derives both totals from normalized settled invocations; `0/0` cannot activate |
| Token budget preserves work | over-budget context disables new reviewers and keeps backend jobs running |
| Work cannot start beyond a configured cap | one atomic Agent Invocation reservation must fit its current Agent Budget Period |
| Missing provider usage remains bounded | settlement charges the reservation as `reserved_fallback` and records measurement quality |
| Runtime replacement cannot block startup | provider-neutral adapter accepts a changed runtime/model without changing Agent identity or requiring HMAC receipts |
| Attribution does not double count | Skill/artifact/cache subsets cannot exceed input tokens |
| Context has a real response cap | server enforces the calibrated graph ceiling plus a protocol absolute maximum; activation also requires actual token and latency evidence |
| Request hot paths are schema-free | startup migration runs once; traced graph requests execute 0 DDL and 0 `PRAGMA table_info` |
| Context database cost is history-independent | current node/resolution/plan projections live on the branch; routine context performs 0 trace-history scans and 0 Agent Flow reads |
| Context reads have a measured fixed upper bound | query-count tests pin a constant owner/instance/branch read path independent of trace, catalog, and usage-history size |
| Routine transition has bounded I/O | query-count tests permit only bounded canonical reads, one changed branch update, and one trace insert; unchanged readiness performs zero writes |
| Immutable graph reads are cached safely | cache key includes database path, graph ID, version, and content hash; callers receive defensive copies |
| Unchanged resolution does not write | identical branch resolution/hash readiness reports zero changed rows |
| Graph persistence is minimal | migrated schema has exactly six Graph owners and no legacy proposal/review/authorization/resolution/budget/rollback tables |
| Agent Flow persistence is minimal | independent store has exactly Agent Budget Period and Agent Invocation lifecycle owners |
| Instance creation avoids duplicate owners | creation writes one instance and initial branch only; it creates no graph token-budget or node-resolution row |
| Job completion avoids duplicate assurance | terminal transaction updates JobAttempt assurance summary and creates no assurance row |
| Activation avoids graph duplication | activation validates one immutable version and one satisfied Maintenance Case, then changes only the active pointer |
| Rollback avoids a second history | approved rollback is an active-pointer change referenced by Maintenance Case and graph trace |
| TrialPlan retention is safe | trace holding a referenced TrialPlan remains retention-pinned while dependent run/job/conclusion records exist |
| Graph protocol deterministic | stable hash tests over canonical JSON |
| Invalid graphs rejected | public validator tests |
| CLI is agent-readable | installed-command JSON subprocess tests |
| Server graph is authenticated | Flask route tests with distinct users |
| Active graph immutable/versioned | SQLite service tests and API history |
| Unaffected jobs continue | integration test with two independent branches |
| Skill cannot execute unapproved | local runtime gate requires a matching conversation approval for first or changed execution |
| Server stores no Skill identity | SQLite persistence inspection and server input rejection tests |
| Local Skill usage is auditable | append-only local audit records identity, content hash, approval, load/reuse, invocation, and result refs |
| Changed Skill content cannot reuse stale authority | content/authority mismatch invalidates only the local reuse hint and requires fresh runtime load/approval |
| Cache scope is truthful | capability output declares `cache.scope=process`; separate installed CLI calls do not claim a hit |
| Model replacement is semantics-neutral | model/Codex telemetry changes do not change semantic cache or graph hash |
| Provider roots are relocatable | environment-root conformance tests for Codex and external providers |
| Scope drift re-enters audit | proposal lifecycle integration test |
| Auditor cannot edit graph directly | API authorization/transition tests |
| Draft does not constrain live work | shadow-mode integration test |
| Active graph can roll back | approved active-pointer change plus Maintenance Case and trace reference test |
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
execution count, and both non-zero token totals from normalized settled Agent
Invocations. Client-submitted metric values are diagnostic only. Activation
accepts only evidence derived by the authoritative Agent Flow/Graph owners.

## Issue 140 Batch 6 release evidence

Batch 6 finalized the cutover from parent `2d951a42`. The original six-batch
cutover did not activate, merge, or push the branch. The independently audited
follow-on activated immutable Graph v6 at
`aee02eed6ec617cebf3e208390fa826460c28fc88fb3919c3637162e31537d41`
and continued the real SgCCS and Trend branches without rewriting their v5
instances, traces, Runs, or Jobs. The current bounded acceptance facts are
content-addressed in
[`batch6-token-context-receipt.json`](research-decision-graph/acceptance/batch6-token-context-receipt.json).

- Final Graph persistence has exactly six owner tables. Final Agent Flow
  persistence has exactly two owner tables, and its Invocation owner has 33
  canonical columns with no legacy reservation or provider-receipt IDs.
- Runtime schema checks reject legacy or unexpected owners. The warm Graph
  check is one `SELECT` with no DDL or `PRAGMA`; the startup-only Agent Flow
  check is one owner `SELECT` plus two bounded column inspections. Request
  handlers reuse the verified schema state.
- A TrialPlan-to-ResearchRun binding performs one read and one write and no
  schema operation. An unbound run remains valid and exposes no invented
  TrialPlan projection.
- Routine branch context performs one branch `SELECT` without scanning trace
  history, immutable graph versions, or Agent Flow. An unchanged capability
  resolution performs zero writes. A changed transition performs one branch
  `SELECT` inside one `BEGIN IMMEDIATE`, followed by one branch update and one
  trace insert; it does not reread the immutable graph version.
- Capability resolution is current-node and transition-target local.
  Triggered conditional gaps block the applicable transition; untriggered and
  future-node gaps do not enter current Agent context.
- Replay is server-owned and non-mutating. Shadow comparison includes Job
  kind, RunSpec, source revision, runner path, and execution-plan identity, so
  equal numeric outputs from semantically different jobs cannot self-certify
  equivalence.
- The offline finalizer is dry-run by default. Apply requires
  `--confirm-offline`, creates database backups, runs Graph then Agent Flow
  migration and exact-schema verification, is idempotent, restores both
  backups on failed final verification, and reports the parent commit plus
  exact database rollback target.
- Batch 1–3 migration reports now expose their before/after schema owner
  counts, actual traced SQL read/write/DDL counts, transaction count, elapsed
  milliseconds, and exact parent-commit rollback target. Batch 4–6 expose the
  same release evidence directly or through the final cutover coordinator;
  none of this telemetry creates a database owner or a routine runtime write.
- Final release gates on 2026-07-19: server/CLI/factor-workspace suite
  `260 passed`; installed Harness suite `41 passed`; installed Harness
  subprocess replay from `/tmp` `11 passed`; generated factor workspace
  Pylance/Pyright gate `1 passed`; targeted production Pyright
  `0 errors, 0 warnings`; both canonical and packaged Skills pass
  `skill-creator` validation and are byte-identical.
- The 2026-07-20 v6 activation gate derived a 2,703-byte routine context,
  charged 800 conservative fallback tokens against a 1,000-token baseline,
  found zero token failures, and proved like-for-like shadow equivalence.
  Post-activation SgCCS and Trend contexts measured 3,611 and 3,566 bytes.
  Both branches retain one trusted Job evidence delta, replay through their
  continuation and blocked-closure traces, preserve unknown Claims and open
  obligations, and therefore correctly remain `release_ready=false` until the
  deferred bootstrap-Sharpe capability becomes available.

## Decision 143 follow-on

The accepted Research Obligation Cycle is a follow-on version, not a
retroactive amendment to the completed issue-140 cutover. Its canonical
semantics are indexed as Grill decision 143 and its independently committed
schema/conformance, shadow replay, local reference Skill, Harness, Graph
shadow, and measured activation batches are defined in
[`research-obligation-cycle-work-package.md`](research-decision-graph/research-obligation-cycle-work-package.md).

Legacy Evidence Envelopes are excluded from every Agent-facing retrieval and
context surface. Deterministic compatibility may inspect only bounded
version/hash/eligibility metadata; reopened research must create new
current-schema evidence.

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
