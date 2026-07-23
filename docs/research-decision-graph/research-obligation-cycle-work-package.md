# Research Obligation Cycle Implementation Work Package

Status: implementation in progress. The original Grill 143 Batches 0–5 are
complete, but the former “Batch 6 next” handoff is superseded by the narrower
canonical sequence in Grill 179.48–179.50. Remaining gates include the final
obligation catalog/resolvers, report-coverage enforcement, lifecycle cleanup,
historical-time backfill, v1–v3 restoration, and real-factor shadow acceptance.

Baseline: `56d36913` on `fix/issue-140-active-graph-agentflow`.

This package follows the completed issue-140 cutover. It must not rewrite,
squash, or retroactively amend the six issue-140 migration batches. Every batch
below is independently testable, committed after its gates pass, and
revertible without requiring a long-lived dual-write path.

## Outcome

Add a token-bounded, first-principles Research Obligation Cycle that:

- derives scoped Research Claims and Verification Obligations from the current
  Decision Contract and accepted evidence state;
- selects actionable obligations for TrialPlan synthesis;
- keeps Evidence Envelopes factual;
- proposes paired Claim-evidence and obligation changes;
- admits those changes only through one authority-bearing atomic decision;
- pauses research through bounded, independently challenged search exhaustion;
- selectively reopens affected research when evidence or methodology changes;
- uses the real FactorTester/Research Graph backend through the existing
  CLI-Anything Harness rather than reimplementing research computation.

## Non-goals

- no second Active Graph, knowledge graph, or cognitive-debt graph;
- no universal obligation checklist;
- no global IC, Sharpe, p-value, or configuration threshold for completion;
- no Claim, obligation, adjudication, Evidence Envelope, TrialPlan, or closure
  service/table;
- no server persistence of concrete Skill identity, body, provider, or path;
- no LLM reviewer on routine transitions;
- no whole-Graph, whole-catalog, whole-trace, or artifact-body Agent context;
- no eager rewrite of legacy evidence;
- no implementation of deferred multi-factor portfolio semantics.

## Existing owner map

| Concern | Canonical owner |
|---|---|
| user research authorization | Agent Flow Work Package |
| current research/statistical state | Hypothesis Branch |
| immutable bounded history | existing Research Graph trace |
| execution truth | ResearchRun, JobAttempt, artifacts, backend assurance |
| statistical design | TrialPlan in validation-design trace plus branch hash |
| lifecycle and capability need | versioned Factor Research Graph |
| methodology/backend/Graph change | Maintenance Case |
| actual Skill load, reuse, approval, invocation | local Harness audit |

The Research Decision Contract is a normalized view over the first two owners,
not a ninth persistence object.

## Grill 179 implementation audit (2026-07-23)

This is the execution checklist for the closed semantic grill. It prevents a
draft manifest or UI projection from being mistaken for an enforced runtime
contract. A checked item requires code, deterministic validation, CLI parity,
and the named acceptance evidence; documentation alone is not completion.

| Accepted contract | Current state | Remaining release gate |
|---|---|---|
| canonical Work Package lifecycle owner | implemented; production owner table explicitly backfilled 17/17 after backup and integrity check | exact-manifest purge/orphan cleanup, read-path benchmark, UI acceptance |
| seven semantic obligation categories plus `other` | successor v9 catalog aligned; 60 subcategories; not activated | activation validator must prove every subcategory has a real resolver and report contract |
| local current-anchor context under 6000 bytes | implemented for successor requirement inspection; 13-item validation-design packet is 5605 bytes | enforce the same bound on real server `next/context` after v9 publication |
| provider-neutral resolver for every active subcategory | descriptor and output schema exist only | implement category resolver packages and factual CLI operations; descriptors cannot satisfy the gate |
| methods as TrialPlan Evidence Actions and Evidence admission | protocol and transition components implemented | full successor-graph path acceptance and actual capability bindings |
| report requirement per node/edge/gate | v9 transition rejects missing requirement/subject bindings; local narrative v3 rehashes every Chinese item while keeping body local; formulas, frozen run configuration and hash-verified local figures now have bounded report projections | add pre-transition CLI preparation, current-anchor packet acceptance and complete FTClient bound-item presentation |
| user acceptance objective/criteria | not implemented as a first-class Contract projection | add bounded objective revision, criterion evaluation and no-silent-closure gate without a new owner table |
| explicit Graph continuation and re-entry | deterministic preflight/frame implemented | rerun against final catalog/topology and show itemized report coverage |
| `end_session_skip=False` default | implemented across factor family, signal align and runtime fallbacks | keep explicit-True comparison regression and strategy-obligation reporting in end-to-end acceptance |
| Graph history and obligation/report browser | server version storage exists | restore exact v1-v3, add bounded FTClient read-only version/topology/catalog/report views |
| historical Agent-conversation report registration | pure one-read historical Carrier GET, checkpoint/report-item timing v3, root-to-current-HEAD local stage/finalize CLI and FTClient dual-time display implemented; replay is idempotent and Graph/Profile/Work Package semantic heads/timestamps stay fixed | add exact-manifest archive/rebuild for a pre-existing invalid derived journal, explicit legacy-root and complete-record invariance tests, and an independent current-HEAD comparison; then exercise the flow against the real `MaxA (2)` conversation and current production Work Package |
| lifecycle cleanup | archive/delete/restore implemented | add retention-aware purge dry-run/apply, orphan checks, exact refs and integrity acceptance |
| real research proof | not complete and blocked on the unfinished issue-143 margin-accounting correction | after issue-143 is complete, merge it into the issue-141 baseline and verify the real margin runtime path; then rerun every relevant `MaxA (2)` Trial under new Job/Run/Evidence identities before recovering the Chinese itemized report. Old results remain immutable historical references but cannot support the final comparison. Continue the test research on v9 without creating another Work Package, complete the planning/research-agent shadow path and a trend family, and bind the rerun result tables plus necessary content-addressed equity/monotonicity images into the report |

The successor remains a draft until every activation-relevant row above is
complete. Existing production research stays pinned to its original Graph
unless the user explicitly requests a continuation and deterministic preflight
accepts it.

### Post-grill completion audit (2026-07-23)

Grills 177, 178 and 179 contain no unanswered semantic question. Their status
is closed. The remaining work is implementation and release acceptance, not
another open-ended design interview:

1. the active server Graph is still v8; the immutable server history contains
   v4–v8 only, so exact v1–v3 restoration and v9 publication have not happened;
2. the successor v9 catalog is a draft implementation surface: category
   descriptors exist, but every active subcategory still needs a factual
   provider-neutral resolver, CLI action, report contract and activation proof;
3. user acceptance objectives and criteria are not yet a first-class bounded
   Contract projection and therefore cannot prevent silent closure;
4. the private progressively loaded Server Maintenance Skill accepted in
   Grill 178.2 is now packaged under `server/skills/server-maintenance/`;
   its Graph, backend and database references exist, but that completion does
   not satisfy the separate resolver, lifecycle or release gates;
5. continuation, Evidence admission and report coverage have protocol tests,
   but still need final-catalog end-to-end validation, a real under-6000-byte
   current-anchor packet and complete FTClient bound-item presentation;
6. canonical Work Package lifecycle is implemented, while retention-aware
   exact-manifest purge, orphan/reference checks, database statement
   benchmarks and UI acceptance remain open;
7. historical backfill fails closed on broken lineage, but lacks the explicit
   archive/rebuild maintenance operation and the complete invariance/current
   HEAD tests required before applying it to `MaxA (2)`;
8. public-client clean-machine installation, repository confidentiality split,
   stable `main` release, download/reinstall/rollback and remote cleanup gates
   remain release work outside the semantic Graph runtime;
9. issue-143 is not complete. The current issue-141 worktree nevertheless
   contains merge commit `fef5b000`, which integrates the unfinished
   issue-143 branch. This is not acceptance evidence: final historical
   recovery and research reruns remain forbidden until margin semantics are
   independently verified on the production runtime path.

