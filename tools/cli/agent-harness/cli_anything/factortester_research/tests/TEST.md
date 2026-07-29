# Harness Test Plan

This release gate validates a CLI-Anything adapter to the real remote
FactorTester backend. A successful process exit is insufficient: tests inspect
the session, graph, capability, evidence, HTTP, RunSpec, ResearchRun, Job, and
artifact contracts produced by the workflow.

## Margin-budget step acceptance

- A one-pool margin target step renders a transposed metric/value table with
  equity, target/projected margin, weighted margin ratio, scale, utilization,
  hard maximum, gross leverage, rounding error, and headroom.
- Several cash pools render one compact row per pool instead of nested JSON.
- Compact output contains no per-product dump and points to `step-field` for
  the complete request/decision payload.
- JSON and `step-field` remain lossless; the compact human projection does not
  delete or rewrite the serialized margin-budget fields.
- `factortester margin-budget show/configure` reads and revision-updates the
  real workspace; it validates `0 < target <= max < 1` and exposes that margin
  mode defaults to 0.30/0.40 while disabled margin leaves weights unscaled.
- The CLI-Anything command delegates exactly to the installed `factortester`
  executable and does not reimplement workspace or validation semantics.

## Strategy intent factor-role refinement

- `factortester strategy-intent describe` reads the registered group-test
  manifest and reports only strategy kinds and factor roles the runtime
  actually consumes, including group `screen` and `sizing` roles.
- `factortester strategy-intent show` reads the active workspace configuration
  and exposes each strategy's kind, primary factor, and explicit role bindings
  in both bounded human output and stable JSON.
- `factortester strategy-intent bind GROUP_ID --role ROLE=FACTOR` validates the
  role against the manifest, validates the factor against the workspace's
  registered factor candidates, preserves unrelated configuration fields, and
  updates through the real revision-checked workspace API.
- Reject unknown groups, malformed bindings, unsupported roles, factor aliases
  outside the workspace, and roles incompatible with the strategy kind without
  mutating configuration.
- Reject a bound group `screen` role while screening is disabled and a bound
  `sizing` role unless factor sizing is selected, so no registered role can be
  a silent no-op.
- The research Harness delegates its matching `strategy-intent` commands to
  the installed `factortester` executable and propagates its exit status and
  JSON rather than maintaining a second local configuration model.
- Installed subprocess coverage resolves both console scripts through
  `_resolve_cli`; the controlled executable checks exact delegation arguments.
- Runtime acceptance remains separate from configuration acceptance: native
  tests prove event/precompute target weights and reason codes are identical,
  future factor changes cannot alter earlier entry/exit decisions, missing
  entry values cannot open positions, and missing exit values close positions.
- Group-role acceptance proves the screen is recalculated per signal event and
  applied before ranking, sizing only changes weights inside the selected set,
  event/precompute targets and reasons match, and perturbing future screen or
  sizing values cannot change an earlier target.

### Passing results (2026-07-23)

- Native factor-role, policy, Flow-contract, and scoped server suite:
  `619 passed`.
- Full CLI plus non-server Harness suite: `220 passed`.
- Installed Harness subprocess delegation with
  `CLI_ANYTHING_FORCE_INSTALLED=1`: passed using the resolved console script.
- Installed `factortester` plus Harness against a complete isolated Flask
  server over TCP: strategy-intent workspace configure/show round-trip passed.
- Web factor-role control Node test: passed.
- Broad `tests/backtest tests/server tests/cli` gate: `1317 passed`, `1 skipped`,
  with 3 failures reproduced unchanged at the exact issue-141 base commit
  (incremental EMA expectation and two research-graph projection/migration
  tests); none of their files differ on this branch.

## Test inventory

- `test_core.py`: deterministic graph/capability/session/evidence and packaging
  unit tests.
- `test_full_e2e.py`: installed Harness subprocess workflows with a controlled
  real `factortester` executable.
