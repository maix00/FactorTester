---
name: cli-anything-factortester-research
description: Use the real FactorTester CLI to conduct bounded factor research. Start from the current Active Graph packet, inspect only the declared next action, submit immutable runs, observe Jobs, and author local graph-independent reports.
---

# FactorTester Research Harness

Use this harness for factor research through the real FactorTester backend. It
is an execution aid, not a copy of the Active Graph or a source of current
research facts.

## Start and discover the current action

Use an explicit local session and JSON output:

```bash
cli-anything-factortester-research \
  --session /path/to/research-session.json doctor --json
factortester agent-flow resume <agent-id> --role research \
  --instance-id <instance-id> --branch-id <branch-id>
cli-anything-factortester-research cycle next \
  <instance-id> <branch-id> --report-file <report.json> --json
```

Treat the returned packet as authoritative for the current node, candidate
edges, blockers, obligations, report tasks, and whether agent judgment is
needed. Do not load the full graph, catalog, trace history, or unrelated
evidence. When the packet names an action whose input contract is not present,
read only its compact contract:

```bash
factortester research step inspect <instance-id> <branch-id> \
  --output current-action.json
```

The inspect response owns current operation payload contracts. Do not memorize
edge-specific request JSON, capability identifiers, products, or Graph version
names in this Skill.

## Command map

- `plan`, `workspace`, `run-step`: prepare a bounded research configuration and
  delegate to the real client
- `cycle`: read the current packet, inspect one declared object, validate and
  advance a bounded Research Cycle
- `report`: create, edit, validate, render, fork, and bind a local
  graph-independent report
- `evidence`: capture bounded server-owned evidence from a terminal Job
- `graph`: inspect a graph or resolve a locally approved implementation
- `strategy`: list public templates and validate a `StrategySpec`
- `skill-usage`: record actual, approved skill use locally
- `gap`, `operator`, `service`: route platform gaps and source-owner work

Use `--help` or `<group> --help` for stable command syntax. Use `--json` for
machine consumption; parse structured output, never CLI prose.

## Ownership and safety boundaries

- Workspace is editable configuration; `ResearchRun` owns an immutable RunSpec;
  `Job` owns lifecycle, result, and artifact state. Observe, cancel, and retry
  by `job_id`, never `page_uuid`
- Call `run preview` before `run submit`; the server freezes the same resolved
  configuration and rejects changed executable factor semantics
- A Profile factor worktree is opt-in transient Run source. It is never silently
  synchronized into the canonical user factor library
- `StrategySpec` uses public templates or a `profile:<path>` Strategy Actor.
  Do not put Flow, StrategyBook, or policy implementation names in it
- Report documents contain authored local content only. Graph, Job, evidence,
  obligation, and checkpoint references live in the adjacent bindings file
- Do not self-certify server guards or reconstruct evidence from stdout. A
  missing capability, invalid timing, or broken lifecycle is a platform gap,
  not a factor conclusion

## Research loop

1. Confirm material product and source choices with the user before planning
2. Read `cycle next`; let its packet select the required local decision or
   detailed contract
3. Create or update only the report components and chips requested by that
   packet; `cycle next --report-file` creates the chapter anchor idempotently
4. Validate locally, submit only the declared immutable run or transition, then
   observe its Job by `job_id`
5. Capture trusted Job evidence once and advance only through a declared edge

Keep signal availability, forward-return horizon, next-bar execution, costs,
capacity, margin, fee mode, universe/mask, sample roles, and selection history
explicit in the frozen run or TrialPlan rather than inferring them later.

## Progressive skill use

The Graph provides capability descriptions and descriptor hashes, not a
concrete skill identity. Match an already loaded fingerprint-valid skill first;
otherwise discover metadata, obtain any required approval in the current Agent
conversation, load only the selected skill, and record actual use with
`skill-usage record`. A historical record never authorizes changed skill
content.
