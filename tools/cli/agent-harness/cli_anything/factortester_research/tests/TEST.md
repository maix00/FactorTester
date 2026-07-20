# Harness Test Plan

This release gate validates a CLI-Anything adapter to the real remote
FactorTester backend. A successful process exit is insufficient: tests inspect
the session, graph, capability, evidence, HTTP, RunSpec, ResearchRun, Job, and
artifact contracts produced by the workflow.

## Test inventory

- `test_core.py`: deterministic graph/capability/session/evidence and packaging
  unit tests.
- `test_full_e2e.py`: installed Harness subprocess workflows with a controlled
  real `factortester` executable.
- `test_real_server_e2e.py`: installed Harness and FactorTester console scripts
  against a complete isolated `server.create_app()` over real HTTP.

## Unit coverage

### Graph protocol and topology

- Project the existing fixed plan as an advisory Observed Graph.
- Build the product-neutral Draft Graph and validate every node, edge,
  lifecycle, enforcement, risk level, and capability descriptor.
- Preserve stable content hashes across the natural module split.
- Reject duplicate IDs, dangling edges, and missing descriptors.
- Keep diagnostic rejection, bounded revision, capability-gap recovery, and
  result-audit routes semantically distinct.

### Node-local capability resolution

- Resolve the current node by default and the full graph only when `--all` is
  explicit.
- Evaluate bounded predicates deterministically and expose unknown facts as
  `requires_agent_judgment`.
- Exclude model/provider/Codex runtime identity from semantic cache keys.
- Verify approved provider fingerprints before selecting an implementation.
- Hash every progressively loaded instruction, reference, and executable file
  used by an approved multi-file Skill into one provider identity.
- Invalidate cache results when provider source content changes.
- Reuse a registered approved Skill by default when its reviewed fingerprint is
  unchanged, while changed, newly discovered, and quarantined providers remain
  fail-closed without loading their Skill body.
- Keep capability descriptions and descriptor hashes independent from concrete
  locally used Skill identity.
- Return byte-stable role-specific Agent resume packets capped at 6000 bytes:
  Research receives one branch, Planning one bounded workspace-factor summary,
  and Server Maintenance only its actionable case queue.
- Keep unconfigured profiles immediately usable, expose configured remaining
  budget without usage history, and omit other roles' state, complete graph,
  catalogs, output, and future gaps.

### Local research audit

- Preserve hash-chained Skill usage with provider, version, fingerprint,
  approval reference, load/reuse mode, rationale, and token counts.
- Persist compact factual EvidenceEnvelope v2 records with command exit status
  and artifact references instead of inline stdout/stderr bodies or research
  decisions.
- Capture a terminal JobAttempt envelope projected by the authenticated server,
  verify its frozen research identity against terminal assurance, and reuse
  the same envelope hash without duplicating the local audit record.
- Keep the Job list projection to one bounded database read for Job records,
  pin state, and active-artifact counts rather than per-Job follow-up reads.
- Project Job detail, pin state, TrialPlan binding, and EvidenceEnvelope
  identity with one joined read; the envelope projector performs no reads.
- Keep legacy EvidenceEnvelope v1 payloads in the persistence-only historical
  record while excluding their decisions, metrics, artifacts, paths, and
  nested copies from every Agent-facing session JSON view.
- Preserve gap and factor-improvement state transitions.
- Keep selection slices separate from OOS annotation.

### Research Obligation Cycle Skill

- Package one canonical and installed reference Skill with five progressively
  loaded modes.
- Resolve its five capability descriptions through one exact whole-bundle
  manifest fingerprint.
- Require conversation approval before the first execution and reuse only the
  unchanged approved fingerprint.
- Validate obligation-discovery and paired-adjudication proposals with
  standalone deterministic scripts.
- Cover material time, market-state, instrument, and interval-event transfer
  questions without Cartesian-product expansion; preserve sequential
  walk-forward exposure, high-frequency day/month staging, purge/embargo, and
  a genuinely untouched latest interval in TrialPlan guidance.
- Load market-event search guidance only for a material anomaly, preserve
  occurrence and public-availability time, bound post-hoc narratives, and use
  at most one event-research sub-agent at the declared risk threshold.
