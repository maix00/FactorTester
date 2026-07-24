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

**Verification Obligation Category**:
A stable, coarse Graph-owned semantic class used by Research Agents to register
branch-specific Verification Obligations, for example factor semantics, data
semantics, statistical validity, or execution semantics. A category is not a
checklist item and should change rarely.
_Avoid_: Concrete obligation, node-specific requirement, factor-specific question

**Requirement Catalog**:
The versioned, human-readable part of an immutable Graph that explains each
Verification Obligation Category and Entry Requirement with a Chinese title,
decision question, selection guidance, expected evidence, non-sufficient
evidence, and reporting expectations. Research Agents load only the categories
and requirements relevant to the current local context.
_Avoid_: Opaque ID list, full-catalog Agent packet, Skill identity, fixed checklist

**Entry Requirement**:
A versioned, finer-grained semantic requirement declared by a node entry gate
under one Verification Obligation Category. It describes what must be
reconsidered at that entry point without prescribing the branch-specific
wording or conclusion of a Verification Obligation.
_Avoid_: Concrete obligation, workflow node, universally closed checklist

**Entry Requirement Coverage Decision**:
A checkpoint-local audited relation stating which accepted branch-local
Verification Obligation revisions cover one Entry Requirement revision at one
node. It is reusable while the requirement, obligations, evidence scope, and
relevant hashes remain unchanged.
_Avoid_: New obligation, global semantic match, unaudited similarity score

**Entry Audit Projection**:
A deterministic, report-facing projection of an actual node entry or
continuation re-entry. It explains the applicable Entry Requirements, covering
or changed obligations, preserved or reference-only evidence, unresolved
requirements, and the resulting transition eligibility.
_Avoid_: Raw trace JSON, hidden gate, a second research report

**Report Method**:
A reusable, versioned semantic reporting contract declared by the Active Graph
for an entry, node action, or edge. It states which facts and bindings must be
reported, while the CLI owns validation and rendering and the Research Agent
supplies only the required analysis.
_Avoid_: Factor-specific prose, Markdown template, UI layout, report database row

**Report Item**:
One ordered, independently bound contribution produced under a Report Method.
Its content may be a sentence, list, table, or content-addressed figure, and it
binds the canonical evidence, TrialPlan, obligation change, claim, run, or delta
references that the item analyzes.
_Avoid_: Unstructured report blob, UUID-only chip, copied raw artifact

**Factor Column Reference Summary**:
The ordered distinct `ColumnRef` values found in one deterministically
validated factor expression. It is a compact expression-inspection fact and
does not assert that a column should become a parameter or that any
substitution is economically coherent, decision-relevant, or valid.
_Avoid_: Parameterization opportunity object, Verification Obligation, valid factor

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

**Research Workspace**:
The stable user/Profile research space that owns configurations, RunSpecs,
ResearchRuns, and JobAttempts. Day/night sessions, fees, frequency, sample
scope, and other execution alternatives are not separate workspaces.
_Avoid_: One workspace per RunSpec, scenario, or Trial arm

**Workspace Configuration**:
The editable configuration used to author and preview research inputs inside
one Research Workspace. Editing it does not rewrite an already frozen Run
Configuration Snapshot or RunSpec.
_Avoid_: Immutable RunSpec, reusable template, second workspace

**Run Configuration Snapshot**:
An immutable, content-addressed capture of one Workspace Configuration inside
the same Research Workspace. A Trial Plan may bind several snapshots, such as
day and night arms, without creating additional workspaces. Its source
configuration and revision remain auditable.
_Avoid_: Mutable workspace configuration, cross-workspace execution carrier

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

**Graph Version Publication**:
A Server Maintenance Agent operation that creates and audits one immutable Factor Research Graph version without running research or moving existing branches.
_Avoid_: Graph upgrade, branch migration, active-pointer change

**Graph Version Activation**:
An authorized Server Maintenance Agent operation that changes only the active Graph pointer used by newly created research.
_Avoid_: Graph upgrade, research execution, automatic branch migration

**Research Branch Continuation**:
An authorized Server Maintenance Agent operation that preserves one Hypothesis Branch's immutable history and same-named current node while entering a direct-child Graph through that node's mandatory re-entry gate.
_Avoid_: Graph upgrade, research replay, data check, TrialPlan regeneration

**Node Re-entry Gate**:
A target-node-owned guard that blocks ordinary work and outward transitions after an explicit Graph-version change until the node's newly applicable blocking obligations are accepted and resolved or bounded.
_Avoid_: Re-entry node, migration workflow, Server Agent resume choice

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
- A running production **Hypothesis Branch** remains on its pinned Graph
  version. Neither activation nor impact detection moves it automatically;
  continuation begins only after the user explicitly requests a version change
  in FTClient or through the Research Agent's CLI/conversation path.
- **Graph Version Publication**, **Graph Version Activation**, and **Research
  Branch Continuation** are distinct Server Maintenance Agent responsibilities.
  Publication creates an immutable definition; activation changes only the
  active pointer; continuation moves only an explicitly affected branch.