These gates retain the canonical implementation order: finish provider-neutral
contracts and resolvers; publish and validate v9; restore history and lifecycle
maintenance; wait for and integrate issue-143; rerun and recover `MaxA (2)`;
then perform public-client release acceptance. Each independently reversible
batch is tested and committed before the next.

## Full proposal implementation audit (2026-07-23)

This audit reread the detailed proposal, its user correction, later
supersession and current production path for every numbered Grill decision.
It does not infer completion from an `Accepted` or `closed` label.

Status codes:

- **C** — the final semantics are implemented on the current runtime path and
  have focused deterministic tests;
- **P** — meaningful implementation exists, but one or more promised owners,
  surfaces, integrations or acceptance tests are missing;
- **D** — the result is still chiefly a documented protocol or draft;
- **S** — the proposal was explicitly superseded, withdrawn or is an
  operating rule rather than a feature;
- **X** — current code or records contradict the final accepted semantics;
- **B** — final acceptance is blocked by the unfinished issue-143 accounting
  work even if local components exist.

The read-only production check found `factor-research@v8` active and only
versions v4–v8 stored. The successor v9 is not published. Therefore a v9
schema or unit test is never counted as current production completion.

### Grill 48–76

| ID | Status | Detailed commitment checked and current result |
|---:|:---:|---|
| 48 | P | Maintenance Case and exact gap/recovery gates exist; mandatory platform-work-to-release-receipt-to-single-wake is not closed. |
| 49 | P | New-lineage and holdout guards exist; there is no end-to-end proof that post-result enrichment cannot consume an exposed confirmation sample. |
| 50 | D | No Provisional Memory repetition/industry-rule threshold promotes a path proposal; replay, shadow and audit infrastructure alone do not implement it. |
| 51 | D | No bounded mechanism-ranked conditioning-candidate generator or ablation scheduler exists. |
| 52 | P | Factor/strategy roles can express part of the distinction; the required main-only, interaction, stability and cost ablation flow is absent. |
| 53 | D | No four-tier, scope-aware candidate eligibility projection or ranking surface exists. |
| 54 | C | `$Rev` is handled as configuration-level direction negation, not evidence or a component factor. |
| 55 | D | Hard exclusions versus soft ranking are guidance, not an enforced candidate resolver contract. |
| 56 | D | Candidate-discovery exit has no enforced broader-search-or-reason report field. |
| 57 | D | No point-in-time `MarketStateSnapshot` owner or open state-definition registry exists. |
| 58 | P/B | Exact factor/RunSpec/Trial/Job identity checks and evidence reuse exist; accounting-change impact and required real reruns remain incomplete and blocked. |
| 59 | P | Maintenance routing exists; deterministic generalization triggers over provisional experience do not. |
| 60 | C | Branch Graph pinning, immutable continuation, same-node re-entry and preservation of running work are implemented and tested. |
| 61 | P | Composition and structural identity exist; no resolver proves that a composed implementation exactly satisfies a missing semantic capability. |
| 62 | P | `FactorParam` and source-free revision manifests exist; semantic version allocation, classification and full lineage do not. |
| 63 | S | The aligned-signal/raw-expression dual-mode proposal was superseded by 65. |
| 64 | S | Shared aligned/raw DAG semantics were moved to strategy/execution by 65. |
| 65 | P | Raw `FactorParam` composition and final family alignment exist; serialized nested resolution and execution-sharing acceptance are incomplete. |
| 66 | P | Strategy roles and RunSpec hashes distinguish configurations; there is no canonical factor versus factor-plus-strategy evidence-class contract. |
| 67 | X | Required `FactorExpr.tanh()` and public typed `where` are absent; raw nesting lacks the full promised version/timing/incremental acceptance. |
| 68 | S | The nested one-operator directory proposal was withdrawn by 72. |
| 69 | P | Workspace/Pyright checks exist, but the full operator import/catalog/hash/LaTeX/batch/incremental snapshot suite does not. |
| 70 | P | Planning receives a compact scope packet, but recommendation, user confirmation and enforced Research scope escalation are not a complete flow. |
| 71 | P | External factors can be marked experimental; ordinary local post-run source-free registration with role, result and failure evidence is not unified. |
| 72 | X | `WhereOp` is defined in both `conditional.py` and `composite.py`, violating the accepted sole-owner contract; typed SDK `where` is also absent. |
| 73 | P | Profile worktrees isolate Agents and hashes support reuse; sibling similarity and logical-duplicate consolidation are missing. |
| 74 | P | Source authorization boundaries exist; immutable `FactorRef@commit` import plus lineage receipt is missing. |
| 75 | D | Research-completion-to-Planning recommendation and user reprioritization are not implemented. |
| 76 | P | Role-specific packets are bounded; the complete promised candidate, market, Pyright and backend-receipt contents are not present. |

### Grill 77–113

| ID | Status | Detailed commitment checked and current result |
|---:|:---:|---|
| 77 | X | The final Research Cycle checkpoint is canonical in server trace, contrary to the older “full checkpoint stays local” wording; Grill 143 refined the model but 77 was never marked superseded. |
| 78 | P | Graph/Trial/Run hashes and durable transitions exist; the full local append-log cadence and resume verification contract is incomplete. |
| 79 | P | Only dependent branches pause and gap recovery exists; event-driven verified auto-resume is missing. |
| 80 | D | No persistent GoalSpec/event watcher exists; an SSE heartbeat is not this feature. |
| 81 | D | Provider-neutral GoalSpec and provider adapters are absent. |
| 82 | P | Maintenance Cases and the Maintenance Skill exist; the zero-token Standing Monitor/Goal does not. |
| 83 | D | Workspace Research Objective and bounded Planning Cycle Goal do not exist as contracts. |
| 84 | D | No Work-Package-bound Research Goal state machine exists. |
| 85 | D | No event-first Agent watcher with sparse heartbeat fallback exists. |
| 86 | D | No runtime-neutral Codex detection/optional Goal adapter/fallback flow exists. |
| 87 | D | No compact Goal drafting and accept/edit/refuse flow exists. |
| 88 | P | Stable Agent ID and invocation telemetry exist; original-dialog wake and event-hash deduplication do not. |
| 89 | P | Packet budgets, reservations and token comparison exist; Goal/wake dedupe and full with-Graph versus without-Graph acceptance do not. |
| 90 | P | Some unchanged reads and duplicate Maintenance actions are zero-write and statement-tested; no complete watcher WAL/lock/latency benchmark exists. |
| 91 | P | Risk levels suppress routine reviewers in packet policy; no complete execution orchestrator/review-hash reuse path exists. |
| 92 | C | Agent Flow, Active Graph and Maintenance ownership are separated and exchange bounded references. |
| 93 | C | There is one factor-research Graph; Planning and Maintenance remain lightweight non-Graph workflows. |
| 94 | P | Planning exposes scope fields, but recommendation, human confirmation receipt and new-primary escalation are incomplete. |
| 95 | D | `targeted_research` and `open_discovery` modes have no runtime schema or CLI. |
| 96 | D | Capability gaps are separated from factor rejection, but discovery-candidate-to-independent-branch/trial lifecycle is absent. |
| 97 | S | The standalone candidate-discovery node was absorbed by later hypothesis/factor-improvement topology. |
| 98 | D | No deterministic exact-candidate short circuit or candidate-search cache exists. |
| 99 | D | No `MarketStateSnapshot` implementation exists. |
| 100 | P | Skill loading is progressive; the full candidate search ladder, stopping evidence and broader-search report are absent. |
| 101 | S/C | Grill 143 replaced the original factor-status vocabulary with scoped Research Claims; the refined Claim protocol is implemented. |
| 102 | P/B | Claim, Trial and catalog objects can express the criteria; product-specific thresholding and real post-margin acceptance remain incomplete. |
| 103 | P | Results preserve immutable identities; there is no complete defect-impact classifier or UI classification. |
| 104 | D | No semantic-version allocator, deterministic change classifier or metadata-revision workflow implements the accepted matrix. |
| 105 | P | Server manifests are source-free; semantic version allocation and temporary-source deletion receipts are incomplete. |
| 106 | P | Formula/DAG leakage is avoided; the promised anonymous integration relationship contract is not complete. |
| 107 | P | Local Profile source and private server maintenance are separated by convention and Skill; end-to-end technical access enforcement is incomplete. |
| 108 | P | Capability descriptions and hashes exist; the full source-free capability-gap contract with domains, timing and counterexamples is not enforced. |
| 109 | D | Planning does not yet generate one recommendation plus bounded alternatives, cost, gaps and completion criteria. |
| 110 | D | No deterministic interruption-decision contract enforces the agreed user-contact boundary. |
| 111 | P | Maintenance Case, Gate, role packet and private Skill exist; release-receipt-to-single-research-wake is incomplete. |
| 112 | S | The original method-heavy topology is superseded by the successor stable-state topology. |
| 113 | C | Current-node and triggered-condition capability resolution is implemented; future-node gaps do not block the current branch. |

