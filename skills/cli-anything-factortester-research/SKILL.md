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
factortester research-graph node info <instance-id> <branch-id>
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
- `factortester research-graph`: read the current packet, inspect one declared
  object, validate and advance the bounded Research Cycle
- `report`: create, add, batch, bind, validate, inspect, render, and export the
  current branch-owned Work Package report
- `evidence`: delegate to the native fragment-bound Evidence catalog
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
- A Trial Job that belongs in the active report must submit with `--profile`,
  `--work-package-id`, and `--branch-id`. The CLI freezes the local report
  HEAD together with the server-owned Graph execution node, waits by default,
  and creates one `test_result` special section. Read
  `report_collections[].report_follow_up.parent_id` and put the subsequent
  analysis under that exact parent. Use `--without-report` only when the Trial
  Job is intentionally outside every research report
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
- Freeze a committed Profile factor or factor family before writing its link:
  ```bash
  factortester client profile factor-worktree reference maxa \
    --source-file custom_factors/SgCPS.py \
    --identity 'SgCPS' --object-kind factor-family --json
  factortester client profile factor-worktree reference maxa \
    --source-file custom_factors/SgCPS.py \
    --identity 'SgCPS|P:[CA]|N:20d|$F:1m' --object-kind factor --json
  ```
  Use the returned `target_ref` verbatim in a `factortester://factor/` link.
  The command rejects untracked source and source that differs from the selected
  Git revision. Freeze a specific Profile configuration with
  `factortester client profile revision freeze <profile-id> --json`.
- Canonical examples:
  - `[工业硅](factortester://product/Product%2FFutures%2FCNFutures%2F_products%2FSI.GFE)`
  - `[MaxA](factortester://profile/profile%3Amaxa)`
  - `[IC 证据](factortester://evidence/evidence%3Aic-2025)`
  - `[预测有效性义务](factortester://obligation/obligation%3Apredictive-validity)`
  - `[审阅任务](factortester://task/research-cycle-review%3Aabc)`
  - `[回测任务](factortester://job/job%3A123)`
  - `[SgCPS](factortester://factor/factor-family%3Av1%3Aprofile-maxa%3AY3VzdG9tX2ZhY3RvcnMvU2dDUFMucHk%3AU2dDUFM%3Abf7ae6d94a7c35d2280107d332dbaf04c4f50b07%3A1aa9a9908b8f1f034973ebfe5819115e13c16cde)`
  - `[冻结运行配置](factortester://run_spec/runspec%3Asha256%3A0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef)`
  - `[试验计划](factortester://trial_plan/trial-plan%3Asha256%3A0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef)`
- A `factor` link target, whether it identifies a factor family or a
  parameterized factor expression, must bind its committed Git revision and
  blob. A `profile_revision` target binds one frozen configuration; `profile`
  names the long-lived identity. Product, contract, and continuous-contract
  links use exact catalog paths and distinct kinds. Evidence and Job links use
  their stable server references. Obligation, Claim, and Task links use the
  exact IDs returned for the current Research Graph branch; copy them from the
  current cycle packet or object response and never derive them from the prose.
- Copy `trial_plan_refs` and `run_spec_refs` from
  `factortester client research timeline <work-package-ref> <branch-id> --json`.
  Inspect the exact checkpoint-bound body with
  `factortester research-graph cycle-object <instance-id> <branch-id>
  trial_plan|run_spec <object-id> --trace-id <trace-id>`. A RunSpec target is
  always `runspec:sha256:<run_spec_hash>`; a TrialPlan target is the exact
  `trial-plan:` reference returned by the timeline.
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

### Fragment-bound Evidence

Formal obligations are drafted by the main Research Agent. Freeze that draft
before requesting the current requirement subclasses or reusable Evidence.
An isolated reviewer may critique the draft afterward, but cannot create the
formal obligation.

Do not treat a Job, terminal execution, file, or webpage as Evidence by itself.
The stable chain is:

```text
SourceCapture -> SourceFragment -> Evidence -> EvidenceUse
```

Every Evidence must identify one or more exact fragments. Every EvidenceUse
must bind that Evidence to an obligation and one or more requirement
subclasses, state why it applies, and freeze the server-checked scope and
qualification. Agent tags are retrieval aids only; they never change Evidence
identity, scope, or Graph admission.

Do not memorize the mutable command schema in this Skill. Ask the native CLI
for the current contract and execute its returned `next_actions`:

```bash
factortester research-evidence guide --json
factortester research-evidence guide search --json
```

Search by product, committed factor version, sample and time window before
using system facets or Agent tags. Reuse compatible Evidence before capturing
a new source. When no compatible Evidence exists, capture one immutable source,
select a precise fragment, compose Evidence, and only then bind it through
`research-graph obligation change`.