- `test_real_server_e2e.py`: installed Harness and FactorTester console scripts
  against a complete isolated `server.create_app()` over real HTTP.

### Work Package report collection

- `job collect-report` requires an explicit Profile, Work Package, and branch;
  it rejects an unbound Job or a historic Job without a frozen execution node
  rather than guessing where evidence belongs.
- `job watch-report` retains the compact terminal stream and invokes the same
  scoped collector only after the stream ends.
- Every Job artifact is retained in the Work Package archive; only declared
  statistical tables and passive images become report components under the
  chapter for the frozen execution node.
- Rendering structured authoring updates the corresponding branch
  `content_hash` in `INDEX.json`, without inventing a checkpoint or report
  section.

### Rich report authoring

- `report add --body` and `--body-file` must accept portable Markdown prose
  with inline code, inline/display LaTex, fenced code, and well-formed
  Markdown tables.
- A complete JSON object supplied as prose must be rejected before a report
  node is written, with a typed-component remedy; a real table remains a
  `table` component when it needs Job/source metadata.
- Both one-component and `add-batch` writes must enforce the same body grammar,
  and the read-only report validation response must disclose that grammar.
- The real scoped CLI workflow must render a rich body with a table, code and
  display formula without falling back to a loose report file.
- The one-time hierarchy maintenance tool may move root-level content only
  when exactly one root chapter makes the target unambiguous; it must preserve
  component IDs, atomically switch HEAD, update parent locators and reject
  zero- or multi-chapter roots for explicit human/agent mapping.

## Unit coverage

### Graph protocol and topology

- Project the existing fixed plan as an advisory Observed Graph.
- Build the product-neutral Draft Graph and validate every node, edge,
  lifecycle, enforcement, risk level, and capability descriptor.
- Preserve stable content hashes across the natural module split.
- Reject duplicate IDs, dangling edges, and missing descriptors.
- Keep diagnostic rejection, bounded revision, capability-gap recovery, and
  result-audit routes semantically distinct.

#### Successor Graph contract refinement

- Keep schema-v1 Graphs byte-compatible and readable while schema v2 requires
  an immutable change manifest, Requirement Catalog, Report Method descriptors,
  Report Requirements, and system-transition policies.
- Reject unknown category/requirement/method/report/anchor references, duplicate
  IDs, missing CLI resolver contracts, and Report Requirements that bind neither
  a real Verification Obligation requirement nor an explicit coordination fact.
- Require every schema-v2 node entry/action and explicit edge to expose bounded
  report requirement references; system gates use their own policy anchors and
  do not become permanent nodes.
- Prove the server validator consumes the same provider-neutral protocol and
  content hash without a second schema implementation.
- Keep contract validation deterministic, source-free, and free of database or
  Agent calls.

### Node-local capability resolution

- Resolve the current node by default and the full graph only when `--all` is
  explicit.
- Evaluate bounded predicates deterministically and expose unknown facts as
  `requires_agent_judgment`.
- Exclude model/provider/Codex runtime identity from semantic cache keys.
- Verify approved provider fingerprints before selecting an implementation.
- Hash every progressively loaded instruction, reference, and executable file
  used by an approved multi-file Skill into one provider identity.
- Invalidate cache results when provider source content changes.
- Reuse a registered approved Skill by default when its reviewed fingerprint is
  unchanged, while changed, newly discovered, and quarantined providers remain
  fail-closed without loading their Skill body.
- Keep capability descriptions and descriptor hashes independent from concrete
  locally used Skill identity.
- Return byte-stable role-specific Agent resume packets capped at 6000 bytes:
  Research receives one branch, Planning one bounded workspace-factor summary,
  and Server Maintenance only its actionable case queue.
- Keep unconfigured profiles immediately usable, expose configured remaining
  budget without usage history, and omit other roles' state, complete graph,
  catalogs, output, and future gaps.

### Local research audit

- Preserve hash-chained Skill usage with provider, version, fingerprint,
  approval reference, load/reuse mode, rationale, and token counts.