### Grill 114–143

| ID | Status | Detailed commitment checked and current result |
|---:|:---:|---|
| 114 | D | Scratch-versus-executed candidate preregistration is not enforced because candidate discovery modes are absent. |
| 115 | D | Immutable `attempt_count` and `outcome_examined_count` do not exist. |
| 116 | P/X | Skill-neutral descriptions and a local use ledger exist; the full description-search-to-approval-to-execution audit loop is unproven, and the canonical Research Obligation Skill currently differs from its packaged CLI copy. |
| 117 | P | Detailed records were reconstructed; the compact index was stale at 142 and is corrected by this audit. |
| 118 | P | Work Package, Graph and Agent Flow authority boundaries are substantially implemented, but later lifecycle work superseded parts of the original object-count wording. |
| 119 | C | TrialPlan is versioned, branch-specific and required by Run/result binding without universal metric thresholds. |
| 120 | C | Compact immutable TrialPlan identity, hash, role, comparison and evidence-action binding are implemented. |
| 121 | P | Deterministic validation exists; conditional Statistical Reviewer invocation/reuse is not a complete runtime path. |
| 122 | C | TrialPlan-to-ResearchRun-to-Job/Evidence binding is implemented and tested. |
| 123 | S | The independent JobEvidenceReceipt/EvidenceEnvelope persistence proposal was withdrawn by 124. |
| 124 | C | Evidence is projected from JobAttempt/artifact/assurance and stored in existing trace; no duplicate receipt owner was added. |
| 125 | P | TrialPlan v5, Evidence Actions and checkpoints exist; full production research acceptance is pending. |
| 126 | P | Owner boundaries and replay are implemented, but the full obligation cycle is not closed. |
| 127 | P | Server/CLI per-Agent token limits work; FTClient cannot configure them. |
| 128 | P | Configure/reset/reserve/settle work; FTClient lacks task usage, remaining budget and reset UI. |
| 129 | P | Atomic reservation and exhaustion behavior exist; low-cost event wake after budget revision is incomplete. |
| 130 | D/P | Bounded backend reads exist; the promised lazy task-usage UI does not. |
| 131 | C | Provider-neutral actual/fallback/cache-aware accounting and charging policy are implemented. |
| 132 | C | AgentBudgetPeriod and AgentInvocation are the two Agent Flow owners. |
| 133 | P | Bounded context-cost categories are persisted; FTClient invocation detail does not display them. |
| 134 | P | Server/local ownership policy exists; FTClient lacks the local usage store and merged view. |
| 135 | D/P | Telemetry exists; deterministic anomaly deduplication and optimization-proposal flow do not. |
| 136 | C | Provider-neutral role-specific small resume packets are implemented. |
| 137 | P | Capability descriptions and local Skill ledger exist; complete compatible-content reuse without rediscovery is not proven. |
| 138 | C | Deterministic terminal assurance is embedded in JobAttempt and reviewer escalation is anomaly-only. |
| 139 | C | Anomalous attempts remain immutable and Maintenance disposition controls eligibility without branch pause writes. |
| 140 | P | One MaintenanceCase table supports dedupe/claim/status/Gates; exact affected-research wake is incomplete. |
| 141 | P | Retention and exact-hash trust are substantially implemented; complete atomic cross-owner Profile/budget/checkpoint transfer is not. |
| 142 | S/P | The old six-Graph-owner count was superseded by canonical Work Package lifecycle; Agent Flow still retains its two owners. |
| 143 | P/X/B | Core Claim/Obligation/Evidence/Adjudication/closure protocols and Skill exist; real resolvers, user objectives, v9, history recovery and shadow research remain incomplete, and the canonical/packaged Skill copies have drifted. |

### Grill 144–176

| ID | Status | Detailed commitment checked and current result |
|---:|:---:|---|
| 144 | C/S | The v8 `job_evidence_ready` separation was implemented and tested; successor v9 intentionally replaces that method-heavy topology. |
| 145 | C/S | v8 blocked closure and recovery without a new resume object were implemented; successor topology later refines the path. |
| 146 | C | Immutable exact-hash cross-version continuation is implemented. |
| 147 | P | Major/sidebar/settings layout exists; localization and final visual-state acceptance are incomplete. |
| 148 | P | Profile factor worktree and `research/` roots are separated; one-time removal of every obsolete layout is not fully proven. |
| 149 | P | Work Package/branch journals and reports exist; historical continuity and complete MaxA reconstruction remain incomplete. |
| 150 | P | Server availability, bundles and Tiger support exist; end-to-end source ownership and UI management remain incomplete. |
| 151 | X | FTClient has no Data Sources major shortcut/page despite the accepted requirement. |
| 152 | P/X | Local Profile/worktree creation exists, but not the promised server-reserved atomic initialization; metadata-only state can still be presented too optimistically. |
| 153 | D/P | No stable CLI business-action ID manifest proves parity for every FTClient mutation/query. |
| 154 | P/X | Work Packages open as research views, but Profile screens still embed a full research view instead of the intended compact attribution/navigation boundary. |
| 155 | P | Profile handoff, trace and UI projection exist; full report/checkpoint acceptance remains. |
| 156 | D/P | Profile hard-delete fails closed; complete archive/restore/delete-plan lifecycle is not implemented. |
| 157 | X | Factor Library is still an embedded server Web page, not the accepted native CLI-backed Local/Server aggregate. |
| 158 | D/P | No complete Git-like factor lineage navigator and composable filter system exists. |
| 159 | D/P | Category/tag overlays and classification provenance are incomplete. |
| 160 | D | Identity/classification adjudication and full version/parameter/applicability/evidence navigation are absent. |
| 161 | D | Exact-hash Draft promotion through Agent approval and CLI integration is absent. |
| 162 | P | Chinese structured reports, obligations, formulas, figures and coverage exist; full MaxA history and visual/E2E acceptance remain open. |
| 163 | P | FTClient does not edit source, as required; recommended values/descriptions/classification/sync surfaces are incomplete. |
| 164 | D | Version-scoped device-local recommended research defaults are not implemented. |
| 165 | S/P | One Work Package aggregates branches, but the later canonical lifecycle added a table contrary to the earlier no-new-object wording; the later decision supersedes it. |
| 166 | D/P | Server-authoritative Profile archive/delete plan and clean-worktree release are incomplete. |
| 167 | P | Git worktrees and shared canonical workspace exist; semantic promotion/version lineage is incomplete. |
| 168 | X | FTClient has no agreed local SQLite owner for preferences, outbox and bounded caches. |
| 169 | D/P | Local staging is recoverable; server reservation-to-local-verify-to-activation is not an atomic two-phase Profile flow. |
| 170 | D | Metadata-only, persistent private source sync and one-Run transient upload modes are absent. |
| 171 | X | No generated stable action manifest and shared UI/CLI conformance vectors exist. |
| 172 | P | The principal/Profile layout is largely unified; proof that no old root can be recreated or referenced remains incomplete. |
| 173 | D | User canonical-version and Profile Draft sync behavior depends on unimplemented promotion/source-sync capabilities. |
| 174 | S/C | The CRDT/event-table proposal was explicitly rejected and correctly not implemented. |
| 175 | D | Device-local shared recommended parameters are absent. |
| 176 | S | This is an operating rule for first-principles/Occam decisions, not a runtime feature. |

