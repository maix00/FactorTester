---
name: factortester-research-skill
description: Use when conducting FactorTester research through its real CLI, Research Graph, Evidence, obligations, Jobs, and structured reports. Read the current server packet, make only genuine research decisions, and let the CLI derive mechanical transition fields.
---

# FactorTester Research Harness

Use this harness for factor research through the real FactorTester backend. It
is an execution aid, not a copy of the Active Graph or a source of current
research facts.

Always invoke the installed `factortester` executable for native operations.
Never run `python -m tools.cli.app`: that bypasses the installed launcher and
can import stale code from the current source worktree.

When this Skill runs inside a Manager-owned server Profile Agent, the Manager
injects a short-lived local FactorTester capability and the matching 7998
endpoint into the Agent environment. Do not run `factortester configure`,
`factortester login`, or copy browser cookies in that context; the installed
CLI uses the injected capability automatically. A normal client or standalone
terminal still follows the explicit configure/login setup below.

When the Web page opens this Profile as its assistance Agent, use
`factortester assist inspect` to read the page-registered schema, complete
structured document and optimistic revision. Prepare the entire document,
retain it with `factortester assist drafts create --stdin`, validate the returned
ID with `factortester assist drafts validate <draft-id>`, then atomically apply
it with `factortester assist drafts apply <draft-id>`. Do not write candidate
files directly into the Profile root or `/tmp`. Never fill the page one field at a time, manipulate
DOM, or invent fields outside the published schema. A revision conflict means
the person edited the page; inspect again instead of overwriting them.

## Current local-first boundary

The Manager does not own the Research Graph state or decide graph transitions.
A server Profile Agent may run the installed CLI, but Research Graph sessions,
edge selection, evidence judgments, obligations, report authoring, and locally
selected test execution still belong to the local research workspace and must
continue when the Manager is offline. Download a graph YAML/version from the
Manager when available, then use the local graph store and
`factortester research graphs next-local` to evaluate candidate edges. Do not
wait for a server packet to decide the next action.

The server-side Graph instance/branch commands documented below are retained
only as compatibility imports for existing shared progress and remote Jobs;
they are not the source of truth for a new offline research session. A shared
report is still edited locally. `factortester research reports publication publish`
persists a source-free projection and its 7997 objects in the local outbox;
`factortester research reports publication sync` flushes it when a connection returns.
Unshared local facts and session state never enter that outbox.

## Start and discover the current action

Use an explicit local session and JSON output:

```bash
cli-anything-factortester-research \
  --session /path/to/research-session.json doctor --json
factortester research graphs next-local \
  --graph-file /path/to/graph.yaml --current-node entry --json
```

The downloaded graph and local session are authoritative for the current node,
candidate edges, blockers, obligations, report tasks, and whether Agent
judgment is needed. Do not ask a Manager to calculate the next step. Load only
the local graph document and the evidence/facts needed by the current node.
`research step inspect` is the bounded, on-demand contract reader for an edge
that declares a server action; it is not an alias for offline graph navigation.
Use it only when `research graphs node info` returns that exact next action.

```bash
factortester research graphs next-local \
  --graph-file graph.yaml --current-node validation_design --json
```

The local evaluator returns candidate edges and deterministic blockers; the
Agent chooses an edge when the result is ambiguous and records that choice in
the local session. A remote Job submission may still be validated by the
selected server, but the server does not own the research transition.

## Command map

- `plan`, `workspace`, `run-step`: prepare a bounded research configuration and
  delegate to the real client
- `factortester research graphs`: download a graph and evaluate the next local
  edge from the local session and facts
- `factortester trial-plan`: validate, freeze, and read a direct TrialPlan
  without entering Research Graph
- `report`: create, add, batch, bind, validate, inspect, render, and export the
  current branch-owned Work Package report
- `evidence`: delegate to the native fragment-bound Evidence catalog
- `graph`: inspect a graph or resolve a locally approved implementation
- `strategy`: list public templates and validate a `StrategySpec`
- `skill-usage`: record actual, approved skill use locally
- `gap`, `operator`, `service`: route platform gaps and source-owner work