- Persist compact factual EvidenceEnvelope v2 records with command exit status
  and artifact references instead of inline stdout/stderr bodies or research
  decisions.
- Capture a terminal JobAttempt envelope projected by the authenticated server,
  verify its frozen research identity against terminal assurance, and reuse
  the same envelope hash without duplicating the local audit record.
- Keep the Job list projection to one bounded database read for Job records,
  pin state, and active-artifact counts rather than per-Job follow-up reads.
- Project Job detail, pin state, TrialPlan binding, and EvidenceEnvelope
  identity with one joined read; the envelope projector performs no reads.
- Keep legacy EvidenceEnvelope v1 payloads in the persistence-only historical
  record while excluding their decisions, metrics, artifacts, paths, and
  nested copies from every Agent-facing session JSON view.
- Preserve gap and factor-improvement state transitions.
- Keep selection slices separate from OOS annotation.

### Research Obligation Cycle Skill

- Package one canonical and installed reference Skill with five progressively
  loaded modes.
- Resolve its five capability descriptions through one exact whole-bundle
  manifest fingerprint.
- Require conversation approval before the first execution and reuse only the
  unchanged approved fingerprint.
- Validate obligation-discovery and paired-adjudication proposals with
  standalone deterministic scripts.
- Cover material time, market-state, instrument, and interval-event transfer
  questions without Cartesian-product expansion; preserve sequential
  walk-forward exposure, high-frequency day/month staging, purge/embargo, and
  a genuinely untouched latest interval in TrialPlan guidance.
- Load market-event search guidance only for a material anomaly, preserve
  occurrence and public-availability time, bound post-hoc narratives, and use
  at most one event-research sub-agent at the declared risk threshold.
- Reject server proposal payloads containing concrete Skill identity.
- Keep canonical and packaged Skill trees byte-identical.
- Require every newly persisted adjudication or closure proposal to name the
  settled proposer invocation that produced it.
- Resolve all proposer and independent-reviewer authority references for one
  transition with one bounded Agent Flow lookup.
- Bind independent-reviewer invocations to the exact proposal hash and reject
  missing, unsettled, wrong-role, wrong-scope, same-principal, or same-lineage
  authority.
- Keep ordinary factual transitions and deterministic historical replay free
  of Agent Flow database reads.

### Packaging

- Keep canonical and packaged `SKILL.md` bytes identical.
- Keep every new production module below 300 lines.
- Preserve the original Click command names, options, help, and JSON shapes
  after command-domain extraction.

## Installed subprocess workflows

The subprocess suite uses `_resolve_cli("cli-anything-factortester-research")`
and supports `CLI_ANYTHING_FORCE_INSTALLED=1`. It must not set a source-tree
working directory to make an installed command pass.

Workflows cover:

- `--help`, `--json`, plan creation, status, and gap lifecycle;
- Observed/Draft Graph output and stable content hashes;
- current-node capability resolution with full contracts omitted by default;
- explicit `--include-contracts` audit output;
- dry-run and real delegation to the configured `factortester` executable;
- server-owned terminal JobAttempt evidence capture without reconstructing
  research identity from CLI output or local Skill state;
- factor-workspace inspection and platform-gap EvidenceEnvelope persistence;
- external daily/minute/factor/handoff manifest validation.

## Real installed CLI to server E2E

The release gate starts the complete Flask application against temporary SQLite
state and drives it through installed console scripts over TCP. It does not use
Flask `test_client`, fake HTTP routes, a developer account, or source-module CLI
fallbacks.

It proves:

- one login with `--keep-login` authenticates later independent processes and
  logout removes the local session;
- the Harness publishes a real immutable graph version;
- trusted proposer/reviewer executions are server-issued and independently
  attributable;
- graph start accepts direct node-local `capability_resolution`; no
  attest/receipt API participates;
- `context` and `next` are bounded current-node packets and future,
  untriggered gaps do not block the branch;
