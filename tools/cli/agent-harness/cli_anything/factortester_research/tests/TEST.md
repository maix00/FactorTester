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
- non-mutating historical replay and a hard token-efficiency activation gate.

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
