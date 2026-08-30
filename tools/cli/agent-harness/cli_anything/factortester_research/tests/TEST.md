# Harness Test Plan

This release gate validates a CLI-Anything adapter to the real remote
FactorTester backend. A successful process exit is insufficient: tests inspect
the session, graph, capability, evidence, HTTP, RunSpec, ResearchRun, Job, and
artifact contracts produced by the workflow.

## Product metadata and report reference acceptance

- `factortester products info` wraps long keys, values, sources, and notes
  without replacing their content with an ellipsis.
- The canonical, packaged, and locally registered Research Agent Skill applies
  typed domain-reference rules to every Markdown-bearing report location.
- The Skill distinguishes domain-object links, mathematical LaTeX, and literal
  program or CLI syntax; inline code is never a fallback for an unresolved
  domain object.

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

- `factortester strategy intent describe` reads the registered group-test
  manifest and reports only strategy kinds and factor roles the runtime
  actually consumes, including group `screen` and `sizing` roles.
- `factortester strategy intent show` reads the active workspace configuration
  and exposes each strategy's kind, primary factor, and explicit role bindings
  in both bounded human output and stable JSON.
- `factortester strategy intent bind GROUP_ID --role ROLE=FACTOR` validates the
  role against the manifest, validates the factor against the workspace's
  registered factor candidates, preserves unrelated configuration fields, and
  updates through the real revision-checked workspace API.
- Reject unknown groups, malformed bindings, unsupported roles, factor aliases
  outside the workspace, and roles incompatible with the strategy kind without
  mutating configuration.
- Reject a bound group `screen` role while screening is disabled and a bound
  `sizing` role unless factor sizing is selected, so no registered role can be
  a silent no-op.
- The research Harness delegates its matching `strategy intent` commands to
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
  server over TCP: strategy intent workspace configure/show round-trip passed.
- Web factor-role control Node test: passed.
- Broad `tests/backtest tests/server tests/cli` gate: `1317 passed`, `1 skipped`,
  with 3 failures reproduced unchanged at the exact issue-141 base commit
  (incremental EMA expectation and two research-graph projection/migration
  tests); none of their files differ on this branch.

## Test inventory

- Factor references freeze the exact source Git commit/blob. Multi-factor
  subjects use a named, committed `factor-set` manifest with its own stable ID;
  a factor-set is not a factor family, and member-factor scope cannot satisfy
  factor-set Edge scope. Report bindings retain only the frozen set identity,
  member count and member hash; the CLI resolves the immutable member manifest
  in bounded pages so large sets never overflow report binding limits. CLI
  coverage also exercises compact list/show, JSON member files, immutable
  version diff, and optimistic update rejection with a stale member hash.

- `test_core.py`: deterministic graph/capability/session/evidence and packaging
  unit tests.
- `test_full_e2e.py`: installed Harness subprocess workflows with a controlled
  real `factortester` executable.

### Active Graph activation orchestration

- `research graphs activation-status GRAPH_ID VERSION` returns one compact,
  server-derived readiness receipt with the current pointer, target version,
  completed gates, missing gates, and rollback target.
- The ordinary `research graphs activate GRAPH_ID VERSION` path never asks the
  caller to copy proposal IDs, Graph hashes, diff hashes, or conversation refs.
- Activation remains fail-closed until independent review, deterministic
  validation, grill audit, and an authenticated human approval are all bound
  to the same immutable Graph target.
- `--yes` supports an explicitly authorized non-interactive Agent invocation;
  without it the CLI requires an interactive confirmation.
- A successful activation returns a compact pointer-change receipt and a retry
  against the already-active version is idempotent.
- The low-level exact-ID authorization commands remain available for audit and
  recovery, but are not the normal user or Agent workflow.

### Work Package Graph continuation orchestration

- Activating a Graph changes only the default for new research. Existing Work
  Packages move only through the existing `continuation-preview` and
  `continue` server operations.
- Continuation remains fail-closed unless the target is a descendant of the
  source Graph through one complete immutable parent lineage and contains the
  branch's current node.
- `research graphs continue ... --yes` obtains the exact target hash through
  `continuation-preview` and immediately submits that hash through the existing
  continuation endpoint. The server recomputes it before mutation.
- `--expected-target-hash` remains available for audit and recovery, but Agents
  do not normally copy a 64-character hash between commands.
- The v10 candidate is a direct child of the immutable v9 Graph. A v8 Work
  Package may continue to v10 only through the verified v8 → v9 → v10 lineage,
  with every intermediate Graph hash and Change Manifest bound to the trace.