### Server and release boundary

The research Skill does not own server maintenance, Manager authentication,
or client publication. If a research run exposes a platform gap or a source
fix is required, record the gap and route it to the registered `$factortester-server-maintenance` Skill. Its canonical repository source is
`server/skills/factortester-server-maintenance/`; read
`references/infrastructure.md` when Docker, WireGuard, SSH publication, or
public/container release state is involved.

The separate `factortester-manager` executable is reserved for that
maintenance/operator boundary. Do not invoke it from a research workflow,
and do not treat the research CLI's session as Manager authority. A
maintenance operator obtains target-specific access metadata with
`factortester-manager server access --json`; do not infer a host transport or
copy connection details into this research Skill.

Use `--help` or `<group> --help` for stable command syntax. Use `--json` for
machine consumption; parse structured output, never CLI prose.

The server factor library uses the same business hierarchy and permission
projection as Web and Swift:

```bash
factortester factor-library families --scope all --json
factortester factor-library factors --scope mine --json
factortester factor-library factor-sets --scope subordinates --json
```

`families`, `factors`, and `factor-sets` read the Manager-owned public, own,
and direct-subordinate scopes. Never use the removed parameter-configuration
store or the internal client SQLite store as a factor-library reader. A
Profile's local factor source is its own
`factor-worktree`; a server Profile has the same workspace layout.

The Profile worktree is an ordinary Git worktree on `agent/<profile>`. Edit
and commit factor-family source on that branch. Publishing must preserve the
database synchronization boundary in this exact order: refresh `download` from the database factor library; merge `download` into `upload` and stop on any
conflict; merge the committed `agent/<profile>` branch into `upload` and stop on
any conflict; only then allow the existing `upload` hook to synchronize back to
the database factor library. Never edit `download`, bypass either merge, or use
hidden bootstrap commands as a second workspace protocol.

Every test-created factor family, factor, and factor set must remain
auditable and be submitted atomically in its ResearchConfiguration, immutable
RunSpec, and Job. A Profile
may additionally document those objects anywhere appropriate in its own
research worktree; do not impose a second manifest format. Only the `self`
Profile may run `factor-library workspace user download|upload` or promote
objects into the user's database factor library. Other Profiles commit
proposals only to their own `agent/<profile>` worktree for later user review.
A member factor never implies coverage of the whole set: preserve the explicit
factor-set identity and its flattened immutable member references together.

## Ownership and safety boundaries

- Workspace is editable configuration; `ResearchRun` owns an immutable RunSpec;
  `Job` owns lifecycle, result, and artifact state. Observe, cancel, and retry
  by `job_id`, never `page_uuid`
- Call `run preview` before `run submit`; the local client freezes the resolved
  configuration. A remote server validates only the submitted Job contract.
- Before submitting a Job, inspect the server-owned output catalog instead of
  memorizing output names:
  ```bash
  factortester job output-capabilities --json
  ```
  Request applicable outputs with repeatable `run submit --output <name>`
  options. IC Jobs must retain report-ready IC sequence and statistics
  artifacts; the standard outputs are `ic_series` and `ic_statistics`. After a
  completed Job whose retained sources still support the requested output, use
  `factortester job generate <job-id> --output <name>` to generate it later.
  Read and download the resulting Job artifacts through the Job commands; do
  not replace Job artifacts with terminal summaries or Agent-authored tables.
- A Trial Job that belongs in the active report must submit with `--profile`,
  `--work-package-id`, and `--branch-id`. The local client freezes the local
  report HEAD together with the local Graph node or an explicit direct-report
  parent, waits by default, and creates one
  `test_result` special section. Read
  `report_collections[].report_follow_up.parent_id` and put the subsequent
  analysis under that exact parent. Use `--without-report` only when the Trial
  Job is intentionally outside every research report
