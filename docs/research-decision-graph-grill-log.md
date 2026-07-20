# Research Decision Graph Grill Decision Log

## Status and purpose

This file is the compact index for the working, append-only semantic record of
the current design grill. It is not an ADR and is not a transcript. An ADR
remains deferred until replay and shadow validation make the architecture
stable enough to justify one.

Each accepted decision records the smallest durable meaning needed to prevent a
later Agent, model, Codex release, or Skill-provider change from silently
reinterpreting the design. Routine research Agents do not load this full file;
they receive only the current-node policy or decision references selected by
deterministic code.

Provenance:

- Codex task: `019f6e0d-aa60-7160-9854-421bb564cb5b`
- branch: `codex/issue-123-research-decision-graph`
- working plan: `docs/research-decision-graph-plan.md`
- first continuously emitted question number: `48`
- latest accepted question in this revision: `142`
- latest discussed question in this revision: `142`

The discussion before question 48 was not emitted with stable per-question
numbers. It is therefore recorded as a pre-numbering phase rather than being
assigned invented question numbers.

Detailed records:

- [pre-numbering phase](research-decision-graph/grill/pre-numbered.md)
- [questions 48–72](research-decision-graph/grill/0048-0072.md)
- [questions 73–93](research-decision-graph/grill/0073-0093.md)
- [questions 94 onward](research-decision-graph/grill/0094-current.md)
- [Research Decision Governance language](research-decision-graph/CONTEXT.md)

This index gives final dispositions for fast lookup. The detailed records are
authoritative when a user correction, rejected alternative, evidence basis,
scenario, acceptance condition, or supersession relationship matters.

Neither this index nor the detailed reconstruction replaces the original Codex
task record. Before implementing a decision, the implementing Agent must reopen
task `019f6e0d-aa60-7160-9854-421bb564cb5b`, read the relevant original
question, user response, and surrounding corrections, then record the reviewed
turn references in the implementation or release evidence. If the conversation
and this reconstruction differ, implementation pauses and the discrepancy
returns to document-grounded audit.

## Record format

Every future entry must contain:

- question number and disposition: accepted, rejected, revised, or superseded;
- final canonical meaning, not merely the proposed wording;
- evidence basis: user scope, code, domain document, statistical or market
  convention, replay, or counterexample;
- affected boundary: Factor Research Graph, Agent Flow, Server Maintenance,
  backend capability, persistence, or acceptance gate;
- explicit reference to any earlier decision it revises or supersedes.

Full prompts, stdout, artifacts, source, and Skill bodies remain behind local
references. The log must not become an unbounded runtime prompt.

## Pre-numbering phase

The following accepted themes were recovered from the working plan, committed
graph protocol, external audit notes, code inspection, and the durable task
record. They are thematic decisions, not reconstructed verbatim questions:

- The Harness is an evidence and execution protocol around the real
  FactorTester lifecycle, not merely a CLI caller and not a fixed flowchart.
- The initial research process is a versioned, branching, adaptive graph with
  deterministic guards and narrowly invoked semantic judgment.
- The human is the sole server-side auditor; Agents propose graph, Skill, and
  backend changes, while the UI displays settings and prior decisions but does
  not approve them.
- Unaffected jobs continue when policy or capability changes occur; only
  affected branches wait at a checkpoint and resume after the canonical
  capability or Maintenance disposition changes.
- Skills are discovered progressively and require approval before first
  execution. The server stores need descriptions, while the local research
  ledger stores actual Skill identity and usage.
- Complete graph, capability catalog, artifacts, source, stdout, and history
  stay behind references. Routine context is a bounded local packet.
- Optional per-profile token caps are enforced before Agent work by the
  provider-neutral Agent Flow settlement model; database hot paths must have
  bounded reads and low-frequency writes.
- Backend reliability is presumed from the JobAttempt terminal-assurance
  summary; a specialist backend review starts only when evidence creates a
  concrete reason for doubt.