- target-node resolution accompanies only the transition that needs it;
- server-owned validation derives non-mutating trace replay, like-for-like
  shadow comparison, and token-efficiency evidence from canonical references;
- the client cannot self-certify replay/shadow/token pass booleans;
- proposal, independent review, grill audit, human authorization, and
  activation remain separate gates.

Companion server tests, outside this Harness package suite, validate the
TrialPlan schema, transition freeze rules, TrialPlan-to-ResearchRun binding,
Job inheritance through `run_id`, retention, and exact-hash rollback gates.
Schema-v4 tests distinguish sample stage from comparison arm, freeze stage
partitions plus RunSpec/comparison membership across child versions, validate
direct-confirmation entry, persist one compact branch stage projection, and
keep the Agent packet below its existing byte limit.
ResearchRun boundary tests verify that stage comes from the planned sample,
not the comparison arm; only the current stage at the plan-bound execution
node can run; protected-sample reuse cannot be hidden behind a shared
`candidate` role; and the hot path remains one branch read plus one run write.
Factor-revision lineage tests preserve the old plan and exposure, release only
on the server-owned new-hypothesis edge, and bind the replacement as version 1
of a new plan identity.
Research Cycle reopening tests clear accepted or pending closure only for an
accepted new or reopened decision-blocking obligation; rejected and
non-blocking deltas preserve closure.
Compact-cycle tests expose bounded question/criterion/detail refs in the
routine packet and load exactly one referenced Claim or obligation body with
one database read and no trace-history scan.
Data-contract tests require an explicit request on the existing edge, execute
availability outside the branch write lock, bind a server-owned
Contract/Methodology EvidenceEnvelope, override client guard booleans, reject
stale/oversized requests without transition writes, and derive identical
guard facts during offline replay. Availability never discharges an
obligation or claims PIT, replayability, or latency fitness.
Factor-revision server tests verify stable source-free manifests, hash changes
for source or resolved-expression changes, RunSpec-v2 preview/submit identity,
legacy RunSpec-v1 readability, and execution-time failure when the current
factor implementation no longer matches the frozen manifest. Random
Parameter display UUIDs are excluded from semantic hashes.
Factor-semantics edge tests require only the branch configuration revision,
freeze manifests outside the branch write transaction, bind a server-owned
Contract/Methodology EvidenceEnvelope, reject stale or unresolved selections,
and derive identical manifest guards during offline replay. The envelope
contains no source, formula, or expression tree and does not self-certify
causal or economic semantics.
JobAttempt edge tests require only an owner-scoped `job_id`, bind canonical
Job/ResearchRun/Contract/Methodology/TrialPlan identity outside the branch
write transaction, and derive identical trust and artifact guards during
offline replay. Client booleans cannot override server facts; failed,
maintenance-required, cross-branch, and stale-plan attempts cannot advance.
Only a named `net_returns` or `net_return_series` artifact qualifies, while a
generic result artifact deliberately exposes a backend capability gap.
Native backtest artifact tests derive the named series from fee-adjusted ledger
equity and fail closed on missing, zero, duplicate, non-finite, or unsupported
engine curves. Summary retention produces no such research artifact.
They also verify that `run preview` derives the exact immutable RunSpec hash
through the same server-side freeze path without creating a ResearchRun or Job,
so an Agent can preregister a TrialPlan before submission.
Run Configuration Snapshot tests keep one Research Workspace while freezing
multiple immutable configuration choices below it. They verify snapshot
creation from the current mutable configuration, byte-stable identity and
source provenance, explicit preview/submit selection, identical preview and
submit RunSpec hashes, and rejection of cross-owner, cross-workspace, deleted,
or stale snapshot identities. The existing mutable workspace configuration and
template revision semantics remain unchanged.
Capability-resolution tests verify that registered, approved, whole-bundle
fingerprint-valid Skill implementations may be bound without rediscovery but
cannot self-authorize execution: a local conversation grant is required before
use, and changed source always fails closed. They also keep equity-only
microstructure guidance out of China-futures resolution and bind the built-in
TrialPlan/RunSpec trial ledger plus reviewed false-discovery guidance.

