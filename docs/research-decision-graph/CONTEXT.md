# Research Decision Governance

This context defines how evidence-driven factor research is orchestrated,
reviewed, resumed, and evolved without replacing FactorTester computation or
turning routine transitions into LLM conversations.

## Language

### Research method

**Factor Research Graph**:
A versioned graph whose nodes and edges express factor-research decisions,
guards, evidence requirements, and triggered capability descriptions.
_Avoid_: Agent workflow, job scheduler, fixed checklist, knowledge graph

**Candidate Discovery**:
The bounded process that finds, creates, repairs, or re-roles a factor
candidate before its hypothesis is frozen.
_Avoid_: Alpha whitelist, full factor-library scan

**Hypothesis Branch**:
An immutable research path beginning when a testable candidate is
preregistered and bound to its trial records.
_Avoid_: Draft idea, mutable experiment

**Trial Plan**:
A versioned statistical-design contract for one hypothesis branch containing
outcomes, sample roles, planned comparisons, stopping, multiplicity, and
decision criteria.
_Avoid_: Work Package budget, graph edge threshold, mutable run note

**Data Availability Profile**:
A compact point-in-time description of the product scope, frequencies, actual
coverage, update time, permissions, and registered historical, delayed,
paper-stream, or live-stream modes available to research planning. It does not
assign sample roles or prove that a stream is real-time.
_Avoid_: Full provider catalog, requested date range, `live=true`

**Sample Scope Identity**:
A server-derived identity for one RunSpec's time and product scope, independent
of factor expression, sample role, or result. It supports exposure audit but
does not by itself prove that data was unseen outside the server.
_Avoid_: Client-declared sample hash, market-regime label, conclusion

**Prospective Holdout**:
A Sample Scope whose outcomes remain unavailable until the current hypothesis,
factor version, Trial Plan, and decision rule are frozen. The most recent
available sealed range is normally preferred for forward relevance, but
recency alone does not make a sample a holdout.
_Avoid_: Latest date, fixed validation stage, any later historical range

**Historical Regime Evidence**:
Evidence from already known historical market backgrounds used for temporal
stability, regime robustness, and transfer obligations. It is not relabelled
as untouched out-of-sample evidence after inspection.
_Avoid_: Universal OOS, final confirmation

**Prequential Evidence**:
Prospective paper or live observations evaluated test-then-train against a
factor and decision version frozen before each observation became available.
_Avoid_: Any live feed, post-hoc replay, broker permission

**Job Evidence Receipt**:
A source-free read projection of one JobAttempt's execution status, hashes,
exit code, terminal-assurance summary, and
stdout/stderr/metric/artifact references. It is not independently persisted.
_Avoid_: New receipt table, duplicate write, full log, research conclusion

**Evidence Envelope**:
The validated bounded schema stored in an existing append-only graph trace's
`evidence_json`. It references canonical Job/assurance facts and binds required
evidence, trial counts, stopping facts, metrics, conflicts, and limitations.
It does not authoritatively interpret a Claim or discharge an obligation.
_Avoid_: Second event store, parent-hash subsystem, artifact container

**Research Decision Contract**:
A versioned normalized view over one Work Package and its Hypothesis Branch
that fixes the decision, permitted-use boundary, research scope, search and
coverage design, applicable methodology, and decision-blocking obligation
policy. It is not a separate persistence owner.
_Avoid_: Universal truth claim, new contract table, token budget

**Research Claim**:
A falsifiable, scope-bound statement whose current evidence interpretation is
maintained in the Hypothesis Branch projection.
_Avoid_: Factor is valid, narrative mechanism, Evidence Envelope

**Verification Obligation**:
A scoped, revisable epistemic responsibility tied to a Research Claim,
decision, assumption, alternative explanation, failure condition, or transfer
boundary. The accepted current projection is branch-local; immutable proposals
and changes remain in graph trace.
_Avoid_: Workflow stage, hard-coded checklist, missing machine field

**Adjudication Proposal**:
A reviewable proposal containing a paired Claim-evidence delta and obligation
delta, either of which may explicitly be a no-op, plus a compact Decision
Warrant and evidence references.
_Avoid_: Hidden chain-of-thought, direct state mutation, backtest conclusion

**Adjudication Decision**:
The authority-bearing accept, reject, or revise disposition that applies the
paired deltas atomically. Evidence Envelopes and Agent assertions alone cannot
change the accepted projection.
_Avoid_: Reviewer for every transition, Evidence Envelope status