### Grill 177 detailed proposals

| ID | Status | Detailed commitment checked and current result |
|---:|:---:|---|
| 177.1 | P | Deterministic expression facts are separated from Agent-created obligations in the Skill and protocol; the real SgCCS-to-SgCPS research adjudication is not complete. |
| 177.2 | C | Fixed `ColumnRef` discovery reuses the validated expression and emits a source-free bounded summary. |
| 177.3 | C/P | Existing `custom_factors describe --json` returns `column_refs` without a new object/command; some manifest paths sort the result instead of preserving first appearance for every factor. |
| 177.4 | C/P | The existing obligation-discovery Skill instructs semantic, unit, direction, timing and parameterization review; end-to-end Graph acceptance remains pending. |
| 177.5 | P | Local source-first and explicit authorized `--source-code` loading exist; complete cross-owner source-visibility acceptance is not proven. |
| 177.6 | C | `factor_semantics` has a reviewed recovery edge to `factor_improvement_required` without a new node or table. |
| 177.7 | D/P | Work Package candidate scope versus branch execution scope is documented, but derived-family scope/lineage and multiplicity behavior are not a complete runtime contract. |
| 177.8 | D/P | SgCPS local proposals describe strict-generalization migration and paired equivalence; no canonical focus-migration service or accepted numerical equivalence exists. |
| 177.9 | C | The bounded `validation_design` recovery edge exists and does not require a fabricated TrialPlan. |
| 177.10 | D/P | Old Job/Evidence preservation exists generally; exact special-case Claim-scope migration with inherited exposure/ledger is not implemented. |

The detailed record previously used `SgCCSParam` after the family had been
renamed. This audit corrects the canonical name to `SgCPS` while retaining the
initial name as historical provenance.

### Grill 178 detailed proposals

| ID | Status | Detailed commitment checked and current result |
|---:|:---:|---|
| 178.1 | C | Publish, activate and explicit branch continuation are separate CLI/server operations; continuation does not rerun ordinary research stages. |
| 178.2 | C | A private progressively loaded Server Maintenance Skill is packaged with bounded Graph/backend/database references and validation tests. |
| 178.3 | C | Existing production branches remain pinned; explicit continuation preserves the same current node and derives a node-attached re-entry frame. |
| 178.4 | C | The server computes cumulative source-to-target change and topology impact in one deterministic preflight rather than invoking an Agent per version. |
| 178.5 | P | Successor v9 contains a Change Manifest and hashes; it is still a draft and has not passed publication/activation acceptance. |
| 178.6 | P | Category/subcategory/concrete-obligation separation exists in the successor catalog and Research Cycle; current production v8 does not enforce the final catalog. |
| 178.7 | P | Entry coverage decisions, reuse receipts and `other` exist in pieces; full migration reclassification and semantic matching are incomplete. |
| 178.8 | P | Continuation emits a system trace and re-entry frame; exact evidence qualification and complete Chinese report projection need final v9 acceptance. |
| 178.9 | P | Evidence qualification is scoped, but the full `Research Claim × changed Entry Requirement` eligibility relation is not implemented end to end. |
| 178.10 | P | TrialPlan and closure can represent blocked work; no complete runtime guarantee creates the next informative Trial whenever a test entry is blocked. |
| 178.11 | P | Versioned Report Methods and per-anchor requirements exist in successor v9; active v8 does not require them. |
| 178.12 | P | Transition report coverage is enforced for declaring graphs and FTClient renders bound items; pre-transition preparation, complete UI and production v9 are pending. |
| 178.13 | P | Historical stage/finalize backfill is fail-closed and idempotent; exact invalid-journal archive/rebuild, legacy-root and complete invariance/HEAD tests remain. |
| 178.14 | C/P | Successor report requirements bind real requirement subcategories and no fake report obligation is created; final production/UI acceptance is pending. |
| 178.15 | C/P | The successor uses category `data` and node `data_contract`; real provider resolvers are incomplete. |
| 178.16 | P | The catalog contains Chinese questions, selection/evidence/insufficiency/basis/report metadata; real resolver behavior and Agent applicability decisions are not enforced. |
| 178.17 | D/X | FTClient has no Graph version browser, and server history still contains only v4–v8; v1–v3 are not restored. |

### Grill 179.1–179.25

| ID | Status | Detailed commitment checked and current result |
|---:|:---:|---|
| 179.1 | S | `research_intent` as an obligation category was later removed by 179.16 and retained only in the Decision Contract. |
| 179.2 | P | Family/instance/derived-family distinctions inform manifests and catalog text; full identity/classification/lineage adjudication is incomplete. |
| 179.3 | S/P | The name and contents were refined into `trial_design_validity`; TrialPlan v5 implements part of the final contract. |
| 179.4 | P | Methods are Evidence Actions rather than stable obligation IDs in v9, but factual statistical resolvers are missing. |
| 179.5 | P/B | Strategy and external market/accounting categories are separate in v9; schedule/accounting resolvers and verified issue-143 behavior are incomplete. |
| 179.6 | S/C | This category proposal was refined into the Evidence Qualification/Admission Gate, whose core deterministic protocol is implemented. |
| 179.7 | P | Research Cycle adjudicates scoped Claims and next actions rather than “factor pass”; user objectives and real v9 closure acceptance are missing. |
| 179.8 | S/C | Capability was later removed from the obligation catalog; successor coordination nodes and Maintenance ownership reflect the correction. |
| 179.9 | P/X | One MaintenanceCase owner exists, but it stores bounded refs and `latest_result_ref`, not the promised typed `result_json/result_hash` task result contract. |
| 179.10 | P | `other.unclassified_material_question` exists in v9; local searchable temporary obligations and complete audit/UI behavior are absent. |
| 179.11 | D | No complete `catalog_change_proposal` Maintenance Case adapter and review/publication flow exists. |
| 179.12 | D/P | Entry gates compact ordinary requirements; no full related-`other` obligation index and mandatory review path exists. |
| 179.13 | P | EntryResolutionFrame and capability/data detours exist; `other` first-action classification and exact return behavior are incomplete. |
| 179.14 | S/P | The intermediate category list was repeatedly refined; only the final seven-plus-`other` v9 draft should be implemented. |
| 179.15 | D/X | Catalog fields declare resolver capabilities and CLI templates, but templates call `requirement-detail`, which reads descriptions rather than resolving facts; activation hard constraint is unmet. |
| 179.16 | P | Final `hypothesis_validity` questions are in the catalog; Decision Contract initialization and factual mechanism resolver are missing. |
| 179.17 | D/P | Industry evidence and product-neutral principles are documented; product/region/venue/effective-date profiles and resolvers are incomplete. |
| 179.18 | D/P | Catalog text acts as a guide, but runtime does not force the Agent to make a reasoned applicability decision for every triggered subcategory. |
| 179.19 | D | No enforced per-subcategory `obligation_discovery_decision`, first-resolution action and first-Trial selection contract exists. |
| 179.20 | D/P | The Skill instructs open-ended first-principles discovery; Trial feasibility over real data/capabilities is not a complete admission gate. |
| 179.21 | C/P | Capability is outside the obligation catalog and has separate Binding/Gap/Maintenance routing; end-to-end resolver coverage is incomplete. |
| 179.22 | C/P | Evidence Qualification is a system gate, not an obligation category; final v9/report acceptance remains. |
| 179.23 | C/P | EvidenceAdmissionGate and TrialPlan Evidence Action binding are implemented and tested; the active v8 path does not use the final successor topology. |
| 179.24 | P | Compact requirement detail and exact reuse helpers exist; the CLI cannot yet run every real resolver or return the complete minimal decision packet. |
| 179.25 | P | Exact Evidence Action reuse exists; cross-Work-Package obligation-adjudication reuse under requirement revisions is incomplete. |

### Grill 179.26–179.50