- Client factor workspaces are generated with typed stubs and must pass the
  configured Pyright/Pylance check. Paths and profiles are configured through
  UI/CLI surfaces rather than edited into user source.
- UI uses a human profile and can manage all profiles; CLI Agents may have
  separate profiles and must be able to claim an Agent ID without being tied
  to Codex or one model.
- User factor source remains local unless synchronization is enabled. Server
  factor registration keeps the factor identity, version, jobs, evidence, and
  non-source metadata while not retaining source or reconstructable formulas.
- The first graph is product-neutral and initially emphasizes single-factor
  research. China futures is a product-profile scope, not graph topology.
- Auxiliary factors may enrich a single factor or condition its strategy;
  independently selected or weighted alpha signals require the deferred
  multi-factor capability.

## Numbered decisions 48–72

| ID | Disposition | Final decision | Basis and affected boundary |
|---:|---|---|---|
| 48 | Accepted | An admissible missing general capability creates mandatory platform work, but never bypasses review, tests, or release. Only dependent branches pause. | User scope; Server Maintenance and capability gap |
| 49 | Accepted | Conditional enrichment may be preregistered before outcomes or proposed after outcomes only as a new hypothesis and trial with an unconsumed confirmation sample. | Statistical selection control; Factor Research Graph |
| 50 | Accepted | A documented industry/statistical rule can justify a Draft proposal after one valid case; otherwise independent repetition is required. Activation always needs replay, shadow comparison, and audit. | Statistical governance; graph evolution |
| 51 | Accepted | Conditioning candidates are bounded, mechanism-ranked, trial-ledgered, incremental, and ablated; no combinatorial brute force. | Overfitting and token budget; enrichment design |
| 52 | Accepted | A state, confidence, risk, or liquidity auxiliary need not have standalone alpha. Main-only baseline and interaction/stability evidence are mandatory; independent alpha routes to multi-factor research. | Quantitative semantics; single-factor boundary |
| 53 | Accepted | Candidate eligibility is tiered by scope-bound evidence, transfer need, untested library status, or Agent creation. Main/auxiliary is an experiment role, not a permanent factor label. | User scope and evidence reuse; candidate discovery |
| 54 | Revised | `$Rev` is a direction-negation parameter in a concrete factor configuration, not evidence status, a factor component, or proof of a reversal effect. | Code inspection; factor semantics |
| 55 | Accepted | Permissions, unavailable data, invalid timing, and incompatible product semantics are hard exclusions. Prior scope and market evidence only rank and warn; they never create a winner whitelist. | User correction; candidate discovery |
| 56 | Accepted | Candidate discovery must warn that confirmed/high-related factors are only starting points and must record whether broader or new-factor search was considered. | User scope; node exit evidence |
| 57 | Accepted | Market-state categories are open-ended, point-in-time definitions. Known regimes are starting points; outcome-derived new states belong to a later trial. | Causal timing; market-state discovery |
| 58 | Accepted | Exact factor, data, RunSpec, product, cost, and JobAttempt terminal-assurance matches are reusable. Scope mismatch requires revalidation; model/runtime change alone does not. | Hash identity; evidence reuse |
| 59 | Accepted | Every run writes compact provisional evidence deterministically. A Server Maintenance review wakes only for generalizable gaps, repeated decisions, counterevidence, reusable scope evidence, or changed norms. | Token control; graph evolution |
| 60 | Accepted | A branch pins its graph version. Existing jobs finish under the original version; affected branches migrate only at checkpoints with an immutable migration trace/reference. | Reproducibility; Agent Flow |
| 61 | Accepted | A missing research capability may be satisfied by an exact, auditable canonical composition; otherwise it requires a first-class operator or strategy capability. | Backend architecture; capability completion |
| 62 | Accepted | An existing family may accept a `FactorParam`, but formula changes create immutable new versions/configurations and never overwrite prior trials. | Code/domain model; factor versioning |
| 63 | Superseded by 65 | The proposed aligned-signal/raw-expression dual mode was rejected after code and boundary review. | Code inspection; FactorParam |
| 64 | Superseded by 65 | Sharing aligned/raw DAG modes in `FactorParam` was moved out of factor expression semantics and assigned to the execution engine or strategy layer. | Complexity boundary; execution architecture |
| 65 | Accepted | `FactorParam` means raw-expression composition; `FactorFamily` applies one final signal alignment; multi-frequency conditioning belongs to strategy/backtest; sharing and precomputed/live choice belong to the execution engine. | User correction and code inspection |
| 66 | Accepted | Raw auxiliary composition creates a new single-factor version. Entry/exit/position conditioning produces factor-plus-strategy evidence and cannot claim the original factor improved. | Quantitative semantics; evidence ownership |
| 67 | Accepted | Initial backend scope is `FactorExpr.tanh()`, a public typed `where`, and verified raw `FactorParam` nesting. Future missing operators are discovered and completed on demand, not prebuilt as an operator zoo. | User need and minimal capability scope |
| 68 | Revised by 72 | The initial nested `expr/operators/` proposal was rejected after architecture inspection; migration remains split into behavior-preserving batches. | Architecture review |
| 69 | Accepted | Operator migration requires snapshots of imports, catalog, hashes, display, FactorParam, batch/incremental behavior, source checks, SDK typing, and representative factors. Pure movement has zero intended semantic change. | Compatibility; release gate |
| 70 | Accepted | Planning chooses a user-confirmed primary scope. Research may autonomously discover/create auxiliaries and variants inside it; a new primary alpha direction returns to Planning and the user. | User authority; Agent Flow |
| 71 | Accepted | New local factors immediately enter the local library as experimental. Server metadata becomes discoverable after a run without source; positive, negative, and incomplete evidence remains visible. | Source privacy; factor registry |
| 72 | Accepted | Operator modules remain flat by semantic family under `expr/`; `conditional.py` owns the sole `WhereOp`, pointwise batch/incremental math shares a kernel, authoring metadata is separate, and no shallow one-operator hierarchy is added. | Architecture Skill and code inspection |