### Work Package report collection

- Ordinary Jobs remain valid without a report binding. A Trial Job must freeze
  a complete report scope or explicitly opt out with `--without-report`.
- The immutable binding retains Profile, Work Package, Graph branch, report
  HEAD generation/hash, and the server-owned execution node through
  ResearchRun and Job detail.
- Report-bound submit waits for terminal completion, mounts exactly one
  `test_result` special section per Job, and returns an
  `analysis_required` parent for the Agent's follow-up.
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
  stdin or a file through `factortester research workspaces checkpoint publish
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
  tests/server/test_research_cycle_object_read.py \
  tests/server/test_research_graph_protocol_v2.py \
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
  tools/cli/agent-harness/cli_anything/factortester_research/tests/test_full_e2e.py \
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
  - Compact the real `factor-library describe --debug-graph` response.
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

- `research graphs node advance` owns this workflow. Its first call reads the
  compact current packet, current requirement details and one factor
  description, writes an editable draft, and returns without Graph mutation.
- Rerunning the same command validates the draft offline and fails with
  itemized errors until it is complete, then derives the compact projection
  before submission.
- The command supports ordinary filesystem paths on macOS, Linux and Windows.

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

The strategy intent CLI accepts a deferred `screen` alias without adding it to
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

## Canonical local Research Graph command refinement

### Test inventory plan

- Server-supplied `next_actions` are no longer an authority. Local graph
  evaluation returns any local guidance from the downloaded graph and facts.
- `tests/release/test_graph_packet_commands.py`: the Harness report packet
  contains no removed `factortester node` or `factortester edge` shortcut.

### Test results

The focused command-contract suite passed 80 tests. The expanded Harness,
continuation, report hierarchy, shadow replay, and v8-to-v10 continuation suite
passed 240 tests in 11.19 seconds. Installed-command enforcement separately
passed all 20 `test_full_e2e.py` tests.

## Git-tracked obligation ledger refinement

### Test inventory plan

- `tests/release/test_research_obligation_ledger.py`: ledger schema, projection,
  atomic persistence, size limit, event replay, fork provenance and recovery.
- `tests/cli/test_research_graph_obligation_commands.py`: native obligation
  change, edge selection and node-advance ledger integration.
- `tests/server/test_research_obligation_coverage.py`: server-side coverage
  recomputation, stale-state and coverage-hash rejection.
- `tests/cli/test_research_report_history_obligations.py`: two-table obligation
  sections, source-node exit coverage and one-time history migration.
- `tools/cli/agent-harness/cli_anything/factortester_research/tests/test_full_e2e.py`:
  installed-command JSON workflow against a real local Work Package.

### Unit test plan

- One branch owns exactly one `branches/<branch>/obligations.json`; schema-v1
  rejects unknown fields, invalid hashes, duplicate identities and files above
  16 MiB.
- Whole-file updates use a temporary file, file and directory `fsync`, then an
  atomic replace. A failed write preserves the previous valid generation.
- State-changing and mapping-only obligation deltas produce deterministic
  current projections and post-event coverage snapshots.
- Edge selection, reselection and clearing recompute requirement coverage
  without changing the obligation-change table.
- Prepared and receipt events bind exact node, edge, context, checkpoint,
  coverage hash, report sequence and local Git commit.
- A fork copies the current projection and records the source branch/hash but
  does not copy mutable pending-transition state.

### Realistic workflow scenarios

- **Obligation change and report publication**: apply one mapping-only delta,
  atomically publish the obligation-change special plus change and current
  coverage tables, then verify one report generation and one Git commit.
- **Rejected transition**: prepare an advance with missing coverage, persist a
  rejection receipt, retain the prior report section and verify that no
  source-node exit section or target chapter was created.
- **Accepted transition recovery**: accept the server transition, fail local
  report finalization, then reconcile the accepted receipt, source-node exit
  coverage and target-node requirements without submitting the transition
  twice.
- **Historical migration**: replay all SgCCS branches into one ledger per
  branch, backfill two-table obligation sections and source-node exit coverage,
  rerun idempotently and compare report/ledger hashes.

### Subprocess acceptance

- Resolve the installed `factortester` command with `_resolve_cli`, invoke
  obligation status/change, edge choose and node advance from a directory
  outside the repository, and parse every `--json` response.
- Verify the command mutates the real Work Package and that the resulting Git
  revision contains the report tree and `obligations.json` together.

## Obligation Chinese-title refinement

### Test inventory plan

- `tests/server/test_research_obligation_cycle_protocol.py`: every newly
  discovered obligation carries a bounded, one-line `title_zh`.
- `tests/release/test_research_obligation_ledger.py`: obligation and requirement
  links render their authoritative Chinese titles while stable IDs remain link
  targets.
- `tests/server/test_profile_research_projection.py`: checkpoint projections
  expose both the short title and full epistemic question.
- `apple/Tests`: projection and audit-object decoding preserve `title_zh` for
  native presentation without client-side inference.

### Acceptance contract

- `title_zh` is a concise Chinese display title of at most 32 characters;
  `epistemic_question` and requirement `question_zh` retain the complete
  question.
- Requirement titles come from the versioned Graph catalog. Obligation titles
  come from the accepted obligation object. Neither CLI nor Swift derives a
  title from an ID or surrounding prose.
- Markdown link labels and binding labels use `title_zh`; target references
  continue to use immutable obligation and requirement IDs.
- Existing branch ledgers and report source trees are migrated once before the
  stricter write gate is enabled.

## Fragment-bound Evidence and obligation-use refinement

### Test inventory plan

- `tests/server/test_research_evidence_catalog.py`: immutable SourceCapture and
  SourceFragment identities, fragment-bound Evidence, system facets, Agent
  tags, search, ownership and one-time legacy migration.
- `tests/cli/test_research_evidence_commands.py`: native guide, source,
  fragment, create, search, facet and tag command groups with structured
  `next_actions`.
- `tests/release/test_research_obligation_ledger.py`: schema-v2 EvidenceUse,
  many-to-many requirement coverage, split semantics and fragment-backed
  evidence gates.
- `tests/cli/test_research_report_history_obligations.py`: three-table
  obligation sections, evidence links and migrated history.
- `apple/Tests`: Evidence detail decodes fragment/source actions; report
  Evidence links open the detail first, while an explicit Job object link
  continues to open the Job tab directly.

### Domain and workflow contract

- One immutable JobAttempt, terminal execution, file revision or web snapshot
  owns one SourceCapture and may own many fragments.
- Every new Evidence object references at least one owned SourceFragment.
  Source-wide Job, command, file and URL references are rejected.
- `source_kind` and `evidence_kind` are immutable system facets. Agent tags are
  mutable user-scoped discovery metadata and never change Evidence identity,
  applicability or Graph admission.
- Tag creation requires a proposal bound to the current catalog revision.
  Similar tags are returned as candidates; an intentional near-duplicate needs
  an explicit distinction reason.
- Search applies product, factor, sample and time compatibility before tag or
  text ranking and explains matches, conflicts, limitations and next actions.
- The main Research Agent authors obligations before the CLI reveals concrete
  requirement subclasses and candidate Evidence. A review Agent cannot author
  or mutate an obligation.
- Each EvidenceUse records one evidence reference, one obligation, one or more
  requirement subclasses, a Chinese rationale, qualification and the validated
  scope snapshot. Evidence, obligations and requirements remain many-to-many.
- Every Edge advance revalidates EvidenceUse scope against the current active
  Claim union and server-owned branch admission. A typed factor/product scope
  introduced only by Evidence is rejected as unbound; a stale subject mismatch
  is not eligible for the human missing-coverage override.
- Obligation changes render a change table, a collapsed current-obligation
  table and a collapsed node/Edge requirement-union table. Evidence links use
  authoritative Chinese titles.
- A report Evidence link opens Evidence detail. Job, local-file, web and
  terminal-output navigation is available only from that detail; an explicitly
  authored Job object reference still routes directly.

### Realistic workflow scenarios

- **Reuse before capture**: list system facets and Agent tags, search by exact
  product/factor/time scope, inspect match explanations and reuse one existing
  Evidence without creating a duplicate.
- **Fragment one terminal execution twice**: capture one real command, create
  separate stdout and return-code fragments, then create two independently
  searchable Evidence objects.
- **Fragment one Job result repeatedly**: capture one terminal JobAttempt,
  select a metric and an artifact/result fragment, and verify both Evidence
  objects navigate through the same Job source.
- **Tag governance**: propose a near-duplicate tag, receive existing
  candidates, create only with an explicit distinction reason, attach and
  detach it without changing the Evidence hash.
- **Obligation split**: supersede one broad obligation, create bounded child
  obligations, explicitly redistribute requirements and EvidenceUse records,
  and verify that no evidence is inherited silently.
- **Historical migration**: convert recoverable Job/terminal/file/web Evidence
  to fragment-bound objects; mark unrecoverable evidence
  `unverifiable_fragment` and keep it readable but ineligible for new coverage.

## Research report navigation and human gate override refinement

### Test inventory plan

- `apple/Tests/ResearchBranchPickerTests.swift`: the selected research path
  uses a fixed-width truncated label while the expanded path menu preserves
  complete multiline labels.
- `apple/Tests/ResearchReportSectionBridgeTests.swift`: adjacent special
  sections form one ordered bridge and remain independently expandable.
- `apple/Tests/NodeAdvanceGateAuthorizationTests.swift`: a stored password is
  available to the report UI only after macOS user-presence authentication;
  the UI submits one branch/node-scoped authorization and no CLI toggle exists.
- `tests/cli/test_research_report_entry_requirements.py`: every Graph report
  requirement is authored as an `obligation_requirement` special section and
  the dynamic next action discloses the exact command contract.
- `tests/server/test_research_graph_report_gate.py`: report and Edge-obligation
  coverage may be downgraded to warnings only by a current human override;
  stale identity, malformed hashes and structural report gates remain fatal.

### Acceptance contract

- The report header presents one fixed-width path selector. Its selected value
  truncates with an ellipsis; the expanded menu displays the full wrapping
  label. Refresh and export are adjacent icon-only controls.
- The gate override is changed only from native macOS UI after the signed-in
  account password is verified. A protected Keychain copy may be unlocked by
  Touch ID or the system user-presence fallback. There is no CLI command that
  changes the override.
- Override state is scoped to account, Work Package branch, current node and
  current checkpoint. It only changes missing report/obligation coverage from
  a hard error to an auditable warning; the incomplete coverage table and
  Agent remediation instruction are preserved.
- `node advance` always rejects a current-node chapter whose direct children
  are all special sections. Nested ordinary content inside a special section
  does not satisfy this structural gate, and the human override cannot bypass
  it.
- A report-requirement binding cannot be attached to an ordinary component.
  It must use `kind=special`, `display_kind=obligation_requirement`, a real
  obligation requirement ID and an explicit parent.
- A human-authorized incomplete advance returns `coverage_remediation` with
  the exact source `target_chapter_id`. `report add` defaults to the report
  tree's last chapter but accepts that explicit node chapter for a scoped
  repair.
- The override never relaxes the mandatory `report.requirement.*` special
  label, reference, identity, hash, or chapter-structure checks.
- Login, account settings login, and gate authorization reuse one native
  credential component and its protected Keychain/Touch ID credential path.
- Consecutive special-section siblings are rendered as one lightweight bridge
  of titles. Selecting a title expands only that section and preserves all
  existing typed-link actions.

## Agent-authored report component removal

### Test inventory plan

- `tests/cli/test_research_report_component_removal.py`: exercise the public
  `factortester research reports remove` command through the real report tree,
  submission sequence, Graph-container authorization and Git finalization.

### Acceptance contract

- An Agent may remove one leaf ordinary component from the current Graph
  container; the immutable Git history remains the audit record.
- Removing a non-empty ordinary component requires an explicit
  `--include-children` acknowledgement.
- Recursive removal is rejected when the target or any descendant at any
  depth is a `special` component, even if every component between the target
  and that special section is ordinary.
- Chapters, Graph-owned containers and components outside the current Graph
  container cannot be removed through the public command.
- A rejected removal retains the pending submission sequence and must be
  corrected or retried under the same sequence. A successful retry advances
  the report generation once and returns structured JSON.

### Test results

```text
conda run -n GTHT pytest -q \
  tests/cli/test_research_report*.py tests/release/test_report*.py