| ID | Status | Detailed commitment checked and current result |
|---:|:---:|---|
| 179.26 | D/P | CLI measurement/snapshot/projection identity is documented; resolver modules and uniformly qualified Evidence outputs do not exist. |
| 179.27 | D | Catalog descriptors do not declare the required freshness policy, invalidation keys or refresh cost for each resolver. |
| 179.28 | D/P | Six statistical questions are catalogued; Bootstrap/DSR/PBO and other factual resolver capabilities remain largely absent. |
| 179.29 | P | Capability-gap routing and deterministic equity-curve SVG/receipt generation exist; missing statistical/backend capabilities and full report admission remain. |
| 179.30 | P | Current Jobs preserve a bounded curve artifact and do not persist full point sequences; historical exact-recovery/reproducibility orchestration is incomplete. |
| 179.31 | P/X | A provider-neutral availability service, local bundle inspection and Tiger connector exist; it does not resolve all `data.*` subcategories or UI ownership, and its two-stage field-check guidance exists only in the packaged Skill copy. |
| 179.32 | X | `DataFreq` itself remains temporal, but Tiger availability writes `"frequency": "L2"` instead of orthogonal `sampling_mode/frequency/market_depth`, directly violating the accepted contract. |
| 179.33 | P | Revision identity, `column_refs`, tree and LaTeX support exist; unified Chinese semantic/unit/domain/timing resolvers are incomplete. |
| 179.34 | P | The Agent can inspect expression structure, but stable paths, units, scale, timing/lookback and parameterization-delta verification are incomplete. |
| 179.35 | P | TrialPlan v5 adds primary action/comparison/checkpoint semantics; several design matrices and resolvers remain artifact-level plans rather than implemented facts. |
| 179.36 | D/P | Hypothesis questions and Skill guidance exist; no factual, source-bound mechanism-chain resolver or enforced report answer exists. |
| 179.37 | P | Industry sources are indexed and embedded as catalog refs; report items do not consistently prove which source/principle was actually applied. |
| 179.38 | P/B | Schedule diagnostics, strategy-intent and margin/accounting code exist; unified resolver/report projection and independent issue-143 verification are incomplete. |
| 179.39 | D | `UserAcceptanceObligation` is not implemented as a first-class Decision Contract projection. |
| 179.40 | D | User objective criteria do not yet gate Planning, Trial results, closure and reopening across the existing Graph. |
| 179.41 | P | Successor v9 removes fixed IC/bootstrap nodes and moves methods into Evidence Actions; it is not published or accepted on real research. |
| 179.42 | S | The proposal to add a skip edge to the old topology was withdrawn and correctly must not be implemented. |
| 179.43 | S | This was a point-in-time production inventory used to decide compatibility, not a new runtime feature. |
| 179.44 | P | Work Packages support active/archive/recently-deleted/restore; retention-aware exact purge and full UI acceptance are missing. |
| 179.45 | P | The stable-state successor topology is built as v9 draft; production remains on v8. |
| 179.45a | P | Capability coordination states remain outside the obligation catalog in the draft; real resolver/Maintenance return acceptance is incomplete. |
| 179.46 | C/P | Ordered Evidence Actions, one-action execution checkpoints, admission and result-audit return are implemented; full successor-Graph E2E is pending. |
| 179.47 | P | Production Work Package owner rows were explicitly backfilled 17/17; exact purge, orphan migration and read-path benchmarks remain. |
| 179.48 | P/B | The implementation order and final semantics are recorded; v9 activation, real resolvers, user objectives, history and shadow research remain open. |
| 179.49 | P | `occurred_at` versus trusted `recorded_at` and historical stage/finalize exist; invalid-journal archive/rebuild and real `MaxA (2)` restoration remain. |
| 179.50 | P/B | Frozen Run configuration lazy detail, offline MathJax formula rendering and content-addressed equity images exist; the complete MaxA report and post-issue-143 reruns do not. |

### Confirmed cross-decision semantic drift

1. **Unfinished issue-143 is already merged into this worktree.** Commit
   `fef5b000` cannot be treated as a passed gate. The user explicitly states
   issue-143 is unfinished, so every affected accounting result remains
   ineligible for final shadow acceptance.
2. **Production versus draft is blurred.** The server is still on v8 and
   stores v4–v8 only. v9 catalog, report rules and successor topology are
   implementation candidates, not active research behavior.
3. **Operator ownership contradicts Grill 67/72.** There is no `tanh`, no
   public typed `where`, and two `WhereOp` classes.
4. **Data depth is encoded as frequency in Tiger.** This contradicts the
   accepted orthogonal `DataFreq`/sampling/depth model.
5. **The Research Obligation Skill is stale.** Its trial-synthesis reference
   still tells the Agent to return TrialPlan schema v4 while the canonical
   server protocol is v5 with Evidence Actions.
6. **Older checkpoint ownership wording is stale.** Grill 77 says the full
   checkpoint is local, while the later accepted Research Cycle uses the
   server trace as the canonical bounded replay owner.
7. **Major FTClient contracts are absent.** Data Sources, native aggregated
   Factor Library, Graph browser, token usage/settings, local SQLite, source
   sync modes and stable business-action manifest are not complete.
8. **“Closed Grill” was mistaken for “completed implementation.”** The former
   audit wording is replaced by this per-proposal matrix; closing a semantic
   question only means no further product choice is required.
9. **Canonical and packaged Research Obligation Skills differ.** The packaged
   `obligation-discovery.md` contains the two-stage data/field-coverage gate
   that is absent from the canonical Skill. The repository's own copy-parity
   test fails, so Agent behavior currently depends on the Skill load path.

### Dependency-ordered remaining implementation

This is the execution order derived from the detailed audit, not a new product
design. Unaffected work may continue, while accounting-dependent research
acceptance remains blocked until issue-143 is independently verified.

1. **Repair trust and semantic drift first.** Reconcile the canonical and
   packaged Research Obligation Skills, update TrialPlan v4 guidance to v5,
   restore the orthogonal Tiger sampling/frequency/depth contract, remove
   duplicate `WhereOp` ownership, implement the accepted typed `where`/`tanh`
   surface, and mark the older checkpoint-ownership decision as superseded.
   These are correctness defects in contracts an Agent may already consume.
2. **Finish the v9 deterministic contract before activation.** Implement real
   provider-neutral resolvers and CLI evidence operations for every active
   requirement subcategory, add bounded user acceptance
   objective/criteria, complete report preparation/coverage and prove the
   current-anchor packet budget. A catalog description or
   `requirement-detail` lookup is not a resolver.
3. **Publish and activate v9 only after its gates pass.** Validate cumulative
   continuation and re-entry against the final catalog/topology. Existing
   research remains pinned unless the user explicitly requests a version
   change; activation alone never migrates a Work Package.
4. **Restore history and finish lifecycle maintenance.** Restore exact v1–v3,
   add retention-aware exact-manifest purge/orphan checks and finish invalid
   historical-journal archive/rebuild plus invariance/current-HEAD tests.
5. **Complete the missing FTClient/CLI parity surfaces.** Add the Graph browser,
   Data Sources, native Local/Server Factor Library, token budget/usage,
   device-local SQLite preferences/outbox/cache, source-sync modes,
   recommended values and generated business-action conformance manifest.
   Every UI operation must remain available through the CLI.
6. **Complete the planning and long-running Agent flow.** Add bounded targeted
   versus open discovery, candidate eligibility/search/exhaustion, user scope
   confirmation, interruption decisions and provider-neutral Goal/watch
   behavior without adding routine reviewer or polling token cost.
7. **Perform accounting-dependent acceptance last.** Do not treat merge
   `fef5b000` as verification. After issue-143 is complete, independently
   validate the production margin/accounting path, rerun affected Trials under
   new identities, recover the complete `MaxA (2)` Chinese report, then run
   SgCPS and trend-family shadow acceptance with result tables and necessary
   content-addressed figures.

## Protocol package

Keep protocol definitions deterministic and provider-neutral under a cohesive
server package, for example:

```text
server/services/research_graph/research_cycle/
├── __init__.py
├── contracts.py
├── obligations.py
├── adjudication.py
├── closure.py
└── replay.py
```

Prefer deep modules with one semantic owner over a large generic
`research_cycle.py`. Keep each production module focused and normally below
about 300 lines; split only when ownership is genuinely distinct.

