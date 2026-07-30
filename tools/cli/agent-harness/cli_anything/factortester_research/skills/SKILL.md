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
cli-anything-factortester-research cycle next <instance-id> <branch-id> --json
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
- `report`: create, add, batch, bind, validate, inspect, and render the
  current branch-owned Work Package report
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
- Reports are branch-owned Work Package trees. Rich prose is portable Markdown:
  it may contain inline code, inline/display LaTex, fenced code, and Markdown
  tables. Use typed `code`, `math`, `table`, `image`, and `result` components
  for standalone or bound content; never paste a JSON payload into prose
- Prefer a `list` component for three or more parallel findings, candidates,
  constraints, decisions, or next actions. Keep explanatory prose in short
  paragraphs; do not join independent claims into one dense paragraph
### Typed domain references

- The Agent alone decides whether prose denotes a domain object. When it does,
  the Agent writes the complete typed Markdown link:
  `[label](factortester://kind/<percent-encoded-target_ref>)`. The Agent supplies
  `kind`, exact `target_ref`, and display label; an alias, product symbol, or
  surrounding sentence is not an object identity.
- The CLI never generates or rewrites these links and never scans surrounding
  prose to infer an object. It only validates links the Agent explicitly
  submitted. Copy exact stable references from their owning Git, Profile
  registry, product catalog, Evidence, or Job response; never ask a resolver to
  guess one from a label or code.
- Canonical examples:
  - `[工业硅](factortester://product/Product%2FFutures%2FCNFutures%2F_products%2FSI.GFE)`
  - `[MaxA](factortester://profile/profile%3Amaxa)`
  - `[IC 证据](factortester://evidence/evidence%3Aic-2025)`
  - `[预测有效性义务](factortester://obligation/obligation%3Apredictive-validity)`
  - `[审阅任务](factortester://task/research-cycle-review%3Aabc)`
  - `[回测任务](factortester://job/job%3A123)`
  - `[SgCPS](factortester://factor_family/factor-family%3Av1%3Aprofile-maxa%3AY3VzdG9tX2ZhY3RvcnMvU2dDUFMucHk%3AU2dDUFM%3Abf7ae6d94a7c35d2280107d332dbaf04c4f50b07%3A1aa9a9908b8f1f034973ebfe5819115e13c16cde)`
- A `factor` or `factor_family` target must bind its committed Git revision and
  blob. A `profile_revision` target binds one frozen configuration; `profile`
  names the long-lived identity. Product, contract, and continuous-contract
  links use exact catalog paths and distinct kinds. Evidence and Job links use
  their stable server references. Obligation, Claim, and Task links use the
  exact IDs returned for the current Research Graph branch; copy them from the
  current cycle packet or object response and never derive them from the prose.
- If object identity or type is uncertain, retain ordinary prose or Markdown
  inline code and do not fabricate a link. Submission validates every explicit
  link against its owning authority and reports the component, field,
  line/column, rule, and corrective example without changing the authored
  Markdown.
- In Chinese report prose, wrap unresolved technical English tokens in Markdown
  inline code: factor aliases, fields, parameters, enum values, CLI
  commands/options, functions, expressions, product symbols, versions, and
  object/type names.
  Leave only genuine prose names such as authors, institutions, products, and
  framework names unformatted; never use backticks merely as emphasis
- Mandatory requirement and Job-result associations remain owned by their
  workflow; do not recreate them with a second loose sidecar document
- Link to a file already stored inside the current research Work Package with
  an ordinary descriptive Markdown link, for example
  `[核心信号审计](grill/2026-07-28-04-core-signal-over-modifiers.md)`. Never
  leave a portable research path as bare prose, expose an absolute local path,
  or use `..` to escape the Work Package
- Cite websites with a descriptive `http` or `https` Markdown link such as
  `[NautilusTrader 事件文档](https://nautilustrader.io/docs/latest/concepts/events/)`;
  do not leave a raw URL in prose
- Do not self-certify server guards or reconstruct evidence from stdout. A
  missing capability, invalid timing, or broken lifecycle is a platform gap,
  not a factor conclusion

## Research loop

1. Confirm material product and source choices with the user before planning
2. Read `cycle next`; let its packet select the required local decision or
   detailed contract
3. Add only the report components and bindings required by that node, scoped to
   its Profile, Work Package and branch; never create a loose report file