**Bounded Closure**:
A defeasible, Research-Decision-Contract-scoped pause reached when
decision-blocking obligations are resolved or explicitly bounded, declared
coverage/stopping rules are satisfied, and no currently justifiable admissible
positive-information-value TrialPlan remains. It carries limitations and
re-entry predicates.
_Avoid_: Research is complete, metric threshold, universal factor validity

**Provisional Memory**:
Local, reviewable process evidence from one research path that has not been
promoted into a reusable graph rule.
_Avoid_: Active edge, global memory, chat history

**Factor Evidence Status**:
A reader-facing projection of bounded Research Claim evidence that a factor is
untested, evaluated, supported, contradicted, inconclusive, or superseded for a
specific immutable configuration and research scope. It is not independently
mutable.
_Avoid_: Valid factor, invalid factor, `$Rev`

**Market State Snapshot**:
A point-in-time, versioned, deterministic summary of market conditions used to
rank candidates or preregister conditioning hypotheses.
_Avoid_: Ex-post regime label, candidate whitelist

### Orchestration

**Agent Flow**:
The runtime-neutral orchestration layer for Agent identity, goals, Work
Packages, checkpoints, watchers, budgets, Git coordination, and routing.
_Avoid_: Factor Research Graph, LangGraph requirement

**Workspace Research Objective**:
The user-owned long-term direction covering all factor families in one
workspace.
_Avoid_: One factor run, server maintenance goal

**Work Package**:
A user-confirmed bounded research authorization containing objective, mode,
factor/product/data scope, permissions, exclusions, and expected evidence for
one Research Agent.
_Avoid_: Entire workspace objective, backend maintenance case

**Targeted Research**:
A Work Package mode with an already identified primary factor or factor range.

**Open Discovery**:
A Work Package mode authorizing an Agent to create and study new candidates
inside a confirmed market, data, theme, permission, and exclusion boundary.

**Coordination Checkpoint**:
The compact server record needed to resume an Agent identity and affected
branch without storing local source, full artifacts, or reasoning.
_Avoid_: Full research checkpoint

### Capability and governance

**Capability Gap**:
A bounded, general, source-free contract showing that an exact approved
implementation required by the current branch is unavailable.
_Avoid_: Factor failure, approximate fallback, whole-graph capability scan

**Maintenance Case**:
A bounded Server Maintenance workflow that reviews, implements, validates, and
releases one graph, Skill, statistical-policy, or backend change.
_Avoid_: Factor Research Graph node, permanent LLM monitor

**Document-grounded Grill Audit**:
A one-question-at-a-time high-risk change audit grounded in domain documents,
code facts, industry or statistical rules, concrete scenarios, and
counterexamples.
_Avoid_: Ordinary graph transition, UI approval, fixed Skill name

**Grill Decision Log**:
The working record of audit questions, user responses, final semantics,
evidence, impact, acceptance criteria, and revision lineage.
_Avoid_: ADR, transcript-only archive, routine Agent context

## Relationships

- A **Workspace Research Objective** produces one or more **Work Packages**.
- A **Work Package** is owned by one Research Agent at a time and may create
  many independent **Hypothesis Branches**.
- The persisted graph instance is the Work Package projection and references,
  but does not own, its Agent Flow resource scope.
- A **Work Package** may reference an Agent Flow resource-budget scope, but
  does not define token, compute, time, concurrency, statistical stopping, or
  multiplicity semantics.
- **Candidate Discovery** may short-circuit for **Targeted Research** or
  generate bounded candidates for **Open Discovery**.
- A **Hypothesis Branch** follows one pinned **Factor Research Graph** version.
- The persisted graph branch is the Hypothesis Branch owner. It contains
  research/statistical state, not token, compute, concurrency, fee, or
  reviewer-usage aggregates.
- A **Research Decision Contract** is derived from one Work Package and its
  Hypothesis Branch; it adds no persistence owner or operational budget.
- A versioned obligation-discovery method proposes **Research Claims** and
  **Verification Obligations** from the Contract and current accepted
  projection. The inventory is extensible rather than a closed checklist.
- Machine-invalid identity, chronology, scope, or timing remains a deterministic
  guard instead of being inflated into a Verification Obligation.
- A **Hypothesis Branch** binds one current immutable **Trial Plan** before
  selection-relevant outcome inspection.
- Planning queries one **Data Availability Profile** before proposing sample
  scopes. The Planning Agent first confirms the user-authorized product range;
  data-source availability never broadens it implicitly.
- The server derives **Sample Scope Identity** from the exact RunSpec and
  records creation of a ResearchRun as exposure. Each Trial Plan declares only
  the ordered sample stages justified by its obligations; the Graph does not
  impose one universal sequence. Sample stage remains distinct from a
  comparison-arm trial role.
