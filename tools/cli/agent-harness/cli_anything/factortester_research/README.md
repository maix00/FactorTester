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

When the harness runs inside a Manager-owned server Profile Agent, the Manager
provides a short-lived local CLI capability automatically. In that context do
not run `factortester configure` or `factortester login`; those commands remain
for a standalone client or terminal installation.

Use one role-specific startup packet rather than assembling infrastructure
context with an Agent:

```bash
factortester agents flow resume research-agent-1 --role research \
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
  --frequency MIN1 \
  --configuration-file research-configuration.json \
  --json

cli-anything-factortester-research workspace prepare --build --sync --json
cli-anything-factortester-research workspace inspect \
  --factor-family SgCCS --json
factortester research workspaces create \
  --profile maxa --title "SgCCS research" \
  --product-group china_futures
# product-group is the implementation group; exact products and masks are
# frozen later in the TrialPlan/RunSpec.
factortester research workspaces fork \
  graph-branch:<instance>:<branch> --profile maxa \
  --label "alternative hypothesis"
# The command inherits the source branch's current report-tree snapshot and
# materializes branches/<new-branch>/REPORT.md. It does not invent a
# checkpoint; later writes affect only the new branch.
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

factortester research graphs start factor-research \
  --product-group china_futures \
  --workspace-id <workspace_id> \
  --capability-resolution-file capability-resolution.json

factortester research graphs node info <instance_id> <branch_id>
factortester research graphs node advance \
  <instance_id> <branch_id> \
  --edge-id <edge_id> \
  --evidence-file transition-evidence.json \
  --entry-assessment-file entry-assessment.json \
  --factor-family <factor_family> \
  --profile-id <profile> --agent-id <agent>
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

`research graphs node info` is read-only and fails closed if the server packet
exceeds its calibrated byte ceiling or leaks a heavy/legacy field.
`research graphs node advance` performs local Research Cycle validation,
rebuilds the exact selected-edge contract, validates report coverage, prepares
the declared target capability resolution, and then invokes the server once.
When the current node has Entry Requirements, its first invocation writes one
compact editable assessment document and returns `state_changed: false`.
The Agent completes that document and reruns the same command. `node advance`
then validates the Chinese content, derives assessment/report hashes and
submits them without exposing separate prepare or validate commands.
`research graphs continuation-preview` performs no write and returns the exact
current-node re-entry hash. `research graphs continue` applies only that exact
hash, preserves the logical Work Package and Hypothesis Branch, and creates a
new physical incarnation for the target Graph version.

For `data_contract__factor_semantics`, the Agent captures the exact
`products availability ... --json` execution as Terminal Evidence and binds
the returned `data-availability-profile` reference. The profile is materialized
once; later clients and `node advance` read the immutable snapshot instead of
scanning the data source again. Client `server_evidence` and availability guard
booleans are rejected or ignored as authority. A profile proves only observed availability facts; it
does not establish a source-wide timing verdict, latency fitness, or clear a
research obligation. Runtime signal/execution scheduling determines causality.
Missing required products keep the branch at `data_contract`; the Agent may
propose another server source, public data, a narrower scope, or a bounded
infeasibility decision. A device-local source such as Tiger is discoverable
only when this CLI is running inside FTClient's local bridge. It must never be
inferred from, or submitted as, a server catalog capability.

For `factor_semantics__validation_design`, `node advance` automatically reloads
the branch-owned workspace and freezes compact, source-free factor revision
manifests. The Agent does not submit a `factor_semantics_request` and must not
use `research step inspect` for this edge. The server derives whether selected
factor implementations resolve; the client cannot self-certify those guards.
This identity binding does not establish causal timing, economic meaning,
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

After independent review, inspect and activate through the compact
server-derived workflow:

```bash
factortester research graphs activation-status factor-research <version>
factortester research graphs activate factor-research <version> --yes
```

The ordinary activation command derives the exact proposal, Graph hash, diff
hash, authenticated conversation and deterministic upgrade validation from the
server Gate. Temporary validation rows are rolled back in the activation
transaction; no validation Work Package or Profile binding remains. Do not
copy internal values into Agent plans. The low-level `human-authorize` and
`--human-authorization-id` forms remain only for audit recovery.

Existing research is never migrated by activation. Continue one Work Package
through its target Graph lineage with:

```bash
factortester research graphs continue <instance_id> <branch_id> \
  --target-version <version> --yes
```

The CLI calls the existing continuation preview first and submits its exact
hash to the existing continuation endpoint. The server recomputes the hash,
requires the target to be a descendant, preserves the current node, and binds
the cumulative Change Manifest. `continuation-preview` and
`--expected-target-hash` remain available for audit and recovery.

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

`research graphs node info` returns bounded Claim and open-obligation summaries.
Use `factortester research graphs cycle-object <instance> <branch>
<claim|obligation> <id>` only when the referenced full current body is
necessary; it performs one current-checkpoint read and never scans the full
trace.

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
  --workspace-root <profile-root> \
  --json
```

The caller root is the owning Profile root, never its factor-authoring
worktree. One Work Package owns `research/<work-package-id>/INDEX.json`, its
derived aggregate `REPORT.md`, branch projections below
`branches/<branch-id>/REPORT.md`, and an `assets/` boundary. A per-package file
lock serializes index merge and publication. Changed files are staged before
the branch, aggregate, and index are atomically published; the index is the
last UI-visible commit point, and a failed publication restores the complete
old generation. Unchanged content writes none of those report files.