- The Agent does not invent or pass `report_id`. For a report-bound Trial Job,
  the CLI reads `report_id` from the current branch report HEAD and freezes it
  together with the report generation, root reference, HEAD hash, and parent ID.
  If that complete identity cannot be frozen, do not claim automatic report
  mounting; either repair the report scope or explicitly use `--without-report`
- A Profile factor worktree is opt-in Run-scoped source. It is never silently
  synchronized into the canonical user factor library. The submitted source is
  retained as an immutable Job input after the Job reaches a terminal state;
  it is removed only when the user clears that Job's files
- `StrategySpec` uses public templates or a `profile:<path>` Strategy Actor.
  Do not put Flow, StrategyBook, or policy implementation names in it
- Attach future strategy configuration, data mapping, documentation, or another
  bounded text dependency with repeatable
  `--run-input [purpose=]path` on both `run preview` and `run submit`. Valid
  purposes are discoverable from `--help`; for example:
  ```bash
  factortester run preview --analysis backtest \
    --run-input strategy_configuration=cost-model.yaml
  factortester run submit --analysis backtest \
    --run-input strategy_configuration=cost-model.yaml
  ```
  These files are retained beside generated Job artifacts and remain
  downloadable from Job detail until the user clears the Job files. A generic
  `.py` dependency is data, not executable authority; executable custom strategy
  code still requires the validated Strategy Actor source and `StrategySpec`

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

- Apply typed-reference rules to every Markdown-bearing location: chapter,
  section, and special-section titles; prose; list items; table headers and
  cells; captions; result analysis; and nested components. Whenever a factor,
  factor-set, product, contract, continuous contract, Evidence, Job, RunSpec,
  TrialPlan, obligation, requirement, Claim, Task, Profile, or Profile revision
  is mentioned as an object, use its validated reader-facing link.
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
- Resolve reusable factors and factor sets through the user-visible business
  catalog: `factortester factor-library factors --json` and
  `factortester factor-library factor-sets --json`. Copy returned v2 refs
  verbatim; never derive object identity from a label.
- A test may create a factor family, factor, or factor set in the current
  ResearchConfiguration. Put those objects in `temporary_objects`, reference
  their v2 refs from the test configuration, and submit them atomically with
  the RunSpec. Nested factors must be flattened into the frozen input. This
  does not create a Profile-local factor-set manifest. Register an object in
  the user database library only when the user requests later reuse.
  Product-group applicability is a separate registry relation owned by each
  product group. A factor or factor-set manifest never stores
  `product_group_refs`. Read and change that relation only through the native
  product-group CLI:
  ```bash
  factortester products groups subjects list \
    product-group:<id> --json
  factortester products groups subjects add \
    product-group:<id> --factor-ref '<stable-factor-ref>' \
    --factor-set-ref '<stable-factor-set-ref>' --json
  factortester products groups subjects remove \
    product-group:<id> --factor-ref '<stable-factor-ref>' \
    --factor-set-ref '<stable-factor-set-ref>' --json
  ```
  One subject may be associated independently with several product groups;
  those groups are not combined into a union. Research-local work does not
  duplicate or silently modify this registry. A TrialPlan or RunSpec freezes
  the exact product-group and factor/factor-set references selected for that
  trial. Change the shared association only when the user explicitly intends
  to persist it beyond the current research trial.
  Registration and association are separate operations. Persist the factor or
  factor set in the user database library before adding a durable association.
  A temporary set submitted with one Job remains visible through that frozen
  Job/RunSpec only and must not be mistaken for a registered library object.
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
  `factortester research workspaces timeline <work-package-ref> <branch-id> --json`.
  Inspect the exact checkpoint-bound body with
  `factortester research graphs cycle-object <instance-id> <branch-id>
  trial_plan|run_spec <object-id> --trace-id <trace-id>`. A RunSpec target is
  always `runspec:sha256:<run_spec_hash>`; a TrialPlan target is the exact
  `trial-plan:` reference returned by the timeline.
