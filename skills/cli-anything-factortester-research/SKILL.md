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

## Run the ordinary research loop

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
  run submit --analysis ic --analysis factor_evaluation \
  --analysis factor_type_analysis --analysis backtest
cli-anything-factortester-research run-step -- job list
```

Treat the workspace as editable configuration, the `ResearchRun` as immutable
RunSpec ownership, and `Job` as lifecycle/result/artifact ownership. Never use
`page_uuid` as execution ownership; observe, cancel, and retry by `job_id`.

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

Submit only factual `EvidenceEnvelope` schema version 2. Never request, read,
reuse, or submit schema-version-1 evidence; it is unavailable to Agents. If a
session reports `legacy_evidence_unavailable_count`, create new current-schema
evidence. Put Claim/obligation interpretation in a separate adjudication
proposal, never inside the EvidenceEnvelope.

For activation validation, send canonical instance/branch/baseline-run
references. The server derives replay, shadow comparison, and token evidence;
never invent client-side pass booleans.

## Freeze TrialPlan and bind runs

Persist one canonical TrialPlan body before validation design is frozen; later
transitions refer to its hash. Bind a submitted ResearchRun with the plan,
version, graph instance/branch, trial role, and declared comparison. The RunSpec
hash must be a planned member. Child Jobs inherit the binding through `run_id`.
Create a new TrialPlan version instead of mutating the frozen body.

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
3. Obtain approval in the Agent conversation before first execution.
4. Load only the selected `SKILL.md`.
5. Record actual use locally with `skill-usage record`, including provider,
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
