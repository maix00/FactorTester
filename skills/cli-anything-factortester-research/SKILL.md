---
name: factortester-research-skill
description: Use when conducting FactorTester research through its real CLI, Research Graph, Evidence, obligations, Jobs, and structured reports. Read the current server packet, make only genuine research decisions, and let the CLI derive mechanical transition fields.
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
evidence. Do not call `research step inspect` to discover the current action or
to read a TrialPlan. It applies only after the packet exposes a current
TrialPlan Evidence Action and explicitly directs the Agent to fetch that
action's missing input contract. In that case, read only its compact contract:

```bash
factortester research step inspect <instance-id> <branch-id> \
  --output current-action.json
```

The inspect response intentionally does not return the TrialPlan body. It owns
only the current Evidence Action identity, comparison roles, RunSpec hashes,
and operation payload contracts. Do not memorize edge-specific request JSON,
capability identifiers, products, or Graph version names in this Skill.

When a candidate Edge returns `action_contract.mode=automatic`, run the
ordinary `node advance` command without inventing an action request or calling
`research step inspect`. The server performs the declared binding itself.

## Command map

- `plan`, `workspace`, `run-step`: prepare a bounded research configuration and
  delegate to the real client
- `factortester research-graph`: read the current packet, inspect one declared
  object, validate and advance the bounded Research Cycle
- `factortester trial-plan`: validate, freeze, and read a direct TrialPlan
  without entering Research Graph
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
  HEAD together with either the server-owned Graph execution node or an
  explicit direct-report parent, waits by default, and creates one
  `test_result` special section. Read
  `report_collections[].report_follow_up.parent_id` and put the subsequent
  analysis under that exact parent. Use `--without-report` only when the Trial
  Job is intentionally outside every research report
- The Agent does not invent or pass `report_id`. For a report-bound Trial Job,
  the CLI reads `report_id` from the current branch report HEAD and freezes it
  together with the report generation, root reference, HEAD hash, and parent ID.
  If that complete identity cannot be frozen, do not claim automatic report
  mounting; either repair the report scope or explicitly use `--without-report`
- A Profile factor worktree is opt-in transient Run source. It is never silently
  synchronized into the canonical user factor library
- `StrategySpec` uses public templates or a `profile:<path>` Strategy Actor.
  Do not put Flow, StrategyBook, or policy implementation names in it

### Direct trials outside Research Graph

An Agent may run a bounded experiment without moving, satisfying, or otherwise
mutating Research Graph. This is a direct Trial, not a Graph transition:

1. Run `factortester run preview` and retain the returned frozen RunSpec hash
2. Author one TrialPlan whose comparison roles refer to that exact RunSpec
3. Freeze it with `factortester trial-plan create --trial-plan-file <plan.json>
   --run-spec-hash <hash> --trial-role <role> --comparison-id <id> --output
   <binding.json> --json`
4. Submit with `factortester run submit --trial-binding-file <binding.json>`

To place the terminal result in an existing research report, also pass
`--profile`, `--work-package-id`, `--branch-id`, and the explicit existing
`--report-parent-id`. The CLI freezes that parent with the report HEAD, waits
for the Job, and mounts one `test_result` special section under it. Continue
analysis under the returned `report_follow_up.parent_id`. Use
`--without-report` only for a deliberately unbound Job.

A direct TrialPlan cannot contain Graph action state and cannot satisfy Graph
Entry Requirements, obligations, report requirements, or Edge guards. Its
result carries stable Evidence, TrialPlan, and RunSpec links for later review;
admitting any of that Evidence into Graph remains a separate explicit action.
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
  Git revision.
- A multi-factor subject is a first-class `factor-set`, not a factor family and
  not a separately typed factor column. Create its named member manifest, commit
  it, and freeze the exact set version:
  ```bash
  factortester client profile factor-worktree factor-set create maxa \
    --set-id momentum-2025 --title-zh '2025年动量因子集合' \
    --description-zh '用于窗口参数比较' \
    --member-ref-file factor-members.json --json
  factortester client profile factor-worktree factor-set reference maxa \
    --set-id momentum-2025 --json
  ```
  Use the returned versioned `target_ref` in report, Evidence, obligation, and
  Edge scope. The stable `set_ref` names the long-lived set; it is not a frozen
  research scope. A member factor never implies coverage of the whole set.
  Reports bind only the frozen `target_ref`, stable `set_ref`, member count and
  member hash; they never copy the complete member manifest into report state.
  Resolve members only when needed, in bounded pages:
  ```bash
  factortester client profile factor-worktree factor-set members \
    --target-ref '<frozen-factor-set-ref>' --offset 0 --limit 50 --json
  ```
  Discover and inspect sets with `factor-set list maxa --json` and
  `factor-set show maxa --set-id momentum-2025 --json`; `show` returns only a
  compact summary, so use `members` for the paginated member list. Update a set
  only with `factor-set update ... --expected-member-hash '<current-hash>'`.
  Compare two frozen versions with `factor-set diff --from-target-ref ...
  --to-target-ref ... --json`. Never hand-edit a manifest or blindly replace a
  version whose current member hash was not read first.
  The manifest is an unordered set saved in canonical sorted order. Do not use
  its storage order as research meaning.
  Freeze a specific Profile configuration with
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
- A `factor` link target, whether it identifies a factor family, a parameterized
  factor expression, or a factor-set, must bind its committed Git revision and
  blob. A factor-set additionally binds the hash of its complete canonical
  member manifest; the CLI resolves that immutable manifest on demand.
  A `profile_revision` target binds one frozen configuration; `profile`
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