The protocol must define:

- Decision Contract view identity and hash;
- Research Claim identity, scope, and evidence states;
- Verification Obligation identity, state, discharge criterion, and links;
- TrialPlan linkage for selected actionable obligations;
- factual Evidence Envelope v2;
- paired AdjudicationProposal and AdjudicationDecision;
- Decision Warrant;
- SearchExhaustionProposal and bounded-closure dispositions;
- MethodologyChangeProposal and impact/reopening proposal;
- allowed transitions, explicit no-op representation, authority class,
  freshness, references, and canonical hashes.

All schemas reject server-side Skill identity fields and enforce existing
bounded serialization limits.

## Evidence Envelope compatibility

The current local Harness Evidence Envelope v1 contains a `decision` field.
Do not reinterpret or silently delete it.

Evidence Envelope v2 must:

- retain command outcome, RunSpec/TrialPlan/backend/factor/data identities,
  trial counts, stopping facts, metrics, conflicts, limitations, and artifact
  references;
- remove authoritative research disposition from the factual envelope;
- carry its schema version and canonical hash;
- require an AdjudicationProposal before its facts can affect accepted Claim or
  obligation state.

Compatibility rules:

- v1 remains retained under its historical semantics for privileged,
  non-Agent audit only;
- Research Agents, Reviewers, Skills, and ordinary Agent retrieval cannot read
  v1 payloads, decisions, metrics, artifacts, or references;
- deterministic compatibility code may inspect only bounded
  schema-version/hash/eligibility metadata and projects `legacy_ineligible`,
  never the v1 decision or content;
- no legacy Claim is strengthened and no obligation is fabricated as
  discharged;
- a resumed affected branch starts current obligation discovery without old
  evidence context and must produce new v2 evidence for current adjudication;
- activation performs no whole-history rewrite.

## Reference Skill

Create one local, progressively loaded reference Skill:

```text
research-obligation-cycle/
├── SKILL.md
├── agents/openai.yaml
├── references/
│   ├── obligation-discovery.md
│   ├── trial-synthesis.md
│   ├── evidence-adjudication.md
│   ├── search-exhaustion.md
│   └── methodology-impact.md
└── scripts/
    ├── validate-obligation-proposal.py
    └── validate-adjudication-proposal.py
```

Follow `skill-creator`:

- keep triggering conditions in the description;
- keep `SKILL.md` concise and imperative;
- load exactly one mode reference when possible;
- put schema checks in deterministic scripts;
- avoid README, changelog, duplicated schema prose, or unrelated assets;
- generate `agents/openai.yaml` from the completed Skill;
- run `quick_validate.py`;
- forward-test with fresh Agents using raw task artifacts and without leaking
  the expected answer.

The five modes are `discover`, `synthesize`, `adjudicate`, `exhaustion`, and
`impact`. Skill execution still requires the existing exact-content
conversation approval. Matching local content/authority/runtime state may be
reused. Changed content invalidates only local reuse authority.

## Harness and CLI surface

Refine the existing `factortester_research` CLI-Anything Harness; do not create
a second Harness.

The CLI surface should remain grouped and machine-readable. Candidate command
shape, to be confirmed against the current inventory:

```text
research obligation discover --json
research trial synthesize --json
research evidence adjudicate --json
research exhaustion assess --json
research methodology impact --json
graph next --json
```

Requirements:

- all commands call the real Research Graph/FactorTester backend or validate a
  local proposal for it; no duplicate research engine;
- all commands support deterministic `--json`;
- status/introspection is read-only and cheap;
- default Agent output is the current local packet, not a complete graph or
  history;
- errors identify missing evidence, stale hash, approval, capability, or
  authority without substituting an approximate method;
- installed-command subprocess tests use the Harness `_resolve_cli` convention
  and run without a source-tree `cwd`;
- the canonical and packaged CLI Skill copies remain byte-identical.

Before implementation, update the existing Harness `TEST.md` plan with the new
unit, subprocess, real-server, replay, Skill, and context-cost scenarios.

## Batch sequence

### Batch 0 — formalize Grill 143

Deliver:

- canonical context terminology;
- compact decision-log entry;
- detailed Grill 143 record;
- evidence-registry additions;
- this work package.

Gates:

- all links resolve;
- no pending Grill 143 marker remains;
- no canonical definition conflicts with Decision 124/126/137/142;
- Markdown and repository documentation checks pass.

Commit immediately after these gates. Do not combine runtime code with this
documentation batch.

### Batch 1 — protocol schemas and counterexamples

Deliver:

- provider-neutral protocol package;
- canonical hashing and bounded serialization;
- Evidence Envelope v2 plus explicit v1 compatibility;
- positive examples and counterexamples;
- deterministic shape, identity, chronology, scope, no-op, and authority
  validators.

Counterexamples must include:

- failed preregistered test discharges its test obligation while contradicting
  the Claim;
- favorable exploratory result cannot self-upgrade to confirmation;
- provenance failure opens an obligation without strengthening a Claim;
- obligation discovery without a new empirical envelope creates a Claim
  no-op;
- mismatched TrialPlan or methodology hash rejects both paired deltas;
- Skill identity in server payload is rejected;
- oversized references and packets are rejected.

Gates:

- pure unit and stable-hash tests;
- legacy v1 fixtures remain readable only by the privileged deterministic
  compatibility test surface and are rejected by every Agent-facing surface;
- direct service and HTTP transition entry reject v1 and non-factual v2 before
  database access;
- Harness persistence and Agent JSON projection are distinct: history retains
  v1 while every Agent view removes its payload, decisions, metrics, artifacts,
  paths, and nested copies;
- branch migration clears legacy evidence refs/history cursor from the current
  Agent projection and counts them only as omitted;
- no database schema change; runtime changes are limited to enforcing the
  legacy/factual boundary and producing EvidenceEnvelope v2.

### Batch 2 — shadow trace replay and branch projection

Deliver:

- proposal/decision/checkpoint trace event handling;
- atomic paired-delta replay;
- compact current Claim/obligation/closure projection;
- shadow comparison against the existing branch interpretation;
- lazy legacy projection without historical rewrite.

Persistence rule:

- first attempt to reuse existing trace plus bounded branch state;
- add at most one cohesive branch projection field only if replay/query
  measurement proves it necessary;
- add no per-concept table and no routine trace-history scan;
- unchanged replay/readiness writes nothing.

Gates:

- deterministic replay after restart;
- rejected or pending adjudication changes neither projection;
- accepted paired deltas cannot partially apply;
- query-count and rows-read tests are independent of trace length;
- routine context performs zero history scans and zero Agent Flow reads;
- migration is dry-run-first, backed up, idempotent, and rollback-tested if a
  physical change becomes necessary.

### Batch 3 — local reference Skill and conformance

Deliver:

- progressively loaded reference Skill;
- two deterministic validation scripts;
- local capability-description mapping and reuse hints;
- exact-hash approval and audit integration;
- realistic fixtures for all five modes.

Gates:

- `skill-creator` validation;
- first/changed execution fails without matching approval;
- matching approved content reuses local state without rediscovery;
- server inspection proves no Skill identity/body was written;
- fresh-Agent forward tests for each mode;
- only the selected reference file is loaded in each measured invocation.

Use a limited number of forward-test Agents. They receive raw Contract,
projection, Evidence Envelope, or methodology-diff fixtures, not this plan's
expected conclusions.

### Batch 4 — Harness refinement and compact Agent packet

Deliver:

- grouped CLI commands;
- local proposal validation and real backend submission/read paths;
- `graph next --json` additions limited to current obligations, candidate
  TrialPlan frontier, applicable capability descriptions, and changed refs;
- explicit cache/fingerprint reporting;
- updated canonical and packaged Harness Skills and documentation.

Gates:

- old Harness tests remain green;
- new core, installed-command subprocess, and real-server E2E tests pass;
- forced-installed CLI works outside the repository;
- default packet remains within the existing 6000-byte server ceiling and a
  stricter measured routine target set from baseline;