........................................................................ [ 34%]
........................................................................ [ 68%]
.................................................................        [100%]
209 passed in 9.00s
```

The installed GTHT `factortester research reports remove --help` command also resolved
the new command from the active source environment. The suite verifies
delete-and-recreate with the same component and binding identifiers so stale
derived locators cannot make removed content appear authoritative.

## Report structure and content-component title refinement

### Relative report insertion

- `report add` and batch `op=add` accept exactly one of
  `before_component_id` or `after_component_id`.
- The named anchor must be an existing sibling under the resolved parent.
  Invalid or cross-parent anchors leave report HEAD unchanged.
- Omitting both position fields preserves append behavior. The public CLI and
  the batch authoring path must produce the same sibling order.

### Test inventory plan

- `tests/release/test_report_tree.py`: structure nodes require a meaningful
  subject title and reject content-kind placeholders; content components
  accept an empty title and Markdown export emits no empty heading.
- `tests/release/test_report_submission_cli.py`: `report add --title` is
  optional for content components, while the same command reaches the shared
  schema gate and rejects a titleless structure node.
- `tools/cli/agent-harness/cli_anything/factortester_research/tests/test_core.py`:
  the packaged Skill explains the structure/content distinction and remains
  byte-identical to the canonical Skill.

### Acceptance contract

- `chapter`, `section`, `subsection`, and `special` organize the report and
  require a meaningful title; `正文`, `表格`, and `列表` are content-kind labels,
  not valid structure titles. Normalized English `Body`, `Table`, and `List`
  are rejected by the same rule.
- `entry`, `list`, `table`, `image`, `code`, `math`, and `result` carry report
  content and may omit `--title`; a meaningful optional title remains valid.
- One tree-schema rule protects direct adds, batch adds, and replacements.
  Click does not duplicate that semantic decision.
- Derived Markdown never writes an empty heading for a titleless content
  component.

## Local canonical factor identity freeze

### Test inventory plan

- `tests/cli/test_factor_reference_commands.py`: the public Profile factor
  reference command loads the committed local factor source, rejects a legacy
  display alias for a new immutable reference, and reports the one canonical
  executable identity.
- `tests/factors/test_factor_alias_validator.py`: the standalone batch helper
  validates four aliases with one FactorFamily source load and reports the
  canonical replacement for a legacy display alias.
- `apple/Tests/ResearchFactorSetMemberListTests.swift`: identical member-page
  requests share one in-flight CLI call and reuse the completed process-local
  result.

### Acceptance contract

- Factor authoring remains local: generated `.pyi` files provide editor types,
  while the installed FactorTester runtime loads the committed source from the
  registered factor worktree.
- A new `factor:v1` reference accepts only the exact alias regenerated by its
  FactorFamily parameter contract. Legacy aliases remain readable but cannot be
  frozen into a new factor reference or factor-set.
- Canonicalization happens when the immutable factor reference is created. A
  factor-set reuses those frozen identities and report rendering never imports
  or evaluates FactorFamily source.
- `python -m tools.factors.alias_validator` accepts one JSON batch without
  importing the full CLI. It has no persistent cache or growing JSON index;
  source revision/blob changes naturally produce a new immutable identity.

### Test results

```text
conda run -n GTHT pytest -q \
  tests/factors/test_factor_alias_validator.py \
  tests/cli/test_factor_reference_commands.py \
  tests/release/test_report_reference_authority.py \
  tests/release/test_job_artifacts.py \
  tests/release/test_report_historical_section_wrap.py \
  tests/release/test_report_batch_replace_cli.py \
  tests/release/test_report_batch_replace_submission.py
