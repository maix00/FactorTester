---
name: cli-anything-factortester-research
description: Plan and execute factor research through the real remote FactorTester CLI, including local workspace inspection, node-local Active Graph capability resolution, immutable TrialPlan and ResearchRun binding, durable job observation, progressive skill loading with approval, local skill-use audit, and platform-gap routing. Use when an agent needs to research one or more factor families without loading the full graph, capability catalog, artifacts, or backend source into context.
---

# FactorTester Research Harness

Use the real backend and keep each Agent's local process in an explicit session:

```bash
cli-anything-factortester-research \
  --session /path/to/agent-session.json doctor --json
```

Start or resume from one deterministic role packet instead of loading
architecture documents:

```bash
factortester agent-flow resume <agent-id> --role research \
  --instance-id <instance-id> --branch-id <branch-id>
```

Planning uses `--role planning --workspace-id <workspace-id>`; Server
Maintenance uses `--role server_maintenance`. The packet is capped at 6000
bytes, contains only that role's current work and budget summary, and is
unlimited when the user has not configured a token cap. A model launcher must
reserve one `agent-flow invocation` before a real model call and settle it
afterward. Do not create model reservations for deterministic graph
transitions, backend Jobs, cache hits, or unchanged heartbeat/resume checks.

## Run the ordinary research loop

Before planning, confirm the products and requested sources with the user in
the current Planning Agent conversation. Do not delegate this choice or infer
extra products from a factor family. Pass the exact scope to `plan`; it places
a compact, real-backend availability probe before TrialPlan design:

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
  run submit --analysis ic --analysis factor_evaluation \
  --analysis factor_type_analysis --analysis backtest
cli-anything-factortester-research run-step -- job list
```

Keep only the availability profile hash/reference in Agent context. Do not
load a provider catalog, broaden scope, or fall back to another source.
Distinguish cached history, delayed streams, paper streams, and live streams;
configuration or entitlement does not prove usable coverage, latency, or
point-in-time integrity. Keep exact routine checks deterministic. When a
remaining data question could change the bounded decision, use obligation
discovery to define it, availability inspection to collect facts, and evidence
adjudication to resolve or bound it.

Treat the workspace as editable configuration, the `ResearchRun` as immutable
RunSpec ownership, and `Job` as lifecycle/result/artifact ownership. Never use
`page_uuid` as execution ownership; observe, cancel, and retry by `job_id`.
Local `workspace inspect` is provisional source understanding, not executable
factor identity. `run preview` and `run submit` use the same RunSpec-v2 freeze
path and return source-free `factor_revision_manifests`. Each manifest hashes
the family source, family expression, stable parameter contract, operator
registry, selected alias, and resolved selected-factor expression. It contains
no source, formula, tree, or parameter values. If execution-time revalidation
finds a changed manifest, the Job fails closed and requires a new preview and
TrialPlan member. Treat `resolution_status=family_contract_only` as an
unresolved factor-semantics obligation, not as verified selected-factor
semantics.

## Use Active Graph without loading global state

Resolve only the current node:

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
```

When the current edge is `data_contract__factor_semantics`, put the exact
request in transition evidence instead of copying the preview response:

```json
{
  "data_availability_request": {
    "products": ["A.DCE"],
    "sources": ["Local"],
    "probe": false,
    "expanded": false
  }
}
```

The server repeats the inspection outside the branch write transaction,
binds the resulting EvidenceEnvelope to the current Contract and Methodology,
and derives basic requested-product availability. Never submit
`server_evidence`, `data_availability_profile_bound`, or
`requested_product_availability_present` as authority. Availability does not
prove point-in-time integrity, replayability, latency fitness, or discharge a
Verification Obligation. If a required product is unavailable, remain at
`data_contract` and ask only for an actual source/scope/fee/credential/licence
choice; Tiger is one candidate source, not a Graph rule.

When the current edge is `factor_semantics__validation_design`, submit only
the branch configuration revision to be frozen:

```json
{"factor_semantics_request": {"configuration_revision": 3}}
```