- **Research Branch Continuation** may validate version identity, direct
  parentage, authorization, compatibility, lineage, the previous current node,
  the target Graph's same-named node and re-entry declaration, and rollback
  target. The Server Maintenance Agent cannot choose or bypass the node's
  re-entry gate. It cannot
  inspect data availability, check
  factor-field coverage, create or discharge Verification Obligations,
  generate a Trial Plan, interpret research evidence, modify a factor, or rerun
  a Job.
- A **Node Re-entry Gate** belongs to its target node and is not a separate
  graph node. An explicit version change preserves `current_node`; normal node
  work and normal outward edges remain unavailable until the gate is satisfied.
- For an explicit change to a descendant Graph version, deterministic code
  validates the ancestry and computes one cumulative source-to-target Graph
  diff. Intermediate versions do not require Agent turns or intermediate
  branch incarnations. Only triggered semantic obligation discovery may invoke
  a Research Agent after the target node's re-entry gate is established.
- A re-entry requirement that makes previously adjudicated factor semantics
  uncertain reopens the matching existing **Verification Obligation**; it does
  not create a migration-specific duplicate. Obligation discovery is triggered
  only when no existing obligation can express the material question.
- The persisted graph branch is the Hypothesis Branch owner. It contains
  research/statistical state, not token, compute, concurrency, fee, or
  reviewer-usage aggregates.
- A **Research Decision Contract** is derived from one Work Package and its
  Hypothesis Branch; it adds no persistence owner or operational budget.
- A versioned obligation-discovery method proposes **Research Claims** and
  **Verification Obligations** from the Contract and current accepted
  projection. The inventory is extensible rather than a closed checklist.
- Each accepted **Verification Obligation** registers under one or more stable
  **Verification Obligation Categories**. A node entry gate declares versioned,
  finer-grained **Entry Requirements** beneath those categories. On entry or an
  explicit Graph continuation, the Research Agent compares the accepted
  branch-local obligations in the relevant category with each changed Entry
  Requirement and proposes whether an existing obligation is sufficient,
  should be reopened/revised, or a new obligation is needed.
- The Research Agent Skill instructs category/requirement selection, while the
  Graph-owned **Requirement Catalog** supplies the versioned domain meanings.
  `context/next` returns category titles and only currently relevant requirement
  summaries; full descriptions are fetched by ID on demand. A description or
  subcategory change requires a new Graph version and preserves prior refs.
- The Graph supplies a stable `other`/unclassified category. A concrete
  obligation that does not fit an available category may register there, but
  that registration never satisfies a category-specific Entry Requirement by
  itself. On an explicit Graph continuation, newly added or refined categories
  trigger scoped Research Agent review of relevant unclassified obligations so
  their registration can be revised without replacing their identity or
  evidence history.
- Accepted coverage is recorded per node and Entry Requirement revision as an
  **Entry Requirement Coverage Decision** listing the covering local obligation
  revisions. Normal execution reuses the decision; semantic rematching is
  reserved for explicit Graph continuation or changed hashes.
- A continuation re-entry first attempts to satisfy newly applicable or
  reopened obligations. Existing evidence remains immutable and may be reused
  when its provenance and scope still support the target requirement. If a
  target Entry Requirement cannot be satisfied, evidence affected by that gap
  remains available only as clearly labelled reference material for the
  specific claims that depend on the unmet requirement; unrelated claims and
  evidence retain their independently established status. Reference-only
  evidence cannot authorize the gated outward transition for an affected
  claim.
- Every actual node entry, including ordinary same-version entry and
  continuation re-entry, emits an **Entry Audit Projection** into the
  chronological Chinese research report. Cached unchanged decisions are
  projected compactly and do not require a new LLM judgment.
- Every Graph entry, node action, and edge declares required, reusable **Report
  Methods**. The Graph owns when and what semantic reporting is mandatory; the
  CLI owns the method schema, preflight validation, reference completeness,
  Simplified Chinese checks, and deterministic Markdown/UI/PDF projection.
- A required method yields ordered **Report Items**, not one prose blob. Each
  affected requirement, obligation, claim, evidence qualification, TrialPlan
  item, result, or next decision is reported separately as the most appropriate
  sentence, list, table, or figure. Canonical refs produce labelled lazy-loaded
  chips beside the relevant item; raw UUIDs and full artifacts do not enter the
  reading flow.
- Every Report Item carries the exact Graph-declared `report_requirement_id`
  that it addresses and, for per-object requirements, the canonical
  `subject_ref` it reports. A node entry, node action, or edge may complete only
  when deterministic set/cardinality/binding validation finds full coverage.
  Validation returns an itemized list of missing requirement IDs, subjects, or
  bindings; it never reports only a generic “report incomplete” error. The
  local report body remains local; transition evidence carries only the compact
  hash-bound projection derived from the validated items, not a new receipt
  object or database row.
- Every Graph-declared report requirement pins one versioned, real Entry
  Requirement subcategory through `entry_requirement_ref`. That binding explains the
  research norm behind the required item and lets the UI connect the report to
  relevant local obligations and coverage decisions. Reporting the item never
  discharges the Entry Requirement or its Verification Obligations; semantic
  satisfaction and report coverage remain independently validated states.