47 passed in 4.95s

DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer \
  xcodebuild test -project apple/FactorTester-Client.xcodeproj \
  -scheme FactorTester-Client-macOS -destination 'platform=macOS' \
  -only-testing:FactorTester-ClientTests/ResearchFactorSetMemberListTests \
  CODE_SIGNING_ALLOWED=NO
3 tests passed
```

## Retained Job input CLI refinement

### Test inventory plan

- `tests/cli/test_run_input_dependency_commands.py`: verify repeatable
  `--run-input` parsing, purpose-specific logical paths, UTF-8 source payloads,
  analysis scope, duplicate-name rejection, unsupported file rejection, and
  retained-input help semantics for both preview and submit.
- `tests/cli/test_factortester_client.py`: verify the real HTTP client forwards
  the same `run_input_dependencies` payload to preview and submit.
- Existing server, Job artifact, Web fixture, release materialization, and
  research Skill tests remain regression coverage for retention, download,
  clearing, retry, privacy, packaging, and Agent discovery.

### Acceptance contract

- Web, native CLI, and the Agent Skill all describe one lifecycle: uploaded
  source/configuration files are immutable Job inputs, remain available beside
  generated artifacts after terminal completion, and are deleted only when the
  user clears that Job's files.
- A generic `.py` dependency remains non-executable. Executable strategy source
  still requires the validated Strategy Hook plus `StrategySpec` path.
- Future strategy or run configuration text files use the generic input
  contract instead of requiring a new upload/storage implementation.

### Test results

```text
conda run --no-capture-output -n GTHT pytest -q \
  tests/cli/test_run_input_dependency_commands.py \
  tests/cli/test_factortester_client.py \
  tests/skills/test_factortester_research_report_authoring_skill.py
16 passed in 3.34s
```