The server reloads the branch-owned workspace outside the write transaction,
freezes source-free factor revision manifests, and derives whether every
selected factor resolves. Never submit factor-semantics guard booleans or use a
local workspace inspection as server evidence. Frozen implementation identity
is necessary but does not establish causal timing, economic meaning,
auxiliary-factor validity, or discharge open Verification Obligations.

When the current edge is `backtest__statistical_robustness`, submit only the
terminal Job identity:

```json
{"job_attempt_request": {"job_id": "job-1"}}
```

The server reloads the authenticated Job, immutable ResearchRun binding,
terminal assurance, and active artifact manifest outside the branch write
transaction. It derives whether the attempt is trusted and whether a canonical
`net_returns` or `net_return_series` artifact exists. Never submit terminal,
trust, or net-return guard booleans as authority. A generic `result` artifact
does not establish a net return series; remain on the backtest node and surface
the backend capability gap instead of guessing from gross returns or summary
metrics. When the TrialPlan needs statistical robustness over returns, freeze
the RunSpec with `retention_mode=full`; summary retention deliberately cannot
claim that the canonical series was retained.

Do not search for or call capability `attest`/receipt APIs; they do not exist.
Submit the node-local resolution directly. Use `--all` only for explicit
activation audit and `--include-contracts` only for human inspection.
Pass `--approve-implementation` only after this conversation approves that
exact local fingerprint.

The Research Cycle modes are capabilities required by existing lifecycle
nodes and guards, not extra nodes or edges. Discovery may be required after a
frozen boundary, a material semantic/evidence change, or before closure;
TrialPlan synthesis occurs only for selected actionable obligations;
adjudication proposes paired deltas; exhaustion contributes to bounded
closure. Methodology impact remains a separate Maintenance Case with
documented grill and human audit, and it must leave unaffected branches and
Jobs running.

At `research_decision`, submit discovery, adjudication, or closure events
through the declared `research_decision__cycle_event` self-edge. It records a
node-local Research Cycle update without inventing a new node or moving the
branch. The server derives `research_cycle_delta_applied`; never submit or
self-certify that guard, and do not write an empty event trace.

Before advancing, validate Research Cycle proposals locally. Then use the thin
Harness adapter to submit through the installed FactorTester client:

```bash
cli-anything-factortester-research cycle validate \
  --evidence-file evidence.json --json
cli-anything-factortester-research cycle advance \
  <instance_id> <branch_id> \
  --edge-id <edge_id> \
  --evidence-file evidence.json \
  --target-capability-resolution-file target-resolution.json \
  --json
```

`cycle next` performs no local write and rejects an oversized packet, raw
stdout/stderr, full graph/catalog content, artifacts, trace history, or legacy
evidence. `cycle advance` validates before backend mutation and records only a
local factual command envelope plus compact event metadata.

When an approved Active Graph direct-child version must continue a paused
legacy branch without rerunning a trusted Job, preview the exact effect first:

```bash
cli-anything-factortester-research cycle continuation-preview \
  <source_instance_id> <source_branch_id> \
  --target-version <version> --job-id <job_id> --json
```

The preview is read-only and creates no local session write. Submit its
`target_hash` to the conversation approval/Grill flow. Only after the server
returns the exact Gate ID, consume it with:

```bash
cli-anything-factortester-research cycle continue \
  <source_instance_id> <source_branch_id> \
  --target-version <version> --job-id <job_id> \
  --expected-target-hash <sha256> \
  --human-authorization-id <gate_id> --json
```

Never edit `graph_version`, rebind a ResearchRun, or copy an artifact manually.
The server preserves the source branch and validates the Job, TrialPlan,
Contract, graph parent, assurance, and target node. The mutating command writes
one bounded local command receipt; it does not load source history into Agent
context.
Candidate edges expose `required_research_evidence` separately from
`required_transition_facts`; never use a permission, budget, Job status, or
approval fact to adjudicate a research obligation.

Submit only factual `EvidenceEnvelope` schema version 2. Never request, read,
reuse, or submit schema-version-1 evidence; it is unavailable to Agents. If a
session reports `legacy_evidence_unavailable_count`, create new current-schema
evidence. Put Claim/obligation interpretation in a separate adjudication
proposal, never inside the EvidenceEnvelope.