## Numbered decisions 73–93

| ID | Disposition | Final decision | Basis and affected boundary |
|---:|---|---|---|
| 73 | Accepted | Concurrent factor work uses sibling immutable versions and structural-hash reuse; no Agent overwrites another and no global lock or mandatory direct messaging is required. | Git/version semantics; Agent Flow |
| 74 | Accepted | An Agent can import an exact FactorRef only from an authorized shared local workspace/Git source. Server-only metadata is a clue and may not be used to reconstruct formulas. | Source privacy; local collaboration |
| 75 | Accepted | Research completes its Work Package and submits evidence/gaps; Planning reprioritizes with the user. Server Maintenance does not choose research priorities. | Role boundary |
| 76 | Accepted | Research starts from a compact packet of identity, scope, node/checkpoint, summaries, evidence references, capabilities/gaps, and budget summary—never full catalogs or histories. | Token control; Agent Flow |
| 77 | Accepted | Full research checkpoint, source, provisional memory, Skill ledger, and artifacts stay local; the server stores only a compact coordination checkpoint. | Persistence boundary |
| 78 | Accepted | Durable checkpoints occur at meaningful transitions and before long work; frequent progress uses append logs. Resume verifies Git, factor, graph, and RunSpec hashes. | Recovery and database efficiency |
| 79 | Accepted | A missing capability pauses only dependent branches. Independent research continues and the paused branch resumes after a verified capability/Maintenance disposition. | Availability; Agent Flow |
| 80 | Accepted | Goals persist, but LLM Agents do not stay running. Deterministic event/watch/heartbeat logic wakes them only for relevant changes or exceptions. | Token control |
| 81 | Revised by 86 | The runtime-neutral GoalSpec and optional provider adapters remain; detection semantics were later corrected to detect Codex runtime rather than a Goal feature. | Runtime portability |
| 82 | Accepted | Server maintenance uses a zero-token standing monitor plus bounded Maintenance Case Goals, not one endless LLM goal. | Server Maintenance |
| 83 | Accepted | Planning uses a user-owned long-term Workspace Research Objective plus bounded Planning Cycle Goals. | Planning Agent Flow |
| 84 | Accepted | A Research Goal binds one Work Package and completes when it produces an auditable decision, not only when a factor succeeds. | Research Agent Flow |
| 85 | Accepted | Scheduling is event-first with adaptive sparse heartbeat fallback, deterministic hash comparison, coalescing, and no unchanged-state wake. | Token/database control |
| 86 | Accepted | Detect Codex runtime, optionally offer Codex Goal, and fall back seamlessly to lightweight GoalSpec if unavailable or declined. Never hard-code Codex into core semantics. | User correction; runtime portability |
| 87 | Accepted | The Agent drafts a compact Goal from confirmed conversation context; the user accepts, edits, or refuses rather than filling a blank form. | Usability and token control |
| 88 | Accepted | Wake the original Agent ID/dialog where possible; a compatible runtime may claim the same identity without changing scope, history, or permissions. Events are idempotent. | Continuity; Agent Flow |
| 89 | Accepted | Goal transitions, heartbeat, matching, dedupe, and checkpoint checks consume zero LLM tokens. Wakes are compact, budget-reserved, single-Agent by default, and measured. | Hard token acceptance |
| 90 | Accepted | Unchanged heartbeat causes zero writes. SQLite stores low-frequency facts only; progress/artifacts remain outside hot tables; SQL count, WAL, locks, and latency are acceptance metrics. | Database hot path |
| 91 | Accepted | No automatic LLM fan-out. One Research Agent owns a Goal; deterministic jobs may parallelize; specialist reviewers appear only for risk, conflict, or graph/backend change. | Multi-Agent and token control |
| 92 | Accepted | Agent Flow owns identity, goals, work packages, checkpoints, watchers, budgets, Git, and routing. Active Graph owns research-method and evidence transitions. They connect only through compact packets, evidence references, and capability-gap events. | Canonical architecture boundary |
| 93 | Accepted | Version one contains one factor-research Active Graph plus lightweight Planning and Maintenance workflows. Those workflows may become separate graphs only after stable semantic paths emerge. | Scope control |