- If object identity or type is uncertain, do not use inline code as a fallback
  and publish the unresolved object. Query the owning CLI for the stable
  reference. If it remains unresolved, rewrite the statement so it does not
  claim that object identity or report the resolution gap before publishing.
  Never fabricate a link. Submission validates every explicit link against its
  owning authority and reports the component, field, line/column, rule, and
  corrective example without changing the authored Markdown.
- Never expose an Evidence, Job, RunSpec, TrialPlan, obligation, Claim, Task,
  Profile, factor, or requirement `target_ref` as ordinary prose or inline
  code. Never paste its SHA-256 or Git blob hash in place of a reader-facing
  reference. Use the object's short Chinese title as the Markdown label and put
  the complete immutable identity only in the typed link target. Report
  preflight rejects raw stable references and reader-facing 40/64-character
  hashes in titles, prose, lists, and tables. Fenced code may retain hashes only
  when the hash is genuinely part of executable code or captured protocol
  output, not as a substitute for an object link.
- Classify every technical span in this order:
  1. A domain-object identity uses its validated typed link. This rule wins
     over code formatting: a factor name or product symbol that denotes the
     object is not inline code.
  2. A mathematical variable, relation, or formula uses inline `\(...\)` or
     display `\[...\]` LaTeX. Mathematical notation is not inline code, and an
     object name does not become math merely because it appears beside a
     formula.
  3. A literal field, function, CLI parameter, enum value, or executable syntax
     uses Markdown inline code or a fenced code block.
  4. Genuine prose remains plain text; never use backticks merely as emphasis.
  For example, a referenced `MmTrend` factor is a typed factor link, `CLOSE` as
  a literal input field and `cs_rank(mask=eligible)` as executable syntax are
  inline code, and `\(O_t/C_{t-1}-1\)` is inline mathematics.
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

Any Evidence or EvidenceUse factor scope must use an exact frozen `factor_ref`
from a Job/RunSpec, the user-visible factor library, or an atomically submitted
temporary test object. Copy the reference verbatim into `factor_refs`; display
names and shortened identities are not object identity.

Do not fall back to an older commit when the selected revision lacks that
factor. Factor-family references are navigation objects only and cannot replace
the concrete `factor_ref` in a Trial, EvidenceUse, or Graph transition.

Do not memorize the mutable graph schema in this Skill. Ask the local CLI for
the current graph contract and let it evaluate the local YAML:

```bash
factortester research graphs next-local --graph-file <graph.yaml> --current-node <node>
factortester research evidence guide --json
factortester research evidence guide search --json
```

Search by product, committed factor version, sample and time window before
using system facets or Agent tags. Reuse compatible Evidence before capturing
a new source. When no compatible Evidence exists, capture one immutable source,
select a precise fragment, compose Evidence, and only then bind it through
`research graphs obligation change`.

Prefer an existing external Web/API Evidence, then a real Terminal or Job
capture. A local file is eligible only when it freezes an authoritative
download with its public acquisition path, or a Git-tracked implementation
with repository, commit and blob identity. A download script, request manifest
or local cache accompanies the SourceCapture as provenance; it does not replace
the original content. Agent-authored reports, audit Markdown and copied command
output are report assets, never primary Evidence sources. Use
`research evidence guide capture --json` for the current provenance contract.

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

## Work Package research-method memory

At the start of work in each research Work Package, create or reuse this
Git-tracked, Work Package-local Skill:

```text
research-methods/
├── SKILL.md
└── references/
    └── <method-slug>.md
```

Keep `research-methods/SKILL.md` short. Use it only to describe when this local
memory applies and to route the Agent to the relevant files under
`research-methods/references/`. Do not register this Work Package-local Skill globally,
copy it into the Profile Skill registry, or treat it as authority for another
research Work Package.

Store each method at `research-methods/references/<method-slug>.md` using a
short, stable, descriptive slug.

