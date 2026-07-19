# Research Obligation Cycle Implementation Work Package

Status: implementation in progress; Grill 143 semantics accepted; Batches 0
through 5 are complete and Batch 6 is next.

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