- untriggered modes, full Skill bodies, full Graph, full catalog, trace
  history, stdout/stderr, and artifacts do not leak into routine output;
- unchanged context produces zero writes.

### Batch 5 — Graph/methodology vNext in shadow mode

Deliver:

- capability descriptors for discover/synthesize/adjudicate/exhaustion/impact;
- deterministic predicates and readiness guards;
- obligation and adjudication routing without treating operations as edges;
- bounded-closure challenge policy;
- MethodologyChangeProposal and selective impact/reopening;
- shadow execution against representative existing research.

Reviewer policy:

- L1 routine deterministic transition: zero reviewer;
- exact preregistered machine criterion: zero reviewer beyond deterministic
  validation;
- material semantic, post-hoc, non-standard, or conflicting adjudication: one
  relevant reviewer;
- materially changed closure checkpoint: one independent closure challenger;
- third reviewer only after unresolved disagreement;
- Graph/methodology/backend policy change: Maintenance Case plus
  document-grounded human audit.

Gates:

- future-node and untriggered capability gaps never block current work;
- independent Jobs and branches continue during impact;
- matching unchanged review hash is reused;
- search exhaustion cannot be produced from “no idea” alone;
- closure dispositions distinguish decision-ready, exhausted without support,
  resource-stopped, blocked, and superseded;
- re-entry predicates affect only matching Contracts.

### Batch 6 — measured activation and rollback

Deliver:

- baseline-versus-shadow evidence;
- one blind targeted-research acceptance using a pinned valid SgCCS Factor
  Family version/configuration;
- one blind open-discovery acceptance that creates and studies a new
  point-in-time trend-following Factor Family after checking the workspace for
  semantic duplicates;
- versioned Graph/methodology activation through the existing pointer gate;
- affected-Contract impact plan;
- rollback target and release receipt.

Activation blocks unless:

- schemas and replay are deterministic;
- all old and new server/CLI/Harness tests pass;
- real FactorTester backend evidence is used;
- context bytes and settled token totals satisfy recorded thresholds;
- query count, rows read/written, transaction count, WAL growth, and latency do
  not regress beyond the accepted measured budget;
- routine reviewer count remains zero;
- no new persistence owner or server Skill identity exists;
- legacy evidence remains semantically unchanged;
- rollback is one approved pointer/version operation.

## Blind real-factor acceptance

The final Graph and reference Skill are not accepted only from synthetic
fixtures. Run two real FactorTester studies:

### Case A — pinned SgCCS targeted research

The Planning role creates a bounded Work Package over one explicitly pinned,
previously usable SgCCS Factor Family version and configuration. Pin the
RunSpec, product scope, time slices, costs/accounting, data snapshot, backend
revision, and TrialPlan before outcome inspection.

The Research role then runs the vNext Graph without receiving any legacy
Evidence Envelope, v1 decision, metric, artifact, or path. It must exercise:

- Decision Contract projection;
- initial obligation discovery;
- TrialPlan synthesis;
- real FactorTester JobAttempt and Evidence Envelope v2;
- paired adjudication;
- diagnostics/revision routing where triggered;
- search exhaustion and bounded closure.

After closure, a non-Agent acceptance comparator or privileged human audit may
compare the sealed v1 baseline with vNext. Comparison uses identical immutable
execution identities and checks factual metric/direction/scope compatibility,
not matching prose. Any difference is classified as:

- corrected v1 defect or stronger epistemic boundary;
- expected result of an explicitly changed method/scope;
- unexplained regression that blocks activation.

The v1 baseline remains inaccessible to Planning, Research, Reviewer, Skills,
and ordinary context throughout the run.

### Case B — new trend-following open discovery

The Planning role creates an Open Discovery Work Package inside the
user-authorized workspace scope. Before writing code it searches the current
Factor library for a semantically equivalent trend factor. If none is
equivalent, it specifies a simple point-in-time trend hypothesis, information
timing, parameter space, falsifiers, market-state boundaries, and permitted
single-factor use.

The Research role:

- creates the Factor Family through the existing generated factor-workspace
  method and public Factor Author SDK;
- passes Pylance/Pyright with zero errors;
- verifies batch/incremental semantics and no look-ahead;
- runs real diagnostics and backtests under an immutable TrialPlan;
- creates factor-specific obligations rather than relying on a fixed list;
- uses discover, synthesize, adjudicate, exhaustion, and impact modes where
  their trigger conditions apply;
- records missing general operators/strategy behavior as Capability Gaps
  rather than approximating or rejecting the factor;
- reaches a truthful positive, negative, blocked, or resource-stopped bounded
  disposition.

This case has no v1 conclusion target. Its purpose is to prove the Graph can
start from a user-authorized workspace, create a new factor, obtain real
evidence, revise it, and stop honestly.

### Role and token boundary

One Agent may perform the Planning role and then claim the bounded Research
role, provided the accepted Work Package, hashes, and role transition are
recorded. Do not spawn a second Agent merely to rename the role. Use one
independent reviewer only for a triggered material adjudication or the final
closure challenge.

Both cases record context bytes, settled tokens by category, reviewer count,
SQL reads/writes, cache reuse, Job duration, and accepted evidence count. The
real-factor acceptance fails if either Agent sees sealed v1 content, if a
routine node loads the complete Graph/catalog/Skill/history, or if database
cost grows with trace history.

## Acceptance matrix

| Invariant | Required proof |
|---|---|
| facts do not self-certify | Evidence Envelope-only test cannot change projections |
| paired interpretation is atomic | fault-injection and replay tests |
| obligations remain extensible | novel factor-specific obligation fixture |
| machine guards stay out of debt | invalid identity/timing fails before obligation creation |
| TrialPlans remain selective | non-actionable obligation produces no TrialPlan |
| exploratory evidence stays bounded | post-hoc favorable fixture opens confirmation duty |
| closure is not success | exhausted-without-support and blocked fixtures |
| closure resists Agent laziness | independent challenger finds seeded omission |
| reopening is selective | two-Contract impact test changes only one |
| backend remains authoritative | real-server Harness E2E |
| Skill remains local | persistence rejection and local audit tests |
| context remains local | packet field/byte and no-leak tests |
| I/O remains history-independent | traced SQL at small and large history sizes |
| token use is risk-bounded | settled invocation and reviewer-count comparison |
| model/runtime change is seamless | provider-neutral restart/replay fixture |
| old evidence is not upgraded or exposed | privileged v1 compatibility plus Agent-surface denial fixtures |

## Measurement protocol

Record, per representative transition:

- serialized Agent packet bytes;
- input/output/cache tokens by bounded category;
- Skill metadata/body/reference bytes actually loaded;
- reviewer count and reviewer tokens;
- SQL statement count and kind;
- rows read and written;
- transaction count, WAL growth, and elapsed time;
- trace length and catalog size used in the fixture;
- cache key, hit/miss, and semantic input hashes;
- number of accepted evidence items produced.

Compare identical immutable RunSpec, Decision Contract, product/methodology
scope, and backend revision. A zero or missing measurement cannot certify
activation. Thresholds are set after baseline measurement and become explicit
release gates; they are not invented in documentation.

## Commit and coordination policy

- finish and validate one batch, then commit that batch;
- preserve unrelated user changes;
- do not merge, push, activate, or delete the worktree without explicit user
  authorization;
- no batch may depend on an uncommitted previous batch;
- if a batch exposes a semantic conflict, stop only affected work, record the
  proposal, and continue unaffected tests/jobs;
- every commit message references the eventual issue/work-package identifier;
- after each commit, report changed owners, tests, token/I/O evidence, rollback
  target, and remaining risk.

## Overall repository release remains required

Completing this work package does not complete the server/client release. The
accepted [`server-client-release-plan.md`](../server-client-release-plan.md)
still requires:

1. a secure repository topology that no longer exposes server implementation
   through a public history;
2. the reviewed integration chain into the stable branch;
3. stable-branch migration from `master` to `main`;
4. checksummed macOS and Python client artifacts published from `main`;
5. clean installation from the real GitHub Release with database, login,
   macOS UI, Vibe UI, and bounded-research recovery evidence;