Any Evidence or EvidenceUse factor scope must use the exact frozen `target_ref`
returned by `factortester client profile factor-worktree reference` (or the
frozen factor-set reference command). Copy that reference verbatim into
`factor_refs`; display names and shortened identities are not object identity.

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

Prefer an existing external Web/API Evidence, then a real Terminal or Job
capture. A local file is eligible only when it freezes an authoritative
download with its public acquisition path, or a Git-tracked implementation
with repository, commit and blob identity. A download script, request manifest
or local cache accompanies the SourceCapture as provenance; it does not replace
the original content. Agent-authored reports, audit Markdown and copied command
output are report assets, never primary Evidence sources. Use
`research-evidence guide capture --json` for the current provenance contract.

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

Use only `factortester research-graph node advance` for Graph mutation. It rebuilds
the current node/edge contract immediately before submission, validates local
Research Cycle proposals, checks report coverage, and automatically binds
declared target-node capabilities. If the current node has unresolved Entry
Requirements, pass a not-yet-existing `--entry-assessment-file` path and
`--factor-family`; the first call writes the editable document and returns
`state_changed: false`. Complete every requested judgment and rerun the same
command. `node advance` validates and projects it before mutation. Pass
Profile/Agent, narrative, and release-Profile options when the packet requires
them. Do not call a second prepare, validate, or Harness advance wrapper.

Copy the current command only from `next_actions`; do not reconstruct it from a
previous attempt or from this Skill. The Agent supplies only genuine choices:
an ambiguous Edge and its reason, unresolved Entry assessments, an Evidence or
Job choice and its rationale, a `no_material_issue` judgment, or an ambiguous
capability binding. The Agent never writes `expected_base_hash`, a complete
`obligation_coverage_submission`, `coverage_hash`,
`data_availability_request`, a frozen availability-profile hash, or another
checkpoint-derived field. The CLI and server own those values. If a returned
action asks the Agent to copy one, stop and report a platform-contract defect
instead of satisfying it manually.

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
Read `change_contract` from `obligation status` before constructing the change.
The outer `research_cycle` transport is always schema version 1 and binds the
returned `parent_trace_ref`; an inner adjudication proposal may independently
be schema version 2. Never copy an inner object's version onto the envelope.
The CLI rejects a malformed envelope before it can enter the ledger, so repair
that same change submission before adding more report content or selecting an
Edge.
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
An Edge never reuses a previous coverage decision by status alone.  At every
advance, the CLI and server revalidate each mapped EvidenceUse against the
current non-superseded Claim scope and the server-owned branch admission.  A
factor- or product-specific EvidenceUse cannot support an obligation that did
not explicitly bind that typed subject through its own scope or linked Claims.
When the research subject changes, supersede or rescope the old Claim and
obligation, then record new EvidenceUse relations; do not rely on an earlier
`bounded`, `serviced`, or `discharged` state.  Missing coverage may be recorded
as human-authorized debt, but stale, mismatched, or unbound scope is an identity
error and is never bypassable.
`edge choose` requires a rich-text reason, records a path-selection special
section, and updates the current coverage table. `node advance` then reads the
ledger and injects exact obligation refs and a hash-bound coverage submission.
A Profile-bound research advance cannot bypass the ledger. A signed-in human
may authorize one node/checkpoint to tolerate missing report or Edge-obligation
coverage; the Agent cannot enable that mode. Even then, inspect the returned
coverage debt, keep the incomplete coverage table, and repair the source node
chapter with the returned `--target-chapter-id`. Structure, identity, hash,
reference, and special-section format gates remain mandatory. Never handwrite
`obligation_coverage_submission` or a duplicate coverage table.

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