Derived-report tests verify byte-stable Markdown, content-addressed asset
embedding, explicit missing/unauthorized gaps, atomic incremental writes,
preservation of the previous complete report after write failure, rejection of
source/heavy payloads, and a server-free CLI render path. Factor-workspace
tests separately prove that regeneration preserves `research/` reports and
notes.

### Profile research projection refinement plan

This refinement exposes the existing Active Graph state to profile-aware
clients without persisting a server-side profile or copying report Markdown
into the database.

- `tests/server/test_profile_research_projection.py`: bounded list, detail, and
  keyset timeline projections; owner/workspace isolation; response byte limits;
  no raw evidence, stdout, source, or Markdown; constant query counts; index
  plans; and large-history fixtures.
- The route cases in `test_profile_research_projection.py`: authenticated HTTP
  list/detail/timeline workflows, invalid cursors and limits, ETag conditional
  reads, and cross-user denial.
- `tests/cli/test_factortester_client.py`: typed client adapter paths, cursors,
  and limits over a real HTTP transport.

The realistic workflow lists a profile's registered workspace research,
opens one current branch projection, pages transition references, and follows
existing Job SSE links only for running jobs. It verifies that terminal
research does not advertise live polling and that no endpoint replays full
history or writes progress rows.

### Local checkpoint report publisher refinement plan

- `tests/release/test_local_research_report.py`: publish one bounded,
  source-free Active Graph checkpoint through the public local client API;
  update the existing Work Package report hierarchy and Profile research
  reference; prove an identical checkpoint rewrites neither report files nor
  the Profile JSON; and reject oversized, inconsistent, or source-bearing
  carriers before mutation. The server projection is exercised without a
  translation shim: omitted evidence becomes an explicit report gap, an
  absent TrialPlan remains legal, and the existing local scope contributes
  only bounded field names plus a canonical hash, never raw scope values.
- `tests/cli/test_client_research_commands.py`: publish the same carrier from
  stdin or a file through `factortester client research checkpoint publish
  --json`, without constructing an HTTP client or reading a database.
- Existing `test_report_rendering.py` remains the renderer compatibility suite;
  the CLI-Anything import path must re-export the single public implementation
  rather than retaining a second writer.

### Local Profile binding refinement plan

- `tests/release/test_local_client_profile.py`: update an existing Profile's
  server URL through the public CLI; bind, list, and remove compact server
  workspace references; and derive Agent readiness from an actually bound
  scope.
- Mutations must reuse the existing atomic Profile JSON store, preserve the
  principal/session and factor-worktree bindings, and perform no server or
  database write.
- Removing a workspace that scopes a planning Agent must deterministically
  return that Agent to `needs_scope` rather than leave a false-ready claim.

## Commands

Run the Harness package suite:

```bash
PYTHONPATH=tools/cli/agent-harness \
  conda run -n GTHT python -m pytest \
  tools/cli/agent-harness/cli_anything/factortester_research/tests \
  -v -s --tb=short
```

Require the installed Harness command:

```bash
cd tools/cli/agent-harness
python -m pip install -e .
CLI_ANYTHING_FORCE_INSTALLED=1 \
  conda run -n GTHT python -m pytest \
  cli_anything/factortester_research/tests/test_full_e2e.py \
  -v -s --tb=short
```

## Test results

Last release-gate run: 2026-07-20