Use a specific research `evidence_kind`. Hypothesis, data, and factor-semantics
evidence must bind `contract_hash` and `methodology_hash`; diagnostics,
backtests, robustness, and JobAttempt evidence must additionally bind
`trial_plan_hash` and `run_spec_hash`. A local `control_command` envelope audits
CLI execution only and is not admissible research evidence.

After a Job reaches a terminal state, capture its server-owned evidence once:

```bash
cli-anything-factortester-research \
  --session research.json \
  evidence capture-job <job_id> --json
```

This command reuses the authenticated Job detail envelope, verifies its
Contract/Methodology/TrialPlan/RunSpec identity against terminal assurance,
and records only the bounded envelope plus local audit metadata. It never
derives research identity from stdout, a Skill, or local source. A repeated
capture reuses the same envelope hash. `not_usable` and
`maintenance_required` attempts remain auditable facts but are not trusted
research-result evidence.

For activation validation, send canonical instance/branch/baseline-run
references. The server derives replay, shadow comparison, and token evidence;
never invent client-side pass booleans.

## Freeze TrialPlan and bind runs

Persist one canonical TrialPlan body before validation design is frozen; later
transitions refer to its hash. Bind a submitted ResearchRun with the plan,
version, graph instance/branch, comparison role, and declared comparison. The
server derives the sample stage from the RunSpec's planned sample role; never
use `trial_role` as the stage. The initial schema-v4 plan freezes stage
partitions, RunSpecs, and comparisons. A child plan cannot replace that design
after outcome inspection. Factor or design revision starts a new hypothesis
and TrialPlan lineage: the server releases the old current binding only on the
new-hypothesis edge, while the old plan and sample exposure remain immutable.
Submit only the current stage from the plan-bound execution node; past,
future, or legacy-unbound stages fail closed. Child Jobs inherit the binding
through `run_id`.

Keep routine context local. Read Claim and obligation summaries from
`cycle next`; only when one `detail_ref` is needed, load that single body with
`cycle inspect <instance> <branch> <claim|obligation> <id>`. Do not reload the
full checkpoint or trace history.

Availability is only one TrialPlan input. Also bind the Decision Contract,
actionable obligations, factor/data/timing semantics, product accounting,
market-regime comparisons, selection and multiplicity history, costs,
capacity, resource limits, sample roles, freeze proof, methodology, and graph
branch. Return a Capability Gap when a material input is absent. Treat recent
or prospective data as untouched holdout only when it was sealed after the
factor, selection boundary, and TrialPlan were frozen.

```bash
factortester run preview --analysis ic
factortester run submit --analysis ic \
  --trial-binding-file trial-binding.json
```

Call `run preview` first. It performs the same server-side configuration and
product-selection freeze as submission but creates no ResearchRun or Job.
Use its `run_spec_hash` in the immutable TrialPlan, then submit with the same
workspace revision and options.

## Load skills progressively

The graph supplies capability descriptions and descriptor hashes, not concrete
skill names.

1. Match the current description to an already loaded, fingerprint-valid skill.
2. If none matches, discover metadata without reading the skill body.
3. Treat a capability binding as discovery, not execution authority. If it
   reports `local_execution_approval_required=true`, obtain approval in the
   Agent conversation and re-resolve with that implementation grant. Do not
   load or execute until `execution_approval_granted=true`.
4. A fingerprint-valid local usage record may authorize reuse; changed content
   requires a new approval.
5. Load only the selected `SKILL.md`.
6. Record actual use locally with `skill-usage record`, including provider,
   version, fingerprint, approval reference, `loaded|reused`, rationale, and
   token counts.

Do not upload concrete skill identity as graph state. Do not reload a skill
solely because a historical record names it.

## Preserve research integrity

- Align signal availability, IC return horizon, and next-bar execution.
- Freeze ranking universe, masks, dates, costs, capacity, margin, fee mode,
  sample roles, slices, selection history, and trial count.
- Query reusable factor-library evidence before expensive repetition.
- Treat missing operators, invalid timing, and broken job lifecycle as platform
  gaps rather than factor conclusions.
- Let `client_only` agents retain/report backend gaps. Let a `source_owner` fix
  only the owning issue worktree, test it, and restart the correct service.