The JSON result separates stable `artifact:research/...` references from a
`local_artifact_descriptor`. Only that explicitly local descriptor contains
`file://` references for FTClient; Graph/server projections must use the stable
references. Local reports may contain explicit bounded `code` and `math`
blocks. Arbitrary source/formula/expression-tree fields remain rejected instead
of being silently discarded by the legacy snapshot projection. Credentials and
unbounded process output remain rejected. The branch-scoped `report export`
command writes Markdown directly and invokes the signed native FTClient
renderer for PDF. Both exports remain derived from the same structured report
tree; neither creates a second report store.

### Graph-independent report authoring

All report mutations are CLI operations. The macOS client is a read-only
viewer: it loads the content document, its bindings sidecar, and navigation
metadata, but it never creates components, edits prose, or attaches chips.

The report is a branch-owned Work Package tree. It is content-only and
independent of the Active Graph; Graph, Job, evidence, obligation and
checkpoint references are typed bindings on report components. Evidence bodies,
Job results and report prose remain in their own stores.

Report prose is portable Markdown rich text. It supports prose, inline code,
inline/display LaTex, fenced code and well-formed Markdown tables. For a
standalone or source-bound code block, formula, table, image or result, use a
typed component instead. A JSON payload is never report prose.

```bash
cli-anything-factortester-research report create \
  --profile <profile> --work-package-id <package> --branch-id <branch> --json
cli-anything-factortester-research report add \
  --profile <profile> --work-package-id <package> --branch-id <branch> \
  --component-id findings --kind chapter --title '研究发现' --json
cli-anything-factortester-research report add \
  --profile <profile> --work-package-id <package> --branch-id <branch> \
  --component-id result-table \
  --kind table --parent-id findings --title '结果表' \
  --content-file result-table.json --json
cli-anything-factortester-research report add \
  --profile <profile> --work-package-id <package> --branch-id <branch> \
  --component-id prerequisite --kind entry --parent-id findings \
  --before-component-id result-table --body-file prerequisite.md --json
cli-anything-factortester-research report add \
  --profile <profile> --work-package-id <package> --branch-id <branch> \
  --component-id source-code \
  --kind code --title '因子实现' --language python \
  --code-file factor.py --parent-id findings --json
cli-anything-factortester-research report add \
  --profile <profile> --work-package-id <package> --branch-id <branch> \
  --component-id signal-equation --parent-id findings \
  --kind math --title '信号公式' --latex 's_t = z_t / \\sigma_t' --json
cli-anything-factortester-research report add \
  --profile <profile> --work-package-id <package> --branch-id <branch> \
  --component-id backtest-summary --parent-id findings \
  --kind result --title '回测结果' --content-file backtest-summary.json --json
cli-anything-factortester-research report validate \
  --profile <profile> --work-package-id <package> --branch-id <branch> --json
cli-anything-factortester-research report manifest \
  --profile <profile> --work-package-id <package> --branch-id <branch> --json
cli-anything-factortester-research report render \
  --profile <profile> --work-package-id <package> --branch-id <branch> --json
```

For prose, use `--body` or a UTF-8 `--body-file`; do not put a JSON object in
either. `report validate`, `manifest`, and `render` operate on the same branch
tree and never create a loose report document or an alternate report store.
If `--parent-id` and `--target-chapter-id` are both omitted, `report add`
writes a direct child of the report tree's last chapter. Use
`--target-chapter-id` or `--parent-id` for an explicit destination. Use exactly
one of `--before-component-id` and `--after-component-id` to insert relative to
an existing sibling under that same parent; omitting both appends normally.
Use ordinary Markdown links with a typed `factortester://` target when prose
needs an optional domain reference, for example
`[IC 证据](factortester://evidence/evidence%3Aic-2025)`. The report CLI does
not register Evidence, Jobs, obligations, or other domain objects. Mandatory
requirement and Job-result associations are emitted by their owning workflow,
not by an agent-authored `chip` command.

Do not infer OOS from a calendar date. A recent historical interval, delayed
stream, paper stream, or live stream is untouched/prospective only if its
observations were sealed after the factor, selection boundary, and TrialPlan
were frozen. Previously inspected historical regimes are validation evidence,
not untouched holdout.

```bash
factortester run preview --analysis ic
factortester run submit --analysis ic \
  --trial-binding-file trial-binding.json \
  --profile <profile> --work-package-id <package> --branch-id <branch>
```

`run preview` is read-only and returns the exact server-frozen RunSpec hash
without creating a ResearchRun or Job. Put that hash in the TrialPlan before
freezing it, then submit with the unchanged workspace revision and options.
An ordinary Job remains unbound. For a report-bound Trial Job the CLI freezes
the local report HEAD identity, waits by default, creates one `test_result`
special section, and returns
`report_collections[].report_follow_up.parent_id`. The
`analysis_required` status tells the Agent to add its interpretation below
that exact parent. Use `--without-report` only for an intentional opt-out.

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

## Strategy intent configuration

The Harness exposes the same policy surface without keeping a second local
configuration model:

```bash
cli-anything-factortester-research strategy-intent describe --json
cli-anything-factortester-research strategy-intent show --group A1 --json
cli-anything-factortester-research strategy-intent configure A1 \
  --role screen=LiquidityGate --screen-rule gte --screen-lower 1 \
  --role sizing=RiskSize --allocation-policy factor_sizing --json
```

These commands delegate to the installed `factortester` executable. Workspace
revision checks and manifest role compatibility remain owned by the real client
and server. A role alias from a Profile factor-worktree is intentionally
deferred until `run preview` or `run submit` supplies that worktree; it is
frozen as a run-scoped source and is never published into the shared library.

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