```text
CLI_ANYTHING_FORCE_INSTALLED=1 PYTHONPATH=tools/cli/agent-harness \
  conda run -n GTHT python -m pytest \
  tools/cli/agent-harness/cli_anything/factortester_research/tests \
  -v -s --tb=no

[_resolve_cli] Using installed command:
  /opt/homebrew/Caskroom/miniconda/base/envs/GTHT/bin/cli-anything-factortester-research
collected 73 items

test_core.py
  46 passed
test_full_e2e.py::TestCLISubprocess
  17 passed
test_real_server_e2e.py::test_installed_clis_drive_real_server_active_graph_e2e
  [_resolve_cli] Using installed command:
    /opt/homebrew/Caskroom/miniconda/base/envs/GTHT/bin/factortester
  [_resolve_cli] Using installed command:
    /opt/homebrew/Caskroom/miniconda/base/envs/GTHT/bin/cli-anything-factortester-research
  PASSED
test_report_rendering.py
  9 passed

73 passed, 123 warnings in 16.27s
```

All warnings are existing Pandas frequency-alias deprecations (`d` to `D`) in
parameter and FactorExpr shift code outside this Harness refactor. The command
exit status and collected test names remain authoritative; no production logic
uses a hard-coded expected count.

### Profile research projection refinement

Last run: 2026-07-20

```text
PYTHONPATH=tools/cli/agent-harness conda run -n GTHT python -m pytest \
  tests/server/test_profile_research_projection.py \
  tests/cli/test_factortester_client.py \
  tests/server/test_research_graph_context_cost.py \
  tests/server/test_research_cycle_object_read.py \
  tests/server/test_research_graph_final_schema.py \
  tests/server/test_active_graph_final_cutover.py \
  tests/server/test_research_graphs.py -v --tb=no

collected 64 items
64 passed in 4.47s
```

The projection-specific large fixture contains 1,000 branches and 100,000
trace rows. List, detail, and timeline remain single-read projections; query
plans use the owner/workspace and branch/timeline indexes. The HTTP acceptance
also verifies owner isolation, 64 KiB bounds, opaque keyset cursors, ETag/304,
and exclusion of raw evidence, stdout, factor source, and report Markdown.

### Local Profile binding refinement

Last run: 2026-07-21

```text
PYTHONPATH=. conda run -n GTHT pytest -q \
  tests/release/test_local_client_profile.py \
  tests/release/test_profile_lifecycle.py \
  tests/release/test_profile_factor_worktree.py

23 passed
```

The public CLI updates one local server binding, manages compact workspace
references, derives truthful Agent readiness, and downgrades a planning Agent
when its workspace is removed. These operations use the existing atomic local
Profile JSON store and perform no server/database write.

### Margin budget and step audit

Last run: 2026-07-23

```text
PYTHONPATH="$PWD" conda run -n GTHT pytest -q \
  tests/backtest/native/test_margin_budget*.py \
  tests/backtest/native/test_gold_standard_accounting.py

21 passed in 0.55s

PYTHONPATH="$PWD" conda run -n GTHT pytest -q \
  tools/cli/agent-harness/cli_anything/factortester_research/tests/test_real_server_e2e.py \
  -k strategy_intent_cli_round_trips_real_workspace

1 passed, 1 deselected in 2.75s
```

The scheduler assertion reads `gross_leverage` from the actual step record;
the HTTP round trip verifies margin-budget configure/show against a real
workspace. The broader backtest/server/CLI suite completed with 1,335 passes,
1 skip, and the same three branch-baseline failures recorded outside this
feature.
# Entry Requirement authoring refinement (Issue #141)

## Test inventory plan

- `test_entry_preparation.py`: 8 focused unit/CLI tests planned.

## Unit test plan

- `core/entry_preparation/factor_facts.py`
  - Compact the real `custom_factors describe --debug-graph` response.
  - Preserve parameter, fixed `ColumnRef`, AST identity and deterministic LaTeX facts.
  - Do not retain source code, full parameter option catalogs or the full debug payload.
- `core/entry_preparation/skeleton.py`
  - Build a draft only for explicitly selected current-node Entry Requirements.
  - Bind each Chinese report row to the matching Graph report requirement.
  - Carry existing mapped obligations without loading unrelated obligation bodies.
- `core/entry_preparation/validation.py`
  - Accept `create_new`, `map_existing`, and `no_material_issue`.
  - Require Chinese reasoning, current fact references, obligation mappings where
    applicable, and one first action or Trial reference.
  - Produce compact server-facing assessment/report projections without mutating
    server or local database state.