- Reject server proposal payloads containing concrete Skill identity.
- Keep canonical and packaged Skill trees byte-identical.
- Require every newly persisted adjudication or closure proposal to name the
  settled proposer invocation that produced it.
- Resolve all proposer and independent-reviewer authority references for one
  transition with one bounded Agent Flow lookup.
- Bind independent-reviewer invocations to the exact proposal hash and reject
  missing, unsettled, wrong-role, wrong-scope, same-principal, or same-lineage
  authority.
- Keep ordinary factual transitions and deterministic historical replay free
  of Agent Flow database reads.

### Packaging

- Keep canonical and packaged `SKILL.md` bytes identical.
- Keep every new production module below 300 lines.
- Preserve the original Click command names, options, help, and JSON shapes
  after command-domain extraction.

## Installed subprocess workflows

The subprocess suite uses `_resolve_cli("cli-anything-factortester-research")`
and supports `CLI_ANYTHING_FORCE_INSTALLED=1`. It must not set a source-tree
working directory to make an installed command pass.

Workflows cover:

- `--help`, `--json`, plan creation, status, and gap lifecycle;
- Observed/Draft Graph output and stable content hashes;
- current-node capability resolution with full contracts omitted by default;
- explicit `--include-contracts` audit output;
- dry-run and real delegation to the configured `factortester` executable;
- server-owned terminal JobAttempt evidence capture without reconstructing
  research identity from CLI output or local Skill state;
- factor-workspace inspection and platform-gap EvidenceEnvelope persistence;
- external daily/minute/factor/handoff manifest validation.

## Real installed CLI to server E2E

The release gate starts the complete Flask application against temporary SQLite
state and drives it through installed console scripts over TCP. It does not use
Flask `test_client`, fake HTTP routes, a developer account, or source-module CLI
fallbacks.

It proves:

- one login with `--keep-login` authenticates later independent processes and
  logout removes the local session;
- the Harness publishes a real immutable graph version;
- trusted proposer/reviewer executions are server-issued and independently
  attributable;
- graph start accepts direct node-local `capability_resolution`; no
  attest/receipt API participates;
- `context` and `next` are bounded current-node packets and future,
  untriggered gaps do not block the branch;
- target-node resolution accompanies only the transition that needs it;
- server-owned validation derives non-mutating trace replay, like-for-like
  shadow comparison, and token-efficiency evidence from canonical references;
- the client cannot self-certify replay/shadow/token pass booleans;
- proposal, independent review, grill audit, human authorization, and
  activation remain separate gates.

