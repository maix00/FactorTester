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

### Local research audit

- Preserve hash-chained Skill usage with provider, version, fingerprint,
  approval reference, load/reuse mode, rationale, and token counts.
- Persist compact factual EvidenceEnvelope v2 records with command exit status
  and artifact references instead of inline stdout/stderr bodies or research
  decisions.
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
They also verify that `run preview` derives the exact immutable RunSpec hash
through the same server-side freeze path without creating a ResearchRun or Job,
so an Agent can preregister a TrialPlan before submission.
Capability-resolution tests verify that registered, approved, whole-bundle
fingerprint-valid Skill implementations may be bound without rediscovery but
cannot self-authorize execution: a local conversation grant is required before
use, and changed source always fails closed. They also keep equity-only
microstructure guidance out of China-futures resolution and bind the built-in
TrialPlan/RunSpec trial ledger plus reviewed false-discovery guidance.

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
collected 55 items

test_core.py
  39 passed
test_full_e2e.py::TestCLISubprocess
  15 passed
test_real_server_e2e.py::test_installed_clis_drive_real_server_active_graph_e2e
  [_resolve_cli] Using installed command:
    /opt/homebrew/Caskroom/miniconda/base/envs/GTHT/bin/factortester
  [_resolve_cli] Using installed command:
    /opt/homebrew/Caskroom/miniconda/base/envs/GTHT/bin/cli-anything-factortester-research
  PASSED

55 passed, 123 warnings in 13.64s
```

All warnings are existing Pandas frequency-alias deprecations (`d` to `D`) in
parameter and FactorExpr shift code outside this Harness refactor. The command
exit status and collected test names remain authoritative; no production logic
uses a hard-coded expected count.