Before proposing a new tag, list existing tags and use `tag propose`. Create
only with the returned revision-bound token. Similar tags require an explicit
distinction reason. Keep tag titles short and descriptions useful for future
retrieval.

Exclude Evidence only through the native lifecycle command. It requires the
current Graph branch, Agent, and an explicit report `parent_id`; the CLI removes
that Evidence's current branch-local EvidenceUse relations, recomputes
obligation coverage, and records the ruling and its reason in the same report
and Git transaction. An excluded Evidence remains readable through existing
typed links but is hidden from ordinary search and cannot be newly admitted or
reused. Use `guide exclude` for the current contract and
`search --include-excluded` only for an explicit audit. Restoring discovery
never restores removed EvidenceUse relations.

## Research loop

1. Confirm material product and source choices with the user before planning
2. Read `factortester research-graph node info`; let its packet select the
   required local decision or detailed contract
3. Add only the report components and bindings required by that node, scoped to
   its Profile, Work Package and branch; never create a loose report file
4. Validate locally, submit only the declared immutable run or transition, then
   observe its Job by `job_id`
5. Capture trusted Job evidence and finish the intended work in the current
   node before selecting an outward Edge
6. Compare the then-current Edge candidates, record the path rationale, satisfy
   the selected Edge's additional obligation categories, and advance

Use only `factortester research-graph node advance` for mutation. It rebuilds
the current node/edge contract immediately before submission, validates local
Research Cycle proposals, checks report coverage, and automatically binds
declared target-node capabilities. If the current node has unresolved Entry
Requirements, pass a not-yet-existing `--entry-assessment-file` path and
`--factor-family`; the first call writes the editable document and returns
`state_changed: false`. Complete every requested judgment and rerun the same
command. `node advance` validates and projects it before mutation. Pass
Profile/Agent, narrative, and release-Profile options when the packet requires
them. Do not call a second prepare, validate, or Harness advance wrapper.

### Entry Requirement, obligation, and report invariants

Keep these Graph contracts distinct:

- `requirement_catalog.categories[].category_id` is one stable, coarse
  Verification Obligation category.
- `requirement_catalog.requirements[].requirement_id` is a versioned Entry
  Requirement subclass under exactly one category. A node exposes only its
  active subclasses; load a selected requirement by ID instead of loading or
  guessing the complete catalog.
- A branch-local Verification Obligation is concrete research state proposed by
  the Agent and accepted through Research Cycle adjudication. The Agent selects
  exactly one existing category, or `other` when none fits. Category and
  `obligation_kind` define the obligation itself; mutable
  `from_requirement_refs` / `to_requirement_refs` separately declare which
  active Entry Requirement subclasses that obligation currently covers.
- An Entry Requirement assessment must cover every active subclass with
  applicability, a category-compatible mapping to concrete obligations or a
  fact-bound non-material decision, a resolution route, and an entry effect.
  The server issues an eligible or limited receipt only after validating that
  coverage decision.
- A receipt is reusable only while the Graph requirement revision and semantic
  hash, referenced obligations, evidence scope, Research Contract, Methodology,
  and checkpoint inputs remain unchanged.
- A Report Requirement is an independent output contract. Satisfying its report
  item never discharges an Entry Requirement or Verification Obligation, and an
  eligible Entry Requirement receipt never satisfies report coverage.

Therefore an outward Edge validates both semantic Entry Requirement coverage
through server-issued receipts and the declared Report Requirements. Edge
obligation categories may add to, rather than duplicate, the node Entry
Requirements. It does not ask the Agent to copy the catalog, and it does not
infer obligation coverage from prose, headings, or a completed report item.

Use the branch-local ledger commands in this order:

```bash
factortester research-graph obligation status \
  <instance-id> <branch-id> --profile-id <profile> --agent-id <agent>
factortester research-graph obligation change \
  <instance-id> <branch-id> --profile-id <profile> --agent-id <agent> \
  --change-file <accepted-obligation-change.json>
factortester research-graph edge choose \
  <instance-id> <branch-id> <edge-id> \
  --profile-id <profile> --agent-id <agent> \
  --reason-file <portable-markdown>
```

Do not choose an Edge when entering a substantive research node. First finish
the Entry Requirements and the research you intend to conduct in that node,
then explicitly begin the departure phase and choose the Edge using the latest
evidence and obligations. A single candidate is only a preview, not permission
to freeze it early. Automatic early selection is allowed only when the Graph
contract explicitly marks a node as pure routing; candidate count alone is not
such a contract.

A material capability blocker is the explicit exception. Do not pretend the
interrupted node is complete. Record the blocking fact and obligation change,
use the declared failure/capability-detour Edge immediately, and let the
assessment route unresolved work to `capability_gap` or
`capability_resolution`. Normal source-node exit report requirements are not
required for this interruption; the failure Edge and detour-entry report
requirements still are. The detour keeps one `resume_node`, and recovery must
use its explicit resume Edge to return there before substantive research
continues.

