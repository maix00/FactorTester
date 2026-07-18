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
- latest accepted question in this revision: `117`
- latest discussed question in this revision: `118` (challenged; unresolved)

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
  affected branches pause at a checkpoint and resume after a receipt.
- Skills are discovered progressively and require approval before first
  execution. The server stores need descriptions, while the local research
  ledger stores actual Skill identity and usage.
- Complete graph, capability catalog, artifacts, source, stdout, and history
  stay behind references. Routine context is a bounded local packet.
- Token budgets are enforced before Agent work, trusted receipts provide
  authoritative usage, and database hot paths must have bounded reads and
  low-frequency writes.
- Backend reliability is presumed from conformance receipts; a specialist
  backend review starts only when evidence creates a concrete reason for doubt.
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
| 58 | Accepted | Exact factor, data, RunSpec, product, cost, and backend receipt matches are reusable. Scope mismatch requires revalidation; model/runtime change alone does not. | Hash identity; evidence reuse |
| 59 | Accepted | Every run writes compact provisional evidence deterministically. A Server Maintenance review wakes only for generalizable gaps, repeated decisions, counterevidence, reusable scope evidence, or changed norms. | Token control; graph evolution |
| 60 | Accepted | A branch pins its graph version. Existing jobs finish under the original version; affected branches migrate only at checkpoints with a migration receipt. | Reproducibility; Agent Flow |
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
| 76 | Accepted | Research starts from a compact packet of identity, scope, node/checkpoint, summaries, references, capabilities/gaps, workspace receipts, and budgets—never full catalogs or histories. | Token control; Agent Flow |
| 77 | Accepted | Full research checkpoint, source, provisional memory, Skill ledger, and artifacts stay local; the server stores only a compact coordination checkpoint. | Persistence boundary |
| 78 | Accepted | Durable checkpoints occur at meaningful transitions and before long work; frequent progress uses append logs. Resume verifies Git, factor, graph, and RunSpec hashes. | Recovery and database efficiency |
| 79 | Accepted | A missing capability pauses only dependent branches. Independent research continues and the paused branch resumes after a verified capability receipt. | Availability; Agent Flow |
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

## Numbered decisions 94–116

| ID | Disposition | Final decision | Basis and affected boundary |
|---:|---|---|---|
| 94 | Accepted | The user confirms the Workspace Objective and primary factor/family scope. Research autonomously handles auxiliaries inside the package; a new main alpha direction requires a new user-confirmed package. | User authority; Planning |
| 95 | Accepted | Work Packages support `targeted_research` and budgeted `open_discovery`. Open discovery lets an Agent create factors within a user-authorized market/data/theme scope. | Research scope |
| 96 | Accepted | Each executable discovery candidate enters the existing graph as an independent hypothesis branch/trial. Invalid mechanism/PIT/data may stop early; backend gaps are not factor failures. | Candidate lifecycle |
| 97 | Accepted | One parameterized `candidate_discovery` handles new primary, auxiliary, primary-for-state, repair/redefinition, and strategy-condition intents. | Graph topology |
| 98 | Accepted | Candidate discovery is a short-circuit node: a targeted existing factor with no search need passes deterministically and consumes no discovery Agent tokens. | Token control |
| 99 | Accepted | Deterministic point-in-time `MarketStateSnapshot` supplies compact market context. Agents may propose new state definitions, but never use future regime labels. | Causal market semantics |
| 100 | Accepted | Discovery proceeds progressively from current package/state/memory to local evidence, data/operators, installed Skill descriptions, then external literature or new Skills only if needed. | Search and token policy |
| 101 | Accepted | Factor evidence statuses are scope-bound: untested, evaluated, supported, contradicted, inconclusive, or superseded in scope. `$Rev` remains separate and no global “valid factor” label exists. | Evidence semantics |
| 102 | Accepted | `supported_in_scope` requires frozen identity/design, PIT timing, trial control, unpolluted OOS, applicable costs/accounting, uncertainty/stability/coverage/counterexamples, backend receipt, and independent audit. Numeric thresholds remain configurable. | Statistical governance |
| 103 | Revised | Results bind family version plus configuration hash. Old problematic results remain and are classified by whether the issue affects formula attribution, causal validity, accounting/execution validity, or metadata; evidence never transfers silently to a new version. | User correction; evidence retention |
| 104 | Accepted | Formula/schema/FactorParam/default direction/data/timing changes bump semantic family version; parameter values create config hashes; metadata-only edits create metadata revisions. Hash is authoritative. | Versioning |
| 105 | Accepted | Full source, AST, and formula remain local. Server stores opaque hashes, versions, schemas, FactorParam references, and evidence; temporary workers may hash then delete source. | Privacy and identity |
| 106 | Accepted | Server may store experiment role relationships and anonymous integration class, but not operation order, weights, formula, or a reconstructable DAG. | Privacy; research index |
| 107 | Accepted | Planning and Research Agents are client-side and see authorized local factor source. Server Maintenance sees backend/graph source but not user factor source by default. | Permission boundary |
| 108 | Accepted | A client capability gap sends the minimum general operator/strategy contract, types, domains, NaN/timing rules, execution surfaces, examples, and counterexamples—never the user formula or path. | Backend completion protocol |
| 109 | Accepted | Planning presents one recommendation and a few compact alternatives; users modify scope in natural language while internal graph/hash/receipt details remain hidden. | UI/conversation boundary |
| 110 | Clarified by 111 | Research interrupts users only for material scope, permissions/data/source sync, Skill approval, new alpha direction, or budget/preference decisions—not routine trials, jobs, gaps, or memory. | Conversation policy |
| 111 | Accepted | Backend changes route deterministically to a Server Maintenance Agent conversation for audit, implementation, validation, release, and receipt-based Research wake. | Approval routing |
| 112 | Accepted | The factor-research graph ends at research decision and contains discovery, preregistration, local capability resolution, data/semantics, optional enrichment/conformance, validation, diagnostics, backtest, robustness, and result audit. Goal, graph evolution, audit, backend release, and experience generalization stay outside it. | Final graph boundary |
| 113 | Accepted | Capability resolution is node-local. Discovery, enrichment, backtest, and robustness resolve only currently triggered needs; future-node gaps never block the current branch. | Token and correctness |
| 114 | Accepted | Discovery ideas remain local scratch until computation/comparison/outcome inspection begins. Executed ideas must be preregistered and cannot be relabeled as drafts to evade trial counting. | Statistical governance |
| 115 | Accepted | Maintain immutable `attempt_count` and `outcome_examined_count`. Input-quality/computability diagnostics are logged but are not outcome trials; selection-relevant outcome inspection requires a formal trial. Multiplicity uses the count required by its method. | Trial ledger |
| 116 | Accepted | High-risk governance uses a Skill-neutral, document-grounded, one-question-at-a-time audit with persistent decision records. The graph stores the capability description; the local ledger records the actual approved Skill. This log records the present grill and future revisions without becoming runtime context. | `grill-with-docs`; governance and auditability |
| 117 | Accepted | Keep this compact index, recover actual question/response and revision evidence into detailed records, move governance language out of the FactorTester domain context, and correct the documentation in a new commit rather than rewriting history. | `grill-with-docs`; documentation conformance |
| 118 | Challenged; unresolved | The original proposal incorrectly mixed Work Package authorization, Active Graph statistical stopping semantics, and Agent Flow operational budgets. It is withdrawn pending a narrower boundary decision. | User correction; Work Package/Graph/Agent Flow boundary |

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