Companion server tests, outside this Harness package suite, validate the
TrialPlan schema, transition freeze rules, TrialPlan-to-ResearchRun binding,
Job inheritance through `run_id`, retention, and exact-hash rollback gates.
Schema-v4 tests distinguish sample stage from comparison arm, freeze stage
partitions plus RunSpec/comparison membership across child versions, validate
direct-confirmation entry, persist one compact branch stage projection, and
keep the Agent packet below its existing byte limit.
ResearchRun boundary tests verify that stage comes from the planned sample,
not the comparison arm; only the current stage at the plan-bound execution
node can run; protected-sample reuse cannot be hidden behind a shared
`candidate` role; and the hot path remains one branch read plus one run write.
Factor-revision lineage tests preserve the old plan and exposure, release only
on the server-owned new-hypothesis edge, and bind the replacement as version 1
of a new plan identity.
Research Cycle reopening tests clear accepted or pending closure only for an
accepted new or reopened decision-blocking obligation; rejected and
non-blocking deltas preserve closure.
Compact-cycle tests expose bounded question/criterion/detail refs in the
routine packet and load exactly one referenced Claim or obligation body with
one database read and no trace-history scan.
Data-contract tests require an explicit request on the existing edge, execute
availability outside the branch write lock, bind a server-owned
Contract/Methodology EvidenceEnvelope, override client guard booleans, reject
stale/oversized requests without transition writes, and derive identical
guard facts during offline replay. Availability never discharges an
obligation or claims PIT, replayability, or latency fitness.
Factor-revision server tests verify stable source-free manifests, hash changes
for source or resolved-expression changes, RunSpec-v2 preview/submit identity,
legacy RunSpec-v1 readability, and execution-time failure when the current
factor implementation no longer matches the frozen manifest. Random
Parameter display UUIDs are excluded from semantic hashes.
Factor-semantics edge tests require only the branch configuration revision,
freeze manifests outside the branch write transaction, bind a server-owned
Contract/Methodology EvidenceEnvelope, reject stale or unresolved selections,
and derive identical manifest guards during offline replay. The envelope
contains no source, formula, or expression tree and does not self-certify
causal or economic semantics.
JobAttempt edge tests require only an owner-scoped `job_id`, bind canonical
Job/ResearchRun/Contract/Methodology/TrialPlan identity outside the branch
write transaction, and derive identical trust and artifact guards during
offline replay. Client booleans cannot override server facts; failed,
maintenance-required, cross-branch, and stale-plan attempts cannot advance.
Only a named `net_returns` or `net_return_series` artifact qualifies, while a
generic result artifact deliberately exposes a backend capability gap.
Native backtest artifact tests derive the named series from fee-adjusted ledger
equity and fail closed on missing, zero, duplicate, non-finite, or unsupported
engine curves. Summary retention produces no such research artifact.
They also verify that `run preview` derives the exact immutable RunSpec hash
through the same server-side freeze path without creating a ResearchRun or Job,
so an Agent can preregister a TrialPlan before submission.
Capability-resolution tests verify that registered, approved, whole-bundle
fingerprint-valid Skill implementations may be bound without rediscovery but
cannot self-authorize execution: a local conversation grant is required before
use, and changed source always fails closed. They also keep equity-only
microstructure guidance out of China-futures resolution and bind the built-in
TrialPlan/RunSpec trial ledger plus reviewed false-discovery guidance.

Derived-report tests verify byte-stable Markdown, content-addressed asset
embedding, explicit missing/unauthorized gaps, atomic incremental writes,
preservation of the previous complete report after write failure, rejection of
source/heavy payloads, and a server-free CLI render path. Factor-workspace
tests separately prove that regeneration preserves `research/` reports and
notes.

## Commands

Run the Harness package suite:

```bash
PYTHONPATH=tools/cli/agent-harness \
  conda run -n GTHT python -m pytest \
  tools/cli/agent-harness/cli_anything/factortester_research/tests \
  -v -s --tb=short
```

Require the installed Harness command:

```bash
cd tools/cli/agent-harness
python -m pip install -e .
CLI_ANYTHING_FORCE_INSTALLED=1 \
  conda run -n GTHT python -m pytest \
  cli_anything/factortester_research/tests/test_full_e2e.py \
  -v -s --tb=short
```

## Test results

Last release-gate run: 2026-07-20

```text
CLI_ANYTHING_FORCE_INSTALLED=1 PYTHONPATH=tools/cli/agent-harness \
  conda run -n GTHT python -m pytest \
  tools/cli/agent-harness/cli_anything/factortester_research/tests \
  -v -s --tb=no

[_resolve_cli] Using installed command:
  /opt/homebrew/Caskroom/miniconda/base/envs/GTHT/bin/cli-anything-factortester-research
collected 73 items

test_core.py
  46 passed
test_full_e2e.py::TestCLISubprocess
  17 passed
test_real_server_e2e.py::test_installed_clis_drive_real_server_active_graph_e2e
  [_resolve_cli] Using installed command:
    /opt/homebrew/Caskroom/miniconda/base/envs/GTHT/bin/factortester
  [_resolve_cli] Using installed command:
    /opt/homebrew/Caskroom/miniconda/base/envs/GTHT/bin/cli-anything-factortester-research
  PASSED
test_report_rendering.py
  9 passed

73 passed, 123 warnings in 16.27s
```

All warnings are existing Pandas frequency-alias deprecations (`d` to `D`) in
parameter and FactorExpr shift code outside this Harness refactor. The command
exit status and collected test names remain authoritative; no production logic
uses a hard-coded expected count.