Create or update one method file when the main Research Agent or an external
reviewer recommends a method that materially affects the research design. Each
record must state the method, who recommended it, the recommendation source,
its applicable subject and sample boundary, expected benefit, limitations or
invalidation conditions, adoption status, and the related typed Evidence, Job,
TrialPlan, RunSpec, factor, or product links when they exist. Preserve rejected
or retired methods with their reason instead of silently deleting the decision
history. Do not copy large command output or Evidence payloads into this memory.

Before applying a recorded method, read its file and make an independent
current-scope judgment. In the report item that adopts, modifies, or rejects the
method, include an ordinary relative Markdown link to that Work Package file
and state why it applies to the current research decision. For example:

```markdown
采用[逐期手续费归因](research-methods/references/per-period-fee-attribution.md)，
因为本轮需要区分每分钟毛收益、持仓变化与双边手续费，而按日聚合会掩盖该关系。
```

Do not publish only a bare method link: the report must contain the Agent's
current reason and scope. The method file is rationale memory, not primary Evidence,
an obligation receipt, a Graph node, or permission to bypass a current
contract. Cite the underlying fragment-bound Evidence separately whenever the
method supports a factual claim. Ensure the method file is inside the current
Work Package and Git-tracked before publishing the report link.

## Research loop

1. Confirm material product and source choices with the user before planning
2. Read the downloaded Graph with `factortester research graphs next-local`; let
   the local result select the required decision or detailed contract
3. Add only the report components and bindings required by that node, scoped to
   its Profile, Work Package and branch; never create a loose report file
4. Validate locally, submit only the declared immutable run or transition, then
   observe its Job by `job_id`
5. Capture trusted Job evidence and finish the intended work in the current
   node before selecting an outward Edge
6. Compare the then-current Edge candidates, record the path rationale, satisfy
   the selected Edge's additional obligation categories, and advance

Persist Graph mutation through the local session store. The local CLI validates
the selected edge, evidence and report bindings before recording the transition.
If a remote Job is needed, submit it separately and keep only its immutable Job
reference in the local session. Do not call a server endpoint to advance the
research graph.

Do not copy a command from a server `next_actions` field. Use the local graph
evaluation and current evidence to decide the next operation. The Agent supplies only genuine choices:
an ambiguous Edge and its reason, unresolved Entry assessments, an Evidence or
Job choice and its rationale, a `no_material_issue` judgment, or an ambiguous
capability binding. The Agent never writes `expected_base_hash`, a complete
`obligation_coverage_submission`, `coverage_hash`,
`data_availability_request`, a frozen availability-profile hash, or another
checkpoint-derived field. The local CLI owns those values. If a remote server
asks the Agent to copy a server-generated next action, stop and report a
platform-contract defect instead of satisfying it manually.

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
factortester research graphs obligation status \
  <instance-id> <branch-id> --profile-id <profile> --agent-id <agent>
factortester research graphs obligation change \
  <instance-id> <branch-id> --profile-id <profile> --agent-id <agent> \
  --change-file <accepted-obligation-change.json>
factortester research graphs edge choose \
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
An Edge never reuses a previous coverage decision by status alone. At every
local advance, the CLI revalidates each mapped EvidenceUse against the current
non-superseded Claim scope and local branch admission. A
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

## Graph version changes and local continuation

When a newer Graph version is available, download it explicitly and inspect its
local topology before changing the local session. The client records the graph
reference and a local continuation event; there is no server-side continuation
preview, approval, Agent plan, or persistent branch migration. Keep unresolved
capability detours in the local session and do not ask a Manager to manufacture
the next edge or report parent.

## Direction metadata and sign-transform audit

Declare `expected_sign` for the final resolved factor expression in the
TrialPlan. It is directional audit metadata: `+1` means positive IC is
expected and `-1` means negative IC is expected. For valid IC observations,
the basic consistency diagnostic is
`direction_rate = mean(expected_sign * IC_t > 0)`; zero IC is not a hit.