4. Validate locally, submit only the declared immutable run or transition, then
   observe its Job by `job_id`
5. Capture trusted Job evidence once and advance only through a declared edge

`cycle advance` is a thin adapter over
`factortester research-graph node advance`. Forward the packet-required
`--entry-assessment-file`, `--target-capability-resolution-file`,
`--profile-id`, `--agent-id`, `--narrative-file`, and `--release-profile`
options unchanged; the native CLI remains authoritative for report
synchronization and transition validation.

## Graph continuation with an open capability detour

Use the existing continuation path; do not invent a direct migration or edit
the research record:

```bash
factortester research-graph continuation-preview \
  <instance-id> <branch-id> --target-version <version>
factortester research-graph continue \
  <instance-id> <branch-id> --target-version <version> --yes
```

Read `agent_plan` from the preview or continuation result. For an open
capability detour, assess the current node's added or revised entry requirements
first. Retain the same capability-detour episode and its `resume_node`; this
current-node reentry is not a second detour. Complete the declared
capability-repair route, enter `capability_resolution`, and use only the
explicit resume edge returned by `cycle next`.

After the original node is restored, assess each remaining Graph-upgrade
requirement only when its owning node is entered. Never nest a second capability
detour inside the open episode. If a later node-local requirement needs another
gap, open it only after the earlier episode has closed.

Use the new physical branch IDs returned by continuation:

```bash
cli-anything-factortester-research cycle next \
  <target-instance-id> <target-branch-id> --json
```

The packet owns the exact assessment, report, and transition contracts. Do not
infer them from Graph version numbers or this Skill.

Do not create Graph-stage chapters yourself. `research-graph node advance`
creates or reuses the target substantive chapter and returns its
`local_report_publish.chapter_sync.component_id`. During a capability detour it
instead returns the single server-owned special nested under the resume-node
chapter; add subsequent node content only under the returned container.

Keep signal availability, forward-return horizon, next-bar execution, costs,
capacity, margin, fee mode, universe/mask, sample roles, and selection history
explicit in the frozen run or TrialPlan rather than inferring them later.

## Report authoring

The harness exposes the production `factortester report` command group. Every
write is scoped to a Profile, Work Package and branch; no `--file` report path
exists. Start from `report --help`, use JSON output, and validate after a
related batch.

```bash
factortester report create \
  --profile <profile> --work-package-id <package> --branch-id <branch> --json
factortester report add \
  --profile <profile> --work-package-id <package> --branch-id <branch> \
  --component-id finding --kind entry --parent-id <node-chapter> \
  --title '研究发现' --body-file finding.md --json
factortester report add \
  --profile <profile> --work-package-id <package> --branch-id <branch> \
  --component-id constraints --kind list --parent-id <node-chapter> \
  --title '研究约束' --item '2026 样本保持封存' \
  --item '费用与保证金写入冻结配置' \
  --item '每个窗口登记为独立试验' --json
factortester report add \
  --profile <profile> --work-package-id <package> --branch-id <branch> \
  --component-id formula --kind math --parent-id <node-chapter> \
  --title '信号公式' --latex 's_t = z_t / \\sigma_t' --json
factortester report validate \
  --profile <profile> --work-package-id <package> --branch-id <branch> --json
```

`finding.md` is rich Markdown, not a JSON transport. If a table needs a Job
artifact/source reference, write it as a typed `table` component rather than
embedding a JSON `columns`/`rows` object in the prose file.

If `report add` or `report add-batch` is rejected, read the structured
diagnostics and the returned pending submission sequence. Correct that same
logical component or batch, then repeat the command with
`--submission-sequence <sequence>`. Do not submit a different report change
while it is pending. A rejection leaves report HEAD unchanged; only the
accepted correction publishes that sequence and closes the pending submission.
The sequence is the branch's next target report generation, not a second
published version counter. After an interrupted Agent run, use `report show
--json` to recover `pending_submission.submission_sequence`, its diagnostics,
and the required retry action before attempting any report write.

## Progressive skill use

The Graph provides capability descriptions and descriptor hashes, not a
concrete skill identity. Match an already loaded fingerprint-valid skill first;
otherwise discover metadata, obtain any required approval in the current Agent
conversation, load only the selected skill, and record actual use with
`skill-usage record`. A historical record never authorizes changed skill
content.