## CLI workflow plan

- `cycle entry-prepare` calls the real FactorTester CLI for one compact `next`
  packet, only the requested requirement details, and one factor description.
- `cycle entry-validate` is offline and deterministic; it fails with itemized
  errors until the editable draft is complete.
- Both commands support JSON and ordinary filesystem paths on macOS, Linux and
  Windows.

## Entry Requirement refinement results

```text
$ CLI_ANYTHING_FORCE_INSTALLED=1 pytest \
    test_full_e2e.py test_entry_preparation.py -q
...............................                                          [100%]
31 passed in 7.28s
```

The focused core/CLI suite contains 11 Entry Requirement tests. A real MaxA
v9 invocation also prepared `factor_semantics.expression_identity` from the
installed FactorTester CLI and verified:

- one selected requirement detail was loaded;
- the SgCPS factor facts contained 15 compact AST nodes, deterministic LaTeX,
  `HA`/`LA` ColumnRefs and one content-addressed expression reference;
- neither factor source code nor the full parameter option catalog was stored.

The complete Harness suite reached 131 passing tests. Its remaining pre-existing
real-server E2E fails while starting an old shadow instance because that fixture
does not supply the now-required shadow proposal; it is outside this
Entry-authoring refinement and does not exercise these commands.

## Run-scoped Profile role factors refinement

Last run: 2026-07-28

```text
$ conda run -n GTHT python -m pytest -q \
  tests/backtest/native/test_group_membership.py \
  tests/server/test_research_job_lifecycle.py \
  tests/cli/test_strategy_intent_commands.py \
  tests/server/test_factor_revision_manifest.py \
  tests/server/test_transient_factor_sources.py

105 passed in 1.45s
```

The strategy-intent CLI accepts a deferred `screen` alias without adding it to
the workspace's shared factor list. A real HTTP preview uploads a Profile-only
factor, freezes its source-free SHA-256 manifest, and exposes the
`transient_run_source` policy without returning source text. Revision checks
also cover role aliases, while the group-membership suite verifies that screen
selection occurs before ranking and excludes missing/warm-up values.

## Typed report reference refinement

### Test inventory plan

- `tests/release/test_report_rich_text.py`: syntax and exact typed-reference
  contracts, including immutable factor and Profile revisions.
- `tests/cli/test_report_reference_client.py`: submission-time validation without
  generating or rewriting Agent-authored Markdown.
- `tests/server/test_report_reference_resolution.py`: exact product-catalog
  validation for products, contracts, and continuous contracts.
- `tests/release/test_report_batch_replace*.py`: atomic authoring-tree and
  installed-command replacement workflows covering preserved hierarchy,
  CLI-generated references,
  system binding retention, stale binding removal, retry identity, and global
  binding-ID uniqueness.
- `tools/cli/agent-harness/cli_anything/factortester_research/tests/test_core.py`:
  the installed progressive-disclosure Skill tells the Agent to author the
  complete typed link, never delegates object inference or link generation to
  the CLI, and explains same-sequence correction after a rejected submission.
- `apple/Tests/ResearchDocumentTextBlockTests.swift`: semantic colors, symbols,
  parsing, and routing for every supported reference kind.

### Acceptance contract

- The Agent writes the complete typed Markdown link and explicitly chooses its
  kind and exact target reference; no migration, CLI, server, or client infers
  an object from prose, a display label, alias, or product code.
- Report submission validates every internal link against its authority without
  rewriting the Markdown: Git commit/blob for factors, the local Profile
  registry for Profile identity and frozen revisions, the product catalog for
  product objects, and existing server records for Evidence and Jobs.
- One shared preflight validates Markdown links, typed links, inline/display
  LaTex, inline code, fenced code, and declared source references before either
  a single or batch mutation. Each diagnostic identifies component, field,
  line, column, stable error code, violated rule, and a corrective example.