6. verification that the remote default is `main`;
7. remote branch and local worktree cleanup only after the published release
   and rollback path have been verified.

The recommended secure topology is to make the existing FactorTester
repository the private server repository and publish a separate history-clean
public client repository. Making the current repository private reduces
exposure but does not itself create a valid public client distribution.

As last verified on 2026-07-19, `maix00/FactorTester` remains `PUBLIC` with
default branch `master`; this is an unresolved product-release blocker.

## Batch 1 release evidence

Batch 1 introduces no database schema or new persistence owner. It adds the
provider-neutral protocol validators, factual Evidence Envelope v2 boundary,
legacy Agent-access denial, Harness persistence/Agent-view separation, and
legacy branch-projection cutover described above.

The release gate must be rerun immediately before commit. Its expected proof is:

- protocol counterexamples, Graph transition, migration, final-schema, and
  shadow-replay server tests pass;
- the complete Harness suite reports 43 passing tests;
- the forced-installed Harness subprocess suite reports 12 passing tests;
- Pyright reports zero errors on the changed protocol and Harness core;
- canonical and packaged Harness Skills both validate and remain
  byte-identical;
- `git diff --check` is clean.

## Batch 2 release evidence

Batch 2 uses no new table or column. The existing branch `latest_trace_id`
points to a bounded checkpoint carrier in the immutable trace. Context and
transition load it by trace primary-key LEFT JOIN in the existing branch
SELECT; they never scan trace history.

The implemented replay rules are:

- initialization accepts only unknown/evidence-free Claims, open obligations,
  no pending adjudication, and no closure;
- proposal alone and rejected/revision-requested decisions do not change
  accepted Claim or obligation state;
- an accepted authority-matched pair applies both deltas into one checkpoint
  or applies neither;
- newly discovered obligations require their complete validated body;
- bounded closure binds current Claim/obligation projection hashes and requires
  an independent closure decision;
- ordinary transitions copy checkpoint continuity, while forks create one
  bounded child-owned bootstrap trace instead of inheriting an unverifiable
  parent cursor;
- shadow replay recomputes Graph path, parent linkage, paired events, and every
  checkpoint hash; legacy EvidenceEnvelope v1 references are not counted as
  current evidence.

Release evidence on 2026-07-19:

- complete server suite: 236 passed;
- complete Harness suite: 43 passed with only the existing Pandas alias
  deprecation warnings;
- focused protocol/Graph/TrialPlan/migration suite: 78 passed;
- Pyright: zero errors and warnings;
- a 250-row irrelevant trace-history fixture leaves routine context at one
  SELECT, zero writes, no history scan, and under the existing 6000-byte
  packet ceiling;
- routine transition remains one branch UPDATE plus one trace INSERT;
- all changed production modules remain below 300 lines;
- `git diff --check` is clean.

## Batch 3 release evidence

Batch 3 adds one provider-neutral, progressively loaded local reference Skill
and maps five semantic capability descriptions to its exact whole-bundle
manifest. The server still stores neither Skill identity nor Skill content.
The local Harness requires approval before first execution, reuses only the
same approved fingerprint, and fails closed when any routed reference or
validator changes.

Fresh-Agent forward tests received only bounded fixtures. One Agent exercised
discovery, TrialPlan synthesis, and evidence adjudication and loaded exactly
the router plus those three selected references. A second Agent exercised
search exhaustion and methodology impact and loaded exactly the router plus
those two references. Neither read this work package, server source, tests,
legacy evidence, or an unselected mode. Their ambiguity findings tightened
checkpoint ownership, missing-input gaps, Claim no-ops, obligation-state
vocabulary, and bounded-closure disposition selection without adding another
runtime object.

Release evidence on 2026-07-19:

- canonical and packaged Skill trees are byte-identical across 10 files;
- both trees pass `skill-creator` validation;
- the whole-bundle manifest is
  `a91fd64b149fd6a05aa3aececafa9703885846e94c42a701c091da78bcc6fc3d`;
- Harness plus Skill conformance tests: 48 passed;
- forced-installed CLI subprocess tests: 12 passed;
- Pyright on changed production and validation scripts: zero errors and
  warnings;
- a clean wheel contains all 10 Skill files, and an isolated `python -S`
  import recomputes the same manifest without source-tree or editable-install
  fallback;
- all changed production modules remain below 300 lines;
- `git diff --check` is clean.

## Batch 4 release evidence

Batch 4 keeps the Harness as a thin CLI-Anything adapter. `cycle next` calls
the installed FactorTester client and performs no local write. `cycle
validate` runs the bundled deterministic proposal validator locally. `cycle
advance` validates before invoking the real backend and then records one
factual local command envelope; it does not copy the HTTP client or research
computation.

The server `next` packet now adds only current capability descriptions, current
open obligation summaries, a truthful TrialPlan-selection frontier, and
bounded changed references. It contains no concrete Skill identity or body,
full Graph/catalog, trace history, artifact bodies, or raw stdout/stderr.
Splitting deterministic readiness into `branch/next_packet.py` reduced both
changed server modules below 300 lines without creating another persistence
owner.

Release evidence on 2026-07-19:

- complete server suite: 236 passed;
- complete forced-installed Harness suite: 49 passed;
- Harness plus reference-Skill conformance suite: 52 passed;
- Pyright on changed server and Harness core: zero errors and warnings;
- canonical and packaged Harness Skills are byte-identical and the canonical
  Skill passes `skill-creator` validation;
- routine `next` performs one SELECT, zero writes, no trace-history scan, and
  remains below the stricter 4000-byte measured target;
- local packet validation rejects legacy evidence, raw output, full
  Graph/catalog content, artifacts, and trace history before Agent use;
- local transition validation rejects invalid proposal/Skill identity before
  backend invocation;
- a clean wheel contains the new command/core modules and Harness Skill, and a
  temporary installed-package invocation exposes `cycle next`, `validate`,
  and `advance` without source-tree fallback;
- all changed production modules remain below 300 lines;
- `git diff --check` is clean.

## Batch 5 release evidence

Draft Graph v4 governs the four routine Research Cycle operations through
existing lifecycle nodes, conditional triggers, output kinds, and freshness
guards. It does not create operation-shaped nodes or edges. Methodology impact
is declared separately as a Maintenance Case capability requiring
document-grounded grill and human audit.

The methodology protocol now accepts only machine-evaluable affected-Contract
predicates. Its pure impact plan separates affected, unaffected, and
undetermined Contracts; proposes reopening only the affected semantic-change
set; and explicitly continues unaffected branches and Jobs. A stable
`review_input_hash` permits exact unchanged-review reuse without a per-call
reviewer or new database object.

Search exhaustion now requires explicit assessment of declared scope,
stopping rules, and the remaining TrialPlan frontier. “No idea” cannot produce
`decision_ready` or `exhausted_without_support`; closure still requires the
existing independent challenge.

Shadow replay of the representative sealed v3 historical preflight stops
truthfully at the new first-principles discovery freshness guard. It neither
loads sealed conclusions nor pretends the old trace satisfied the new
methodology. This is classified as a methodology re-entry requirement for
Batch 6 comparison, not as an unexplained backend failure.

Release evidence on 2026-07-19:

- complete server suite: 236 passed;
- complete forced-installed Harness plus Skill suite: 52 passed;
- Pyright on changed Graph, closure, and methodology modules: zero errors and
  warnings;
- unapproved entry-node resolution exposes only the current discovery
  approval gap; approved entry resolution contains no future-node gap;
- default entry resolution is 3082 bytes and approved entry resolution is
  3259 bytes; the 36441-byte full Draft Graph remains an explicit
  developer/audit surface, never routine Agent context;
- canonical and packaged Skills are byte-identical and both Skill validators
  pass;
- changed Research Obligation Cycle bundle fingerprint:
  `95c58ec11017ee82554c0ef2bc455380e51eb0263331a107d0c1afcd8ed42149`;
- a clean temporary wheel imports Graph v4 and recomputes the same Skill
  fingerprint from installed package resources;
- no database schema, persistence owner, routine reviewer, or Skill identity
  was added;
- `git diff --check` is clean.
