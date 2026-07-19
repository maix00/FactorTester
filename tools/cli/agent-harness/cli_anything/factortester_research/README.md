# cli-anything-factortester-research

CLI-Anything harness for planning factor research, calling the real remote
`factortester` backend, and keeping a local, replayable research audit.

## Setup

```bash
cd tools/cli/agent-harness
python -m pip install -e .
factortester configure --host 127.0.0.1 --port 8123
factortester login --username <user> --keep-login
cli-anything-factortester-research doctor --json
```

The harness is a remote HTTP client, not a local replacement for FactorTester.
Use `--json` for agent-readable output and an explicit `--session` path when
several agents work independently.

## Research execution

Freeze one complete `ResearchConfiguration`, then let immutable `ResearchRun`
and durable `Job` records own execution:

```bash
cli-anything-factortester-research plan \
  --factor-family SgCCS \
  --factor 'SgCCS=SgCCS|P:CA|N:10d' \
  --configuration-file research-configuration.json \
  --json

cli-anything-factortester-research workspace prepare --build --sync --json
cli-anything-factortester-research workspace inspect \
  --factor-family SgCCS --json
cli-anything-factortester-research run-step -- \
  workspace create --factor-family SgCCS
cli-anything-factortester-research run-step -- \
  run submit --analysis ic --analysis factor_evaluation \
  --analysis factor_type_analysis --analysis backtest
cli-anything-factortester-research run-step -- job list
```

`workspace` owns the editable configuration, `ResearchRun` freezes the RunSpec,
and each `Job` owns status, progress, cancellation, errors, results, and
artifacts. Observe, cancel, and retry by `job_id`; never use `page_uuid` as
execution ownership.

## Token-efficient Active Graph flow

Resolve only the current node. Full-catalog resolution is reserved for an
explicit activation audit.

```bash
cli-anything-factortester-research graph capabilities \
  --product-group china_futures \
  --node hypothesis_preregistration \
  --facts-file local-facts.json \
  --json > capability-resolution.json

factortester research-graph start factor-research \
  --product-group china_futures \
  --workspace-id <workspace_id> \
  --capability-resolution-file capability-resolution.json

cli-anything-factortester-research cycle next \
  <instance_id> <branch_id> --json
cli-anything-factortester-research cycle validate \
  --evidence-file transition-evidence.json --json
cli-anything-factortester-research cycle advance \
  <instance_id> <branch_id> \
  --edge-id <edge_id> \
  --evidence-file transition-evidence.json \
  --target-capability-resolution-file target-resolution.json \
  --json
```

There is no capability `attest` command and no capability-receipt round trip.
The client submits the node-local deterministic resolution directly; the
server validates it against the immutable graph descriptor.

`context` and `next` return bounded current-node packets. They do not load the
complete graph, catalog, artifacts, stdout/stderr, or untriggered future gaps.
Conditional capabilities use machine predicates first and ask an Agent only
when the predicate is genuinely undetermined.

The Harness `cycle next` wrapper is read-only and fails closed if an older or
changed backend returns more than 6000 bytes or leaks a heavy/legacy field.
`cycle advance` validates local Research Cycle proposals before invoking the
real client and retains only a factual local command envelope for audit.

Graph activation validation accepts canonical references only:

```bash
factortester research-graph validate factor-research <version> \
  --proposal-id <proposal_id> \
  --routine-instance-id <instance_id> \
  --routine-branch-id <branch_id> \
  --baseline-run-id <run_id>
```

The server derives non-mutating replay, like-for-like shadow outcomes, and
token-efficiency evidence. Client-supplied pass booleans are not authoritative.

## TrialPlan binding

Before the validation design is frozen, persist one bounded immutable
`TrialPlan` in transition evidence. Later transitions refer to its hash.
Submitting a run may include `trial_binding` with:

- `instance_id` and `branch_id`;
- the canonical `trial_plan`, hash, and version;
- `trial_role` and declared `comparison_id`.

The RunSpec hash must be a planned member of that role/comparison. The
`ResearchRun` retains the binding and every child `Job` inherits it through
`run_id`; changing the plan requires a new plan version rather than mutation.

```bash
factortester run submit --analysis ic \
  --trial-binding-file trial-binding.json
```

## Skill discovery and audit

The graph stores capability descriptions and descriptor hashes, not concrete
skill names. Give an Agent only the current capability description:

1. Reuse an already loaded matching skill when its provider fingerprint is
   unchanged.
2. Otherwise discover a candidate without loading its body.
3. Obtain approval in the Agent conversation before first execution.
4. Load the selected `SKILL.md` only after approval.
5. Record actual local use:

```bash
cli-anything-factortester-research skill-usage record \
  --capability-description '<description>' \
  --descriptor-hash <sha256> \
  --skill-name <name> \
  --skill-description '<description>' \
  --provider <provider> --version <version> \
  --source-fingerprint <sha256> \
  --approval-ref <conversation-ref> \
  --load-mode reused \
  --matching-rationale '<why this matches>' \
  --json
```

The concrete skill identity stays in the local research audit for replay and
human inspection. Do not repeatedly load a known skill merely because its name
appears in history.

## Guardrails

- Align signal visibility, IC forward returns, and next-bar execution.
- Freeze costs, capacity, margin, fee mode, sample role, slice, and trial count.
- Query existing factor-library evidence before repeating expensive work.
- Treat missing backend capability as a platform gap, never as a factor result.
- `client_only` agents retain evidence and report server gaps.
- `source_owner` agents fix the owning issue worktree, run tests, and restart
  the target service through the manager; ownership is not permission to edit
  an unrelated checkout.

## External factors

Use `external-factor plan` to freeze daily/minute preparation and
`external-factor validate` to verify manifests. Attach a validated handoff with
`factortester external-factor validate <handoff.json> --attach`; never inject a
Parquet matrix directly into native replay.
