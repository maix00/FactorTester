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

Use one role-specific startup packet rather than assembling infrastructure
context with an Agent:

```bash
factortester agent-flow resume research-agent-1 --role research \
  --instance-id <instance-id> --branch-id <branch-id>
```

Planning supplies `--workspace-id`; Server Maintenance needs no graph or
workspace argument. The deterministic packet is at most 6000 bytes, omits
other roles' queues and full history/catalog/output, and includes the current
Agent budget summary. Repeated unchanged resume is byte-stable and writes
nothing.

## Research execution

Freeze one complete `ResearchConfiguration`, then let immutable `ResearchRun`
and durable `Job` records own execution:

```bash
cli-anything-factortester-research plan \
  --factor-family SgCCS \
  --factor 'SgCCS=SgCCS|P:CA|N:10d' \
  --product A.DCE \
  --source Local \
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

New previews and submissions use RunSpec v2. The common freeze path embeds
source-free factor revision manifests: only hashes of the executable family
source, family/selected-factor expression contracts, stable parameter schema,
operator registry, and selected alias are retained. Preview returns the same
manifests for TrialPlan design. Worker planning recomputes them and fails
closed if factor source or resolved semantics changed after submission. A
legacy alias that cannot be resolved is explicitly marked
`family_contract_only`; it is not silently presented as verified semantics.

The Planning Agent must confirm the concrete product list and requested sources
with the user before calling `plan`. The first executable phase records a
compact real-backend availability probe. It never expands scope or silently
falls back. The probe is feasibility evidence: obligation discovery still
defines the exact coverage, field/frequency, visibility, latency, and
permitted-use facts that the research decision needs.

## Token-efficient Active Graph flow

Resolve only the current node. Full-catalog resolution is reserved for an
explicit activation audit.

```bash
cli-anything-factortester-research graph capabilities \
  --product-group china_futures \
  --node hypothesis_preregistration \
  --facts-file local-facts.json \
  --approve-implementation local.research-obligation-cycle \
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
The approval option is valid only after the current Agent conversation
approves that exact local Skill fingerprint.

Research Cycle operations remain capabilities of existing lifecycle
nodes/guards, not additional Graph edges. A semantic methodology change is a
Maintenance Case and deterministic Contract-impact plan; unaffected branches
and Jobs continue.

`context` and `next` return bounded current-node packets. They do not load the
complete graph, catalog, artifacts, stdout/stderr, or untriggered future gaps.
Conditional capabilities use machine predicates first and ask an Agent only
when the predicate is genuinely undetermined.

The Harness `cycle next` wrapper is read-only and fails closed if an older or
changed backend returns more than 6000 bytes or leaks a heavy/legacy field.
`cycle advance` validates local Research Cycle proposals before invoking the
real client and retains only a factual local command envelope for audit.
`cycle continuation-preview` performs no write and returns the exact
cross-version effect hash. After conversation approval,
`cycle continue` consumes that exact Gate, preserves the old branch and Job
binding, and records one bounded local command receipt.

For `data_contract__factor_semantics`, transition evidence supplies only an
explicit `data_availability_request` (`products`, `sources`, `probe`, and
`expanded: false`). The server repeats the inspection outside the branch write
transaction and persists its own Contract/Methodology-bound EvidenceEnvelope.
Client `server_evidence` and availability guard booleans are rejected or
ignored as authority. A profile proves only observed availability facts; it
does not establish PIT integrity, replayability, latency fitness, or clear a
research obligation. Missing required products keep the branch at
`data_contract`; the Agent may propose another source such as Tiger, public
data, a narrower scope, or a bounded infeasibility decision.

For `factor_semantics__validation_design`, transition evidence supplies only
`factor_semantics_request.configuration_revision`. The server reloads the
branch-owned workspace outside the write transaction and freezes compact,
source-free factor revision manifests. It derives whether selected factor
implementations resolve; the client cannot self-certify those guards. This
identity binding does not establish causal timing, economic meaning,
auxiliary-factor validity, or clear an open Verification Obligation.

