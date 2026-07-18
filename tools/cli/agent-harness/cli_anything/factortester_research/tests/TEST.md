# Harness Test Plan

The harness tests cover:

- plan generation through `workspace -> immutable RunSpec -> job`;
- absence of analysis-specific submission commands and `page_uuid` ownership;
- session/gap state transitions;
- validation slice separation;
- source-owner worktree selection;
- subprocess delegation to the real `factortester` executable.

## Research decision graph refinement

The adaptive research-graph work is implemented as vertical slices. Tests are
added one observable behavior at a time.

### Slice 1 planned behavior

- `test_core.py`
  - the existing fixed Harness plan projects to a valid Observed Graph;
  - every edge references declared nodes;
  - canonical graph JSON produces a stable content hash;
  - graph validation rejects duplicate IDs, dangling edges, and invalid
    lifecycle/enforcement values;
  - advisory plan phases remain distinguishable from enforced gap states;
  - capability requirements are semantic contracts, not concrete Skill names;
  - mandatory and conditionally triggered capabilities remain distinct;
  - FDR, Deflated Sharpe, and PBO trigger only when their trial-family
    preconditions are known to hold;
  - authoritative net returns precede bootstrap Sharpe and result audit;
  - diagnostic and robustness failures can reject or preregister a bounded
    revision without a post-selection audit loop;
  - factor revisions restart hypothesis, capability, data, and validation
    checks;
  - factor semantics and terminal decisions require bounded
    hypothesis-code-alignment and provisional-memory references;
  - external Skill execution remains unresolved without an explicit grant.
- `test_full_e2e.py`
  - the installed Harness command prints the Observed Graph as JSON;
  - repeated invocations produce the same graph hash;
  - human-readable status identifies the graph as observed and non-active;
  - default capability output omits full contracts, while
    `--include-contracts` exposes them for explicit audit.

### Server and integration behavior

- authenticated FactorTester API and CLI retrieval of observed, draft, and
  active versions;
- immutable version history and gated active pointer;
- capability approval and Skill execution gates;
- server-side capability descriptions without concrete Skill identity;
- local hash-chained actual Skill usage audit;
- branch-local pause with unrelated job continuity;
- compact current-node context without full graph/catalog/artifact history;
- current-node resolution storage and `research-graph next`;
- per-transition token telemetry by main Agent, reviewer, Skill document,
  artifact summary, and cache use;
- token-budget behavior that suppresses new reviewers without stopping jobs;
- provider fingerprint/cache invalidation and model-neutral semantics;
- proposal/reviewer/audit lifecycle, including third reviewer only after
  disagreement;
- trusted-launcher Agent principal and lineage attestations, so distinct
  execution IDs cannot simulate independent reviewers;
- one-time human activation authorization, separate from ordinary authenticated
  Agent proposal, review, validation, and grill requests;
- a deterministic Backend Assurance Gate that emits a compact signed receipt
  for an immutable terminal job without launching an Agent;
- exactly one independently attested `backend_verifier` only when a succeeded
  job has a semantic or integrity anomaly;
- backend verifier and implementation roles require trusted-launcher
  `server_backend_code` authority; ordinary research users can report and route
  anomalies but cannot claim code-modification authority;
- no verifier, Skill load, artifact body read, stdout/stderr load, or extra
  research Agent on the routine trusted backend path;
- non-mutating historical replay and a hard token-efficiency activation gate.

### Real installed CLI to server E2E

The release gate must also start the complete `server.create_app()` application
against an isolated temporary SQLite database and drive it over real HTTP. It
must not use Flask `test_client`, fake routes, or source-module CLI fallbacks.

The workflow must prove:

- both `cli-anything-factortester-research` and `factortester` resolve to
  installed console scripts;
- one real login with `--keep-login` remains authenticated in later,
  independently spawned CLI processes;
- the installed Harness emits the real Draft Graph and the installed
  FactorTester CLI publishes it;
- proposer and reviewer use distinct server-issued Agent executions under the
  same owner;
- capability approvals and receipts, non-zero trusted provider usage,
  like-for-like shadow runs, validation, grill audit, and activation all pass
  through the real HTTP service;
- a live instance returns separate bounded `context` and `next` packets and can
  advance using a target-node capability receipt;
- `logout` removes the local cookie and a later protected command fails.

The test must use a temporary `FACTORTESTER_HOME`, temporary database, generated
credentials, and a test-only provider-attestation secret. It must not read or
mutate a developer's existing account, cookie, graph, or research data.

Run:

```bash
cd tools/cli/agent-harness
conda run -n GTHT pytest cli_anything/factortester_research/tests -q
```

Installed-command validation:

```bash
python -m pip install -e .
CLI_ANYTHING_FORCE_INSTALLED=1 conda run -n GTHT pytest cli_anything/factortester_research/tests/test_full_e2e.py -q
```

Manual smoke test:

```bash
cli-anything-factortester-research --session /tmp/ftr-session.json plan \
  --factor-family SgCCS \
  --factor 'SgCCS=SgCCS|P:CA|N:10d' \
  --configuration-file research-configuration.json \
  --json
```

The generated plan must create/select a workspace, write or import a revision, submit one run containing requested analyses, and observe/control results by `job_id`.

## External Vibe infrastructure coverage

- Unit coverage validates the canonical locked pipeline command, daily/minute
  manifest contracts, factor provenance, mandatory next-bar execution, and the
  explicit unavailable GTHT import boundary.
- The real-file smoke test validated the existing daily v1, minute v1,
  `academic_carhart_mom`, and `gtht_handoff.json` artifacts.

Do not keep a hard-coded pass count here; the authoritative result is the
current command exit status and collected test report.

## Test Results

Last release-gate run: 2026-07-18

```text
CLI_ANYTHING_FORCE_INSTALLED=1 conda run -n GTHT python -m pytest \
  tools/cli/agent-harness/cli_anything/factortester_research/tests \
  tests/server/test_research_graphs.py \
  tests/server/test_research_job_lifecycle.py \
  tests/cli/test_research_graph_commands.py \
  tests/cli/test_factortester_client.py -q

78 passed, 123 warnings in 16.56s
```

The real-server test printed installed paths for both console scripts and
completed the isolated login-through-logout Active Graph workflow. The warnings
are existing Pandas frequency-alias deprecations outside this refinement.