Do not confuse this metadata with `$Rev`. `$Rev` is an expression modifier that
negates the resolved factor value. With the same forward-return label,
`IC_$Rev = -IC_raw`; it changes the observed IC sign, while `expected_sign`
does not transform factor values, IC values, or half-life inputs. Resolve the
complete `factor_ref` first and attach the declared direction to that final
expression. Never infer the final hypothesis from an alias substring alone.
If a legacy diagnostic maps an alias containing `$Rev` to `expected_sign = -1`,
label that mapping as diagnostic-only rather than treating it as the final
factor's required sign.

Use direction consistency as a diagnostic alongside signed `mean_ic`, HAC
uncertainty, and a paired raw-versus-`$Rev` sign audit. It is not a universal
hard gate before the first experiments. Holding-period half-life fitting must
remain independent of `expected_sign` and use the observed baseline direction.

Keep signal availability, forward-return horizon, next-bar execution, costs,
capacity, margin, fee mode, universe/mask, sample roles, and selection history
explicit in the frozen run or TrialPlan rather than inferring them later.

## Report authoring

The harness exposes the production `factortester research reports` command group. Every
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
factortester research reports create \
  --profile <profile> --work-package-id <package> --branch-id <branch> --json
factortester research reports add \
  --profile <profile> --work-package-id <package> --branch-id <branch> \
  --component-id findings --kind section --parent-id <node-chapter> \
  --title '研究发现' --json
factortester research reports add \
  --profile <profile> --work-package-id <package> --branch-id <branch> \
  --component-id finding --kind entry --parent-id findings \
  --body-file finding.md --json
factortester research reports add \
  --profile <profile> --work-package-id <package> --branch-id <branch> \
  --component-id prerequisite --kind entry --parent-id findings \
  --before-component-id finding --body-file prerequisite.md --json
factortester research reports add \
  --profile <profile> --work-package-id <package> --branch-id <branch> \
  --component-id constraints --kind list --parent-id findings \
  --item '2026 样本保持封存' \
  --item '费用与保证金写入冻结配置' \
  --item '每个窗口登记为独立试验' --json
factortester research reports add \
  --profile <profile> --work-package-id <package> --branch-id <branch> \
  --component-id formula --kind math --parent-id findings \
  --latex 's_t = z_t / \\sigma_t' --json
factortester research reports add \
  --profile <profile> --work-package-id <package> --branch-id <branch> \
  --component-id grill-decision --kind special \
  --display-kind grill_resolution --parent-id <node-chapter> \
  --title 'Grill 决议：方向门控' --json
factortester research reports add \
  --profile <profile> --work-package-id <package> --branch-id <branch> \
  --component-id external-audit --kind special \
  --display-kind external_review --parent-id grill-decision \
  --title '外部审计：门控边界' --json
factortester research reports remove \
  --profile <profile> --work-package-id <package> --branch-id <branch> \
  --component-id incorrect-entry --json
factortester research reports validate \
  --profile <profile> --work-package-id <package> --branch-id <branch> --json
factortester research reports export \
  --profile <profile> --work-package-id <package> --branch-id <branch> \
  --format markdown --output ./research-report.md --json
factortester research reports export \
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
Before moving an existing component or replacing its authored content, do not
invent the batch JSON. Read the current machine contract and its exact template:

```bash
factortester research reports mutation-guide --operation move --json
factortester research reports mutation-guide --operation replace --json
```

Run the returned `inspect_command`, fill the returned
`operations_file_template`, then execute its `submit_command`. A replacement
must submit every authored field but no `bindings`; the CLI regenerates typed
reference bindings and preserves workflow-owned bindings.
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

Wrap literal identifiers containing underscores, such as `cs_rank` and
`cs_ordinal_rank(mask, ascending)`, in inline code. If the span is mathematical
notation, use LaTeX instead; if it denotes a domain object, use its typed link.
The CLI rejects an unformatted identifier with its component, field, line,
column, rule and correction example.

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
report generation was published, use `factortester research reports abandon-pending`
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