- A missing Report Item is a deterministic gate error, not a new obligation
  kind. The Research Agent uses the bound Entry Requirement to find the relevant
  concrete Verification Obligations: it reopens or revises an incomplete match,
  or creates a substantive concrete obligation under that real subcategory when
  none exists. A purely missing rendering of an already adjudicated obligation
  does not justify inventing a duplicate Verification Obligation.
- FTClient presents Report Items as the primary chronological reading flow.
  Graph-continuation/re-entry items use a visibly distinct transition treatment
  while remaining in the same continuous report; they are not shown as ordinary
  research findings or as a second report.
- Trace `created_at` is the trusted server recording time and remains the owner
  of cursor, topology, HEAD, stale-write, and audit ordering. A checkpoint event
  or Report Item may additionally carry one timing envelope with optional
  `occurred_at`, `time_basis=transition|historical_backfill`, and source refs.
  Historical occurrence time improves narrative attribution but never reorders
  topology or changes the current branch/Profile/Work Package freshness.
- Historical Agent-conversation registration is a dedicated, idempotent CLI
  action over the existing Work Package, branch, trace carrier, local journal,
  and artifact refs. It inserts only missing immutable report fragments and
  rebuilds deterministic projections; it does not transition the Graph, move
  `latest_trace_id`, or add a persistence owner. Conflicting narrative, broken
  provenance, wrong branch, or source cycles fail closed. UI page-access time
  and Markdown/PDF renderer time are not research facts.
- Node and edge reporting have distinct anchors and presentation. A node item is
  part of the stage it analyzes; an edge item explains an actual transition
  between source and target stages. Graph continuation uses the edge treatment
  plus explicit source/target Graph versions. Missing requirements appear at
  the exact node or edge anchor as pending coverage, never as a fabricated
  completed chapter.
- When an unmet Entry Requirement blocks a test node, the Research Agent must
  attempt to synthesize the next decision-relevant TrialPlan that could change
  the affected obligations or claims. If no meaningful TrialPlan remains, the
  branch proceeds to evidence-bounded research closure rather than silently
  passing the node. Every affected claim, evidence qualification, obligation,
  and missing requirement is projected as a separate report item.
- A Research Agent that finds no adequate category may propose a new category;
  one that finds a missing reusable Entry Requirement may propose that finer
  requirement. Neither proposal changes the Graph until Graph Maintenance
  review, document-grounded grill, and human audit accept it into a future
  Graph version.
- Deterministic factor-expression inspection exposes a **Factor Column
  Reference Summary** with the existing compact factor description. A
  Research Agent inspects the source-accessible original expression for
  economic, dimensional, price-basis, direction, timing, and construction
  errors, then may identify a parameterization opportunity and propose a
  **Verification Obligation** only when an economically coherent substitution
  could change the construction, Trial Plan, permitted use, or bounded
  research decision. Fixed columns do not create obligations mechanically;
  the backend does not recommend substitutions or infer economic roles. A
  semantics-changing parameterization retains independent factor-family
  lineage rather than overwriting the original family.
- Original factor source is loaded locally and on demand at factor semantics:
  prefer the claimed Profile worktree, otherwise use the existing authorized
  FactorTester description command. Source and full expressions do not enter
  routine Agent packets, Graph traces, or reports. When source/math access is
  not authorized, the Agent records the visibility limitation and cannot claim
  to have completed economic-expression review.
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
  binds exactly one plan version, one RunSpec hash, one server-derived current
  sample stage, one comparison-arm trial role, and one comparison identity,
  which its JobAttempts inherit. Submission outside the plan-bound execution
  node fails closed.
- Multiple day/night, fee, frequency, or sample-scope arms remain in the same
  Research Workspace. Each arm freezes a Run Configuration Snapshot and
  RunSpec; none may use a temporary workspace as an execution carrier.
- A Trial Plan whose input identities are invalid may be superseded within the
  same Hypothesis Branch only before any Run, JobAttempt, Evidence, or sample
  exposure exists. The replacement preserves the research contract,
  methodology, obligations, design, stage policy, old plan, and trace; it may
  change only the invalid configuration/RunSpec/action-input identities and
  starts from a new unreleased execution checkpoint.
- A factor revision crosses the server-owned new-hypothesis edge before the
  old current-plan binding is released. The old TrialPlan and exposure remain
  immutable; a replacement plan begins a new identity at version 1.
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
- Routine Agent packets expose Claim identity plus a bounded obligation
  question summary and criterion ref/hash. Full current Claim or obligation
  bodies are read explicitly by ID from the latest checkpoint with one
  primary-key join; routine work never loads the whole checkpoint or history.
- **Bounded Closure** is recorded as one compact trace checkpoint plus a current
  branch disposition/hash. It requires one compact independent closure
  challenge and does not create a closure service/table. An accepted new or
  reopened decision-blocking obligation clears accepted or pending closure in
  the same replay event; rejected and non-blocking deltas do not.
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