The change file must include non-empty portable Markdown in `reason_markdown`
and an explicit `evidence_use_delta` array. Each added EvidenceUse contains the
exact Evidence reference and short Chinese title, obligation reference,
covered requirement references, Chinese use rationale, qualification, and
scope-match snapshot. Use an empty array only when the change genuinely adds
or removes no evidentiary support.
`obligation change` writes the accepted Research Cycle delta and one obligation
change special section in one Git commit. The special contains the change table,
the authored explanation, a default-collapsed current-obligation table, and a
default-collapsed union table that marks node Entry and selected-Edge sources
separately.
The coverage relation is many-to-many: one obligation may cover several
requirement subclasses from the current node or selected Edge, and one subclass
may be supported by several obligations. Always submit the complete
`from_requirement_refs` and
`to_requirement_refs` for each changed obligation; never collapse the relation
to one obligation or one subclass.
`edge choose` requires a rich-text reason, records a path-selection special
section, and updates the current coverage table. `node advance` then reads the
ledger, injects exact obligation refs and a hash-bound coverage submission,
and refuses missing coverage. A Profile-bound research advance cannot bypass
the ledger. Never handwrite `obligation_coverage_submission` or a duplicate
coverage table.

When analysis focuses on one requirement category, add a nested special using
`--display-kind obligation_requirement --obligation-requirement-id <id>`.
The referenced category may come from the node Entry Requirements, the selected
Edge requirements, or both. Keep its explicit `parent_id`; never infer the
container from the previously written report item.

## Graph continuation with an open capability detour

Use the existing continuation path; do not invent a direct migration or edit
the research record:

```bash
factortester research-graph continuation-preview \
  <instance-id> <branch-id> --target-version <version>
factortester research-graph continue \
  <instance-id> <branch-id> --target-version <version> --yes
```

For proposal-bound shadow validation, pass the exact shadow Run/proposal and
the owning Profile/Agent to the same continuation command. The CLI creates an
isolated local shadow Work Package for report authoring while preserving the
live Agent scope and live research record.

Read `agent_plan` from the preview or continuation result. For an open
capability detour, assess the current node's added or revised entry requirements
first. Retain the same capability-detour episode and its `resume_node`; this
current-node reentry is not a second detour. Complete the declared
capability-repair route, enter `capability_resolution`, and use only the
explicit resume edge returned by `factortester research-graph node info`.

After the original node is restored, assess each remaining Graph-upgrade
requirement only when its owning node is entered. Never nest a second capability
detour inside the open episode. If a later node-local requirement needs another
gap, open it only after the earlier episode has closed.

Use the new physical branch IDs returned by continuation:

```bash
factortester research-graph node info \
  <target-instance-id> <target-branch-id>
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
factortester report add \
  --profile <profile> --work-package-id <package> --branch-id <branch> \
  --component-id grill-decision --kind special \
  --display-kind grill_resolution --parent-id <node-chapter> \
  --title 'Grill 决议：方向门控' --json
factortester report add \
  --profile <profile> --work-package-id <package> --branch-id <branch> \
  --component-id external-audit --kind special \
  --display-kind external_review --parent-id grill-decision \
  --title '外部审计：门控边界' --json
factortester report validate \
  --profile <profile> --work-package-id <package> --branch-id <branch> --json
factortester report export \
  --profile <profile> --work-package-id <package> --branch-id <branch> \
  --format markdown --output ./research-report.md --json
factortester report export \
  --profile <profile> --work-package-id <package> --branch-id <branch> \
  --format pdf --output ./research-report.pdf --json
```

Every non-chapter submission must name its actual `--parent-id`, including
ordinary sections nested in `grill_resolution` or `external_review`. Never
infer the parent from the previous write: use the chapter ID to leave a special
section and the special-section ID to remain inside it. These two labels are
report presentation semantics, not Graph nodes. They may nest when the source
semantics require it.

`report export` renders the current validated tree in memory before writing the
requested destination; it never edits the report source or materialized branch
report. PDF export requires the signed native renderer shipped beside the
frozen FTClient CLI. The macOS UI invokes this command and does not maintain a
second report renderer.

When opening a Grill resolution or an external review, the Agent must create
the container itself with `--kind special` and the matching `--display-kind`.
Do not publish that container as an ordinary section, subsection, or entry.
Put its ordinary child material under the returned special component ID. A
Grill child may itself be an `external_review`, and either may contain another
registered special when the reviewed source semantics require nesting.

Wrap technical identifiers containing underscores, such as `cs_rank` and
`cs_ordinal_rank(mask, ascending)`, in inline code unless they are genuine
mathematical notation inside `\(...\)`. The CLI rejects an unformatted
identifier with its component, field, line, column, rule and correction
example.

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
