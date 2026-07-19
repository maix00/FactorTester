# Research Obligation Cycle Implementation Work Package

Status: proposed implementation package; Grill 143 semantics accepted; no
runtime implementation started.

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
- zero database schema or runtime-route changes.

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