## Numbered decisions 94 onward

| ID | Disposition | Final decision | Basis and affected boundary |
|---:|---|---|---|
| 94 | Accepted | The user confirms the Workspace Objective and primary factor/family scope. Research autonomously handles auxiliaries inside the package; a new main alpha direction requires a new user-confirmed package. | User authority; Planning |
| 95 | Refined by 118 | Work Packages support `targeted_research` and `open_discovery`. Open discovery lets an Agent create factors within a user-authorized market/data/theme/permission/exclusion scope; operational budget is referenced from Agent Flow rather than owned by the package. | Research authorization |
| 96 | Accepted | Each executable discovery candidate enters the existing graph as an independent hypothesis branch/trial. Invalid mechanism/PIT/data may stop early; backend gaps are not factor failures. | Candidate lifecycle |
| 97 | Accepted | One parameterized `candidate_discovery` handles new primary, auxiliary, primary-for-state, repair/redefinition, and strategy-condition intents. | Graph topology |
| 98 | Accepted | Candidate discovery is a short-circuit node: a targeted existing factor with no search need passes deterministically and consumes no discovery Agent tokens. | Token control |
| 99 | Accepted | Deterministic point-in-time `MarketStateSnapshot` supplies compact market context. Agents may propose new state definitions, but never use future regime labels. | Causal market semantics |
| 100 | Accepted | Discovery proceeds progressively from current package/state/memory to local evidence, data/operators, installed Skill descriptions, then external literature or new Skills only if needed. | Search and token policy |
| 101 | Accepted | Factor evidence statuses are scope-bound: untested, evaluated, supported, contradicted, inconclusive, or superseded in scope. `$Rev` remains separate and no global “valid factor” label exists. | Evidence semantics |
| 102 | Accepted | `supported_in_scope` requires frozen identity/design, PIT timing, trial control, unpolluted OOS, applicable costs/accounting, uncertainty/stability/coverage/counterexamples, JobAttempt terminal assurance, and risk-triggered independent audit. Numeric thresholds remain configurable. | Statistical governance |
| 103 | Revised | Results bind family version plus configuration hash. Old problematic results remain and are classified by whether the issue affects formula attribution, causal validity, accounting/execution validity, or metadata; evidence never transfers silently to a new version. | User correction; evidence retention |
| 104 | Accepted | Formula/schema/FactorParam/default direction/data/timing changes bump semantic family version; parameter values create config hashes; metadata-only edits create metadata revisions. Hash is authoritative. | Versioning |
| 105 | Accepted | Full source, AST, and formula remain local. Server stores opaque hashes, versions, schemas, FactorParam references, and evidence; temporary workers may hash then delete source. | Privacy and identity |
| 106 | Accepted | Server may store experiment role relationships and anonymous integration class, but not operation order, weights, formula, or a reconstructable DAG. | Privacy; research index |
| 107 | Accepted | Planning and Research Agents are client-side and see authorized local factor source. Server Maintenance sees backend/graph source but not user factor source by default. | Permission boundary |
| 108 | Accepted | A client capability gap sends the minimum general operator/strategy contract, types, domains, NaN/timing rules, execution surfaces, examples, and counterexamples—never the user formula or path. | Backend completion protocol |
| 109 | Accepted | Planning presents one recommendation and a few compact alternatives; users modify scope in natural language while internal graph/hash/evidence-reference details remain hidden. | UI/conversation boundary |
| 110 | Clarified by 111 | Research interrupts users only for material scope, permissions/data/source sync, Skill approval, new alpha direction, or budget/preference decisions—not routine trials, jobs, gaps, or memory. | Conversation policy |
| 111 | Accepted | Backend changes route deterministically to a Server Maintenance Agent conversation for audit, implementation, validation, release, and revision/disposition-based Research wake. | Approval routing |
| 112 | Accepted | The factor-research graph ends at research decision and contains discovery, preregistration, local capability resolution, data/semantics, optional enrichment/conformance, validation, diagnostics, backtest, robustness, and result audit. Goal, graph evolution, audit, backend release, and experience generalization stay outside it. | Final graph boundary |
| 113 | Accepted | Capability resolution is node-local. Discovery, enrichment, backtest, and robustness resolve only currently triggered needs; future-node gaps never block the current branch. | Token and correctness |
| 114 | Accepted | Discovery ideas remain local scratch until computation/comparison/outcome inspection begins. Executed ideas must be preregistered and cannot be relabeled as drafts to evade trial counting. | Statistical governance |
| 115 | Accepted | Maintain immutable `attempt_count` and `outcome_examined_count`. Input-quality/computability diagnostics are logged but are not outcome trials; selection-relevant outcome inspection requires a formal trial. Multiplicity uses the count required by its method. | Trial ledger |
| 116 | Accepted | High-risk governance uses a Skill-neutral, document-grounded, one-question-at-a-time audit with persistent decision records. The graph stores the capability description; the local ledger records the actual approved Skill. This log records the present grill and future revisions without becoming runtime context. | `grill-with-docs`; governance and auditability |
| 117 | Accepted | Keep this compact index, recover actual question/response and revision evidence into detailed records, move governance language out of the FactorTester domain context, and correct the documentation in a new commit rather than rewriting history. | `grill-with-docs`; documentation conformance |
| 118 | Accepted after revision | The original combined-budget proposal was withdrawn. Work Package owns user authorization; Factor Research Graph owns trial/stopping/multiplicity and evidence-transition semantics; Agent Flow owns token/compute/time/concurrency/fee enforcement and wait/resume; backend jobs enforce only assigned limits. Work Package may carry references, not those owners' logic. | User correction; canonical three-layer boundary |
| 119 | Accepted | `validation_design` produces a versioned TrialPlan containing the branch-specific statistical design. Active Graph requires and evaluates `trial_plan_ref` evidence but does not hard-code universal IC, Sharpe, sample-size, multiplicity, or stopping thresholds. Outcome-driven plan changes create a new version and trial consequences. | Statistical-design ownership |
| 120 | Accepted | Server persists a compact immutable TrialPlan as the authoritative Run/result binding; local research retains full rationale and private references. Run submission and returned evidence carry the same plan hash. A plan version is written once, while attempts/results append references without hot-path plan rewrites. | TrialPlan persistence and audit |
| 121 | Accepted | Research Agent drafts TrialPlan from hypothesis, product profile, and approved protocol. Deterministic validation is the routine path; one Statistical Reviewer appears only for non-standard, ambiguous, protocol-deviating, or high-risk design, with unchanged review hashes reused. User is asked only for authorization, fee, permission, or irreducible preference changes. | TrialPlan authoring and review |
| 122 | Accepted | TrialPlan freezes statistical interpretation and may coordinate multiple immutable RunSpecs. Every ResearchRun binds one plan hash, one RunSpec hash, one trial role, and one comparison ID; JobAttempts inherit them. An unplanned RunSpec cannot be attached after outcomes without a new plan version and trial effect. | TrialPlan/RunSpec cardinality |
| 123 | Revised by 124 | Originally proposed a persisted JobEvidenceReceipt per attempt and a parent-linked EvidenceEnvelope per transition. The subsequent complexity audit found that these duplicate canonical Job/assurance and graph-trace owners. | Unified evidence contract |
| 124 | Accepted | Preserve JobEvidenceReceipt only as a read projection over existing JobAttempt/artifact/backend-assurance facts, and EvidenceEnvelope only as the validated schema of existing graph-trace evidence. Add no tables, receipt/envelope writes, parent-hash subsystem, or routine reads beyond current-branch canonical rows; reuse the local decision packet and write nothing for unchanged state. | Complexity, token, and database-I/O audit |
| 125 | Accepted with implementation constraint | Store compact TrialPlan once in existing validation-design graph-trace evidence, retain only a current-plan hash projection on the Hypothesis Branch, bind ResearchRun to plan hash/role/comparison, and let JobAttempts inherit. Do not create a TrialPlan table/service or scan trace history in routine submission. Existing persistence objects may be refactored after semantic-owner and read/write-path audit; the design is not limited to patching current tables. | TrialPlan persistence and physical-schema optimization |
| 126 | Accepted | Refactor graph instance into the persisted Work Package projection and graph branch into the Hypothesis Branch owner instead of adding parallel tables. Graph persistence owns research/statistical state only; Agent Flow owns token/compute/time/concurrency/fee budgets, usage aggregation, and wait/resume. ResearchRun owns immutable RunSpec binding, JobAttempt one execution, and graph trace one bounded transition. | Persistence ownership and layer correction |
| 127 | Accepted after revision | UI configures a total token limit per Agent Profile; Agent Flow enforces it under the claimed Agent ID. Persist only compact restart-safe limit/used/reserved/revision state, cache active state, and perform at most one reservation plus one settlement per real model call. Research graph and backend jobs never own or update the budget. | Per-Agent token budget ownership |
| 128 | Accepted | UI displays per-Agent limit/used/reserved/remaining and task-grouped invocation usage, while Agent Flow remains the owner. Settlement appends one compact source-free usage item in its existing transaction. Limit changes retain usage; manual reset opens a new immutable period, preserves history, and waits for an active invocation to settle. No automatic-reset scheduler in v1. | Token usage visibility and reset |
| 129 | Accepted | Insufficient remaining allowance is a derived Agent Flow pause, not graph evidence or a new pause row. Preserve checkpoint, leave graph/hypothesis unchanged, continue backend Jobs, and return provider-neutral `agent_budget_exhausted`. A limit/reset revision produces one deduplicated event-driven wake; no polling or LLM heartbeat. | Budget exhaustion and resume |
| 130 | Accepted | UI settings initially reads only Agent Profile plus current budget aggregate. Task usage loads only on expansion using Agent/period/time cursor pagination and is grouped at read time. Budget events refresh one Agent aggregate; v1 adds no polling, materialized summaries, compactor, or retention scheduler. | Token UI read-path bound |
| 131 | Accepted | Normalize usage through deterministic provider-neutral code. Agent ID remains the budget identity across model/runtime changes; each budget period pins a charging policy. Default charged amount is normalized total input plus output without double-counting cache. Missing actual usage settles from the safe reservation and is labeled fallback, so startup remains seamless. | Cross-runtime token accounting |
| 132 | Accepted | Consolidate execution, reservation, provider usage receipt, and budget persistence into two deep Agent Flow objects: AgentBudgetPeriod and AgentInvocation. Invocation owns provenance, reservation, and settlement. Move them out of the Graph Module, migrate and remove overlapping legacy tables, and do not maintain a dual-write compatibility path. | Agent Flow persistence consolidation |
| 133 | Accepted | Store one bounded fixed-category context-cost breakdown in the existing AgentInvocation settlement: base instructions, conversation, local graph packet, evidence summaries, Skill documents, review material, and output. Record counts/quality only, no content or per-document rows; UI loads it only on invocation expansion. | Token-cost diagnosis |
| 134 | Accepted | Persist usage with the Agent Flow execution owner: local Research Agent usage in the local manager store and Server Agent usage in the server store. UI routes settings and merges views but has no independent accounting database, no browser persistence, and no default local-history sync to server. | Usage persistence placement |
| 135 | Accepted | Context-cost optimization belongs to Agent Flow, not Factor Research Graph or a standing optimizer Agent. Deterministic rules flag single anomalies and deduplicate repeated/threshold breaches into one proposal. Only semantic-preserving cache/config actions are automatic; code, Skill-condition, reviewer-policy, or flow changes enter Maintenance and high-risk grill. | Token telemetry optimization loop |
| 136 | Accepted | Provider-neutral deterministic resume returns a role-specific small packet. Research gets current authorized scope/branch/changed refs/node-local capability hints/next action; Planning and Maintenance get only their bounded pending work. Omit full graph/catalog/history/output, write nothing for unchanged revision, and default profiles to unlimited until UI sets a cap. | Frictionless token-bounded Agent startup |
| 137 | Accepted | Server supplies only capability description/hash. Local manager may add an opaque reuse ref with content/approval/runtime compatibility from local audit state. Matching state avoids rediscovery/download/reapproval; fresh contexts still obey runtime loading rules. First/changed execution requires conversation approval, UI only displays it, and real Skill identity/execution remains local. | Skill-neutral reuse and local audit |
| 138 | Accepted | Keep BackendAssuranceValidator as deterministic terminal validation but store its bounded policy/revision/check/anomaly/hash/disposition data in the existing JobAttempt terminal transaction. Remove the independent assurance receipt owner. Conforming Jobs need no reviewer/read; only concrete anomaly, hash conflict, implausible result, or evidence-backed suspicion opens Maintenance. | Backend trust with no duplicate persistence |
| 139 | Accepted | Preserve an anomalous JobAttempt and derive its evidence ineligibility from assurance plus Maintenance disposition rather than writing branch pause state. Only dependent transitions wait; cases deduplicate by job/policy/anomaly hash. Deterministic evidence comes first, at most one source-authorized Backend Reviewer is conditional, false positives reference old Jobs, and confirmed fixes release a new backend revision and JobAttempt without rewriting history. | Backend anomaly isolation and rerun |
| 140 | Accepted | Use one durable MaintenanceCase object/table for all maintenance kinds. It owns only queue/dedup/claim/current-status and bounded refs to canonical conversation/Job/graph/Git/test owners. Add no per-kind queue or case-event table; update only material state transitions, UI is read-only for approvals/disposition, and resolution wakes affected work once. | Minimal durable maintenance coordination |
| 141 | Accepted after industry review | A: v1 Agent Profiles are owner-pinned; model/runtime changes are seamless, while cross-owner movement uses explicit atomic profile/budget/checkpoint transfer instead of a global per-call broker. B: referenced TrialPlan graph traces are retention-pinned with dependent research history, avoiding a separate store. C: use checkpoint/hash and AuthN/AuthZ for runtime, exact-diff authenticated single-use conversation approval for high-risk effects, and signed attestation only across real software-supply-chain trust boundaries. | Portability, retention, and proportional security threat model |
| 142 | Accepted | Reduce the current 20 Graph-module tables to six Graph owners (`graph_versions`, active pointer, instances/Work Packages, branches/Hypotheses, trace, Maintenance Cases) plus two independent Agent Flow owners (budget periods and invocations). Fold assurance into JobAttempt, current node resolution into branch, governance gates into Maintenance Case, and rollback into an approved active-pointer change. Implement as six independently committed migration batches with query/write/replay gates and no long-lived dual write. | Database-object deletion audit |
| 143 | Accepted through 143.6, then access-refined | Model factor research with scoped Research Claims and extensible Verification Obligations rather than a second cognitive-debt graph or hard-coded checklist. A Research Decision Contract is a versioned Work Package/Hypothesis Branch view. Evidence Envelopes remain factual; one authority-bearing adjudication atomically applies paired Claim/obligation deltas. One progressively loaded local reference Skill implements discover/synthesize/adjudicate/exhaustion/impact while the server remains Skill-neutral. Research pauses through independently challenged bounded closure and selectively reopens on material impact. Reuse existing trace/branch/Maintenance owners; deliver schemas and conformance first, shadow replay second, measured minimal persistence third, and Graph/methodology activation last with token/database regression gates. Legacy envelopes are privileged audit records and are unavailable to Agents; deterministic compatibility sees only bounded version/hash/eligibility metadata and reopened research creates new evidence. | Meng cognitive-debt warning; first-principles research; FactorMAD as bounded design reference; statistical governance; complexity/token/database/privacy audit |
| 144 | Accepted | Split trusted terminal JobAttempt binding from downstream analytical capability resolution. `authoritative_backtest` first enters a capability-free `job_evidence_ready` checkpoint through the existing server-owned binding action. Only then may the branch enter statistical robustness or expose its missing capability. A downstream gap cannot roll back accepted Job facts; the checkpoint adds no database object, statistical claim, reviewer, or bootstrap implementation. Capability-gap closure and recovery remain a separate unresolved grill decision. | Real v5 acceptance found five trusted Jobs but zero accepted graph evidence deltas because target capability validation rolled back the binding transition |
| 145 | Accepted and scope-refined | A downstream capability gap may receive an independently challenged bounded closure with the existing `blocked` disposition; it preserves open obligations and is neither success nor factor rejection. Recovery returns to `job_evidence_ready` without rerunning the Job, unless immutable inputs or evidence became stale. The server derives the recovery origin from the existing latest trace edge rather than storing another resume object. Capability-gap is diagnosis; Skill/data binding and source-authorized backend modification are separate resolution or Maintenance paths. A blocked acceptance run is truthful but cannot set `release_ready=true`. | Human accepted the proposed bounded closure/recovery semantics and asked whether gap completion and backend code update were the same node type |

## Canonical audit boundary after decision 116

```text
ordinary approved research transition
  -> deterministic guard/evidence check
  -> no grill

high-risk graph/statistical/Skill/backend change
  -> compact proposal diff
  -> document and code conflict check
  -> one-question-at-a-time auditor dialogue
  -> append accepted/rejected/revised disposition here
  -> Agent implements or reproposes
  -> replay/shadow/conformance gates
```

The capability description is canonical; `grill-with-docs` is the current
locally selected implementation, not a server-side dependency or graph hash
input.