- **Historical Regime Evidence** may discharge robustness or transfer
  obligations. A final **Prospective Holdout** remains sealed until its
  decision-blocking obligation is opened; **Prequential Evidence** requires
  version freeze and point-in-time event records in addition to a live source.
- A **Trial Plan** is generated only for selected actionable obligations; not
  every obligation requires a backend run.
- The **Factor Research Graph** requires and evaluates a **Trial Plan**
  reference but does not hard-code that plan's product- or hypothesis-specific
  numeric thresholds into graph topology.
- The server persists the compact immutable **Trial Plan** and binds its hash
  to submitted runs and returned evidence; full rationale and private
  references remain local.
- The compact plan is stored once in existing graph-trace evidence; the
  Hypothesis Branch retains its current-plan hash plus a compact current-stage
  projection, and no dedicated TrialPlan service/table is required.
- A trace containing a referenced TrialPlan is retention-pinned until its
  dependent run/job/conclusion history is explicitly deleted.
- A Research Agent drafts the **Trial Plan**; deterministic protocol validation
  is the default review path, with one Statistical Reviewer only for
  non-standard, ambiguous, protocol-deviating, or high-risk design.
- A **Trial Plan** may coordinate multiple immutable RunSpecs; each ResearchRun
  binds exactly one plan version, one RunSpec hash, one trial role, and one
  comparison identity, which its JobAttempts inherit.
- Existing persistence objects are implementation candidates, not frozen
  semantics. Implementation may refactor them when an ownership and query-path
  audit proves fewer duplicate facts, reads, or writes.
- Agent Flow alone owns resource budgets, usage aggregation, and wait/resume;
  graph traces carry only bounded transition evidence and references to
  resource-usage facts.
- UI configures the total token limit per Agent Profile and displays Agent Flow
  usage; UI/browser state is not the accounting owner.
- Agent Flow keeps one compact restart-safe budget state per claimed Agent ID,
  with at most one atomic reservation and one settlement around a real model
  invocation. Cache hits and unchanged state produce zero writes.
- The settlement transaction also appends one source-free usage item for UI
  task attribution; it never stores prompt, full context, factor source, or
  response body.
- UI may change a current limit or manually reset into a new immutable budget
  period. Reset retains history and waits for an active invocation to settle.
- Budget exhaustion is a derived Agent Flow pause. It preserves the Agent
  checkpoint, leaves graph/hypothesis state unchanged, and never stops an
  already submitted backend Job.
- A changed budget revision emits one deduplicated wake; unchanged budget and
  wait state create no polling, Agent invocation, or database write.
- UI initially reads only the selected Agent Profile and current budget
  aggregate. Task usage is lazy, cursor-paginated, and grouped at read time;
  v1 has no summary/compaction scheduler.
- A deterministic provider-neutral usage adapter emits input/output/cache,
  charged amount, measurement quality, and charging-policy version. Model or
  runtime changes do not change Agent budget identity or rewrite history.
- Missing actual provider usage settles conservatively from the reservation;
  it does not block Agent startup or require another Agent/Skill invocation.
- Agent Flow persists only two deep lifecycle objects: Agent Budget Period and
  Agent Invocation. Invocation unifies execution provenance, reservation, and
  provider-neutral settlement; overlapping legacy tables are migrated and
  removed rather than dual-written.
- Agent Invocation may include one bounded fixed-category context-cost
  breakdown generated deterministically. It contains counts, not context
  content or per-document rows, and adds no settlement transaction.
- Usage follows the Agent Flow execution owner: local Agent records remain in
  the local manager store and Server Agent records in the server store. UI
  routes and merges views but owns no accounting database or default sync.
- Agent ID is owner-pinned in v1. Model/runtime changes within one owner are
  seamless; cross-owner movement is an explicit atomic
  profile/budget/checkpoint transfer that revokes the old claim.
- Context-cost diagnostics belong to Agent Flow. Routine invocations do not
  wake an optimizer; repeated/threshold breaches create one deduplicated
  proposal, and semantic/code changes route to Maintenance/grill.
- Startup/resume is deterministic and role-specific. It returns only current
  authorized scope, one local branch packet, changed refs, node-local
  capability descriptions/reuse hints, and next action; it omits full
  graph/catalog/history/output and writes nothing for an unchanged revision.
- Agent Profiles are unlimited until UI sets a cap, so budget setup is not a
  prerequisite for work.
- Server packets contain only capability description/hash. Local packets may
  add an opaque approved reuse ref from local audit state; actual Skill
  identity/version/execution remains local and changed content/authority
  requires conversation approval.