Graph activation validates upgrade mechanics transactionally and leaves no
persistent validation Work Package. Do not create a research fork or temporary
Profile binding to validate an upgrade. After activation, continue the existing
logical Work Package and Hypothesis Branch with the commands above.

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

Structure nodes organize and nest the report: `chapter`, `section`,
`subsection`, and `special` require a meaningful `--title`. The title must
describe the subject; never use `正文`, `表格`, or `列表` as a structure title.
The same rule rejects the English placeholders `Body`, `Table`, and `List`.
Content components carry the report material: `entry`, `list`, `table`,
`image`, `code`, `math`, and `result` never carry `--title`. If content needs a
meaningful heading, create a `section` or `subsection` as its container, then
add titleless content beneath it. Raw Graph stack events such as entry
requirement push, resolve, resume, or abandon belong to the Graph timeline;
never copy their event JSON into the research report. For example:

```bash
factortester report create \
  --profile <profile> --work-package-id <package> --branch-id <branch> --json
factortester report add \
  --profile <profile> --work-package-id <package> --branch-id <branch> \
  --component-id findings --kind section --parent-id <node-chapter> \
  --title '研究发现' --json
factortester report add \
  --profile <profile> --work-package-id <package> --branch-id <branch> \
  --component-id finding --kind entry --parent-id findings \
  --body-file finding.md --json
factortester report add \
  --profile <profile> --work-package-id <package> --branch-id <branch> \
  --component-id prerequisite --kind entry --parent-id findings \
  --before-component-id finding --body-file prerequisite.md --json
factortester report add \
  --profile <profile> --work-package-id <package> --branch-id <branch> \
  --component-id constraints --kind list --parent-id findings \
  --item '2026 样本保持封存' \
  --item '费用与保证金写入冻结配置' \
  --item '每个窗口登记为独立试验' --json
factortester report add \
  --profile <profile> --work-package-id <package> --branch-id <branch> \
  --component-id formula --kind math --parent-id findings \
  --latex 's_t = z_t / \\sigma_t' --json
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
factortester report remove \
  --profile <profile> --work-package-id <package> --branch-id <branch> \
  --component-id incorrect-entry --json
factortester report validate \
  --profile <profile> --work-package-id <package> --branch-id <branch> --json
factortester report export \
  --profile <profile> --work-package-id <package> --branch-id <branch> \
  --format markdown --output ./research-report.md --json
factortester report export \
  --profile <profile> --work-package-id <package> --branch-id <branch> \
  --format pdf --output ./research-report.pdf --json
```

Every nested submission must name its actual `--parent-id`, including ordinary
sections nested in `grill_resolution` or `external_review`. Never infer the
parent from the previous write. If both `--parent-id` and
`--target-chapter-id` are omitted, the CLI writes a direct child of the report
tree's last chapter, regardless of whether Graph checks are active or bypassed.
Use the chapter ID to leave a special section and the special-section ID to
remain inside it. These labels are report presentation semantics, not Graph
nodes. They may nest when the source semantics require it.

To write into another chapter, pass its exact `--target-chapter-id`; to write
inside one of its containers, pass that container as `--parent-id`. To place a
new component immediately above or below an existing sibling, pass exactly one
of `--before-component-id` or `--after-component-id`. The anchor must already
belong to the same parent; the CLI never guesses a cross-container position.
To repair a requirement after a human-authorized advance, use the exact source
`--target-chapter-id` returned in `coverage_remediation`; do not guess from a
node title. An explicit target authorizes an insertion into that Graph node
chapter, not a move or replacement of historical content. Every
`report.requirement.*` repair must still use `--kind special`,
`--display-kind obligation_requirement`, and the matching
`--obligation-requirement-id`.

Use `report remove` only to correct Agent-authored ordinary content. A
non-empty ordinary container requires `--include-children`. The command always
rejects a chapter or special section, and recursively rejects an ordinary
subtree when any descendant at any depth is special. Move retained ordinary
children elsewhere before retrying; special sections remain system- or
domain-command-owned. Removal changes only the current report projection and
retains the prior content in Git history.

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

If the intended logical submission has been deliberately abandoned before its
report generation was published, use `factortester report abandon-pending`
with the same Profile, Work Package, and branch scope. This command is only for
`reserved` or `rejected` submissions: it restores any materialized business
sidecar to its committed base and releases the sequence. Never delete
`pending-submission.json`, edit a sidecar, or use this command for a
`published` submission; published content must use `report finalize-pending`.

## Progressive skill use

The Graph provides capability descriptions and descriptor hashes, not a
concrete skill identity. Match an already loaded fingerprint-valid skill first;
otherwise discover metadata, obtain any required approval in the current Agent
conversation, load only the selected skill, and record actual use with
`skill-usage record`. A historical record never authorizes changed skill
content.