- A failed preflight opens one branch-local pending submission at
  `HEAD.generation + 1`. Until that same logical component/batch is corrected
  with its `submission_sequence`, all different report writes are rejected.
  Failure never advances HEAD; successful correction atomically publishes that
  sequence as the next generation and closes the pending submission.
- Product-catalog validation accepts only an exact registered object path whose
  object type matches `product`, `contract`, or `continuous_contract`.
- Failed validation is atomic: no report component, HEAD generation, descriptor,
  or Git commit changes.
- `add-batch` replacement updates only an existing component's authored fields;
  it preserves hierarchy and system-owned report requirements, removes graph and
  stale reference bindings, and permits a current component to reuse a binding
  ID only when kind and target remain identical.
- macOS consumes the validated kind and target as data. It never parses a
  product code or label to guess a destination.

## Branch report projection refinement (Issue #141)

## Test inventory plan

- `tests/release/test_generic_research_report.py`: extend with one focused
  projection case.
- `tests/release/test_report_rendering.py`: retain the existing journal replay
  coverage while checking that a structured authoring source is appended to
  the same branch `REPORT.md` rather than creating a second Markdown report.

## Unit test plan

- A branch with a graph-journal snapshot and `authoring/DOCUMENT.json` has one
  readable `branches/<branch>/REPORT.md` containing both projections.
- Re-rendering replaces the bounded authoring projection block, so it is
  idempotent and never duplicates report sections.
- `research report render` targets that branch report; it must not create
  `authoring/REPORT.md`.
- `tests/release/test_research_history_ui.py`: assert that one narrative
  surface can append structured components and that document refresh uses a
  view-lifetime file presenter instead of a timed polling loop.

## Job-to-report collection refinement (Issue #141)

## Test inventory plan

- `tests/release/test_job_artifacts.py`: replace arbitrary report-file tests
  with Work Package branch scope fixtures.
- `tests/server/test_research_job_lifecycle.py`: cover immutable execution-node
  projection from the ResearchRun into Job detail.

## Unit test plan

- A completed job downloads all files into
  `research/<work-package>/artifacts/jobs/<job-id>/`.
- Only declared tables and passive images are mounted as special components,
  under the chapter bound to the Job's immutable execution node.
- A missing execution node is rejected; the collector never silently attaches
  an old job to the branch's current node.

## Evidence Registry to Graph admission refinement (Issue #141)

## Test inventory plan

- `tests/server/test_research_evidence_graph_admission.py`: direct transition
  coverage for persistent Evidence admission bindings.
- `tests/server/test_research_evidence_registry.py`: retain ownership and
  admission replacement coverage.

## Unit test plan

- The Agent supplies only an evidence/admission reference pair; the Graph
  resolves owner, workspace, branch scope, qualification, identity scope and
  immutable envelope metadata inside the transition transaction.
- An eligible admission satisfies an Active Graph edge that explicitly
  requires admitted evidence and carries only a server-derived binding into
  the trace and bounded evidence context.
- A stale admission, an admission for another branch, and a limited
  qualification cannot satisfy that guard.

## Graph continuation report hierarchy refinement

### Test inventory plan

- `tests/release/test_report_hierarchy_contract.py`: nested system-special
  hierarchy through the public report writer.
- `tests/release/test_graph_continuation_report_hierarchy.py`: inherited report
  publication with and without a server-owned capability-detour stack.
- `tests/cli/test_research_graph_commands.py`: continuation CLI uses the exact
  server report container and inherited target branch.

### Acceptance contract

- A continuation inherits the source report before publishing its upgrade
  record and never creates a chapter from `carrier.current_node`.
- With an open detour stack, `graph_continuation` is a child of the current top
  detour; without one it is a child of the existing substantive node chapter.
- Nested detour specials preserve every episode identity and content. The
  upgrade record neither clears nor replaces any episode.
- Missing, ambiguous, or mismatched server-owned parent state fails closed and
  leaves the report HEAD unchanged.