- Backend assurance is deterministic validation inside the existing JobAttempt
  terminal transaction. Conforming results require no reviewer or separate
  receipt lookup; concrete anomalies/suspicion route to Maintenance.
- An anomalous Job remains immutable. Evidence ineligibility is derived from
  Job assurance and Maintenance disposition, not a branch-pause row. Confirmed
  fixes produce a new backend revision and JobAttempt; old/new coexist.
- One durable Maintenance Case queue coordinates all maintenance kinds using
  bounded refs to canonical owners. It has no per-kind/event tables, writes
  only material state changes, and UI cannot approve/disposition it.
- Runtime trust uses checkpoint/history, hash, and resource AuthN/AuthZ.
  High-risk effects consume one exact-hash authenticated conversation approval;
  cryptographic attestation is reserved for real cross-boundary release
  provenance rather than same-server routine transitions.
- Final persistence is six Graph owners (versions, active pointer, instances,
  branches, trace, Maintenance Cases) and two independent Agent Flow owners
  (budget periods, invocations). Assurance belongs to JobAttempt, current
  resolution to branch, and rollback to an approved pointer change.
- A **Job Evidence Receipt** is projected from existing JobAttempt, artifact,
  and terminal-assurance summary fields without a new write.
- A graph transition or research decision stores one validated
  **Evidence Envelope** inside its existing graph trace without copying full
  stdout, metrics, or artifacts.
- An **Evidence Envelope** records facts and never directly changes Claim or
  obligation state.
- Legacy Evidence Envelopes are audit-retained but are not available to
  Research Agents, Reviewers, Skills, or ordinary Agent retrieval. A
  deterministic compatibility path may inspect only the minimum
  version/hash/eligibility metadata needed to mark them legacy-ineligible.
  Reopened research produces new current-schema evidence.
- One accepted **Adjudication Decision** applies its proposal's Claim-evidence
  and obligation deltas atomically to separate replayable projections. Routine
  deterministic or exactly preregistered judgments need no reviewer; material
  semantic, post-hoc, non-standard, or conflicting judgments require one
  relevant independent reviewer.
- **Bounded Closure** is recorded as one compact trace checkpoint plus a current
  branch disposition/hash. It requires one compact independent closure
  challenge and does not create a closure service/table.
- New evidence, scope, Factor versions, Graph/methodology, product rules,
  operators, or backend semantics reopen only Contracts matched by explicit
  impact or re-entry predicates. Unrelated jobs and branches continue.
- The server stores methodology/capability descriptions and bounded semantic
  change proposals, never concrete Skill identity or body. The local audit
  records the actual progressively loaded reference Skill, approval, and use.
- An affected **Hypothesis Branch** emits at most one deduplicated
  **Capability Gap** for the same gap hash.
- A **Capability Gap** creates a **Maintenance Case** outside the
  **Factor Research Graph**.
- A high-risk **Maintenance Case** may require a
  **Document-grounded Grill Audit**.
- Accepted audit semantics are appended to the **Grill Decision Log** and are
  implemented by an Agent; the human auditor does not edit graph or source
  records.
- **Provisional Memory** can propose a graph change but does not itself become
  an active edge.

## Example dialogue

> **Research Agent:** "The current hypothesis branch needs a pointwise `tanh`
> capability, but the local binding has no approved implementation. I recorded
> a source-free Capability Gap and checkpointed only this branch."
>
> **Server Maintenance Agent:** "The change affects a backend contract, so I
> opened a Maintenance Case. The audit will compare the proposed semantics,
> existing FactorExpr contract, NaN behavior, batch/incremental parity, and
> counterexamples one question at a time."
>
> **Auditor:** "The capability intent is accepted. Implement it without
> changing existing operator semantics, then publish the bounded conformance
> result reference."

## Flagged ambiguities

- “Active flow” previously referred to both research method and Agent
  orchestration. Resolved: **Factor Research Graph** owns research semantics;
  **Agent Flow** owns runtime orchestration.
- “Grill inside the Active Graph” implied a routine graph node. Resolved:
  high-risk audit belongs to a **Maintenance Case** outside the ordinary
  research graph.
- “Validated factor” implied global truth. Resolved: use scope-bound
  **Factor Evidence Status**.
- “Goal keeps an Agent online” implied continuous LLM execution. Resolved: the
  goal persists while deterministic event/watch logic wakes an Agent only when
  action is possible.
- “Work Package budget” previously mixed user authorization, statistical
  stopping, and runtime resource control. Resolved: **Work Package** owns
  research authorization, **Factor Research Graph** owns statistical research
  semantics, and **Agent Flow** owns operational resource enforcement.