For `backtest__statistical_robustness`, transition evidence supplies only
`job_attempt_request.job_id`. The server reloads the owner-scoped Job,
ResearchRun identity, terminal assurance, and active artifact manifest in one
bounded detail read, then binds its own EvidenceEnvelope. Only a succeeded,
anomaly-free, trusted Job can satisfy the trust guard. Only a named
`net_returns` or `net_return_series` artifact can satisfy the net-return guard;
a generic `result`, summary metrics, or gross-return field cannot. If the
backend does not emit that canonical artifact, route to the capability gap
instead of allowing the client to infer it. A TrialPlan that needs return-level
robustness must freeze `retention_mode=full`; summary retention intentionally
does not retain a canonical series.

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
Synthesis consumes the Decision Contract, actionable obligations, exact
product/source scope, compact availability evidence, factor/data/timing
semantics, product accounting, market-regime comparisons, selection and
multiplicity history, costs, capacity, resource limits, sample roles, freeze
proof, methodology, and graph branch. Availability alone is not sufficient.
New plans use schema version 4: `decision_contract_hash`,
`methodology_hash`, bounded `obligation_refs`, `stage_policy`, and
`parent_trial_plan_hash` are validated against the current Research Cycle
checkpoint and branch projection. Older v1-v3 plans remain replayable but do
not receive stage-lineage enforcement.
Submitting a run may include `trial_binding` with:

- `instance_id` and `branch_id`;
- the canonical `trial_plan`, hash, and version;
- comparison-arm `trial_role` and declared `comparison_id`.

The RunSpec hash must be a planned comparison member. Its sample stage is
derived from the TrialPlan sample role, not from `trial_role`. The initial plan
freezes stage partitions, RunSpecs, comparisons, outcomes, criteria, and
stopping/multiplicity rules. A child version cannot replace them after outcome
inspection; factor or trial-design revision starts a new hypothesis and plan
lineage. The server releases the old current binding only on that declared
new-hypothesis edge; old plans and sample exposure remain immutable.
Submission is accepted only for the branch's current stage at the plan-bound
execution node. `ResearchRun` persists that server-derived stage, and every
child `Job` inherits the binding through `run_id`.

Bounded closure is defeasible: an accepted new or reopened
decision-blocking obligation clears accepted or pending closure atomically.
Rejected or non-blocking deltas leave closure unchanged.

`cycle next` returns bounded Claim and open-obligation summaries. Use
`cycle inspect <instance> <branch> <claim|obligation> <id>` only when the
referenced full current body is necessary; it performs one current-checkpoint
read and never scans the full trace.

After a Job becomes terminal, capture its server-projected audit envelope:

```bash
cli-anything-factortester-research \
  --session research.json \
  evidence capture-job <job_id> --json
```

The Harness validates the envelope against the same response's terminal
assurance and deduplicates it by content hash. It does not copy the result
body, artifact payloads, stdout, or source into the session.

Render a reviewed, bounded local snapshot without contacting the server:

```bash
cli-anything-factortester-research report render \
  --snapshot-file report-snapshot.json \
  --workspace-root <factor-workspace> \
  --json
```

The deterministic target writes
`research/branches/<branch-id>/REPORT.md` only when content changes. Factor
workspace regeneration preserves `research/`, including provisional notes.
Reports link content-addressed evidence and assets; they reject factor source,
formula/expression trees, credentials, and raw stdout/stderr. Markdown is the
only implemented target. PDF and chart producers remain optional future
targets; a chart is an embedded report asset, not a separate report.

Do not infer OOS from a calendar date. A recent historical interval, delayed
stream, paper stream, or live stream is untouched/prospective only if its
observations were sealed after the factor, selection boundary, and TrialPlan
were frozen. Previously inspected historical regimes are validation evidence,
not untouched holdout.

```bash
factortester run preview --analysis ic
factortester run submit --analysis ic \
  --trial-binding-file trial-binding.json
```

`run preview` is read-only and returns the exact server-frozen RunSpec hash
without creating a ResearchRun or Job. Put that hash in the TrialPlan before
freezing it, then submit with the unchanged workspace revision and options.

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
