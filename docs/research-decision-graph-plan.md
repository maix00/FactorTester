# Research Decision Graph Implementation Plan

## Status

Working plan, not an ADR. The branch is rooted at
`fix/issue-123-factortester-cli-http` commit
`9f4a0bd7fd9583c9cb6e89641fb0bfaca166f95e`.

This document remains editable while the observed workflow, statistical
semantics, and server control plane are being validated. An ADR is deferred
until the draft graph has passed replay and shadow validation.

## Objective

Turn the existing FactorTester research harness into an evidence-driven,
versioned research decision graph without replacing the real FactorTester
workspace, RunSpec, job, or artifact lifecycle.

The graph expresses product-neutral research semantics. Product support is a
separate binding concern:

- a factor declares the product groups and data fields for which it has been
  implemented or validated;
- a capability implementation declares the product groups it currently
  supports;
- a product profile supplies market-specific data, timing, accounting, and
  risk invariants;
- FactorTester may add new product profiles without redesigning the research
  graph.

China futures is the first product profile being validated, not a permanent
boundary of FactorTester or of the research architecture.

The system must:

- derive the initial graph from existing research behavior rather than ask the
  human auditor to design a research workflow;
- reassess every node and edge against statistical rules, market semantics,
  data availability, and counterexamples;
- support multiple bounded hypothesis branches and a small number of
  independent review agents;
- keep unaffected research running when one branch encounters a capability or
  policy gap;
- let agents propose and implement graph, Skill, Harness, and code changes;
- reserve the only human user's role for server-side audit through a
  grill-me-style evidence review;
- keep Draft Graph changes in replay/shadow mode until activation gates pass.

The primary operational acceptance metric is token efficiency. The graph must
reduce repeated interpretation rather than become another large prompt.

Token control is pre-execution, not merely telemetry:

```text
create budget scope
  -> reserve max input/output before Agent, reviewer, or Skill work
  -> grant or deny atomically
  -> launch only with reservation_id
  -> ingest trusted provider/gateway usage receipt
  -> commit actual usage and release unused reservation
```

Client-reported transition telemetry is diagnostic only. Authoritative budget
usage comes from provider receipts whose HMAC is verified by the configured
gateway adapter. If no trusted adapter is configured, commit fails closed.
Skill-document, artifact-summary, and cache-read tokens are input attribution
subsets; reviewer tokens are added to primary input/output to form team total.

## Fixed Governance Decisions

1. The human is an auditor, not a research-flow author.
2. Agents may build and iterate a Draft Graph autonomously.
3. The auditor may freeze, reject, quarantine, or roll back a change, but never
   edits graph records or source code directly.
4. An agent must turn an audit disposition into a new proposal and rerun the
   relevant review and validation gates.
5. Capability changes use two-stage control:
   - audit the capability intent, permissions, and scope;
   - let agents implement and independently validate it.
6. An implementation that stays inside the approved scope may activate
   automatically. Scope drift, high-risk semantic changes, or reviewer
   disagreement re-enters audit.
7. A graph edge declares a capability contract. A registry resolves a concrete,
   versioned Skill, CLI command, or server feature.
   Product applicability belongs to the factor, data contract, implementation,
   and product profile; it does not define the graph topology.
8. External Skills may be discovered and downloaded into quarantine, but may
   not execute before the applicable audit approval.
9. Existing jobs are durable. A policy or capability gap pauses only affected
   graph branches; unrelated jobs continue.
10. Full local process files remain local. A local agent may submit a bounded
    structured trace with state, decision, evidence references, summaries, and
    hashes.
11. Deterministic code owns topology, guard, capability-binding, job-state,
    hash, and evidence-field checks. LLM review is reserved for semantic
    ambiguity and material change.
12. Runtime agents receive a local context packet, never the full graph or full
    capability catalog by default.
13. Skill metadata uses progressive disclosure. Full `SKILL.md` content is
    loaded only after a trigger matches and any required execution approval is
    present.
14. Grill audit applies to graph, statistical-policy, Skill-execution, and
    platform changes, not ordinary transitions on an already active edge.
15. The server persists capability/Skill need descriptions and descriptor
    hashes, never the selected Skill name, provider, path, body, or content
    fingerprint. The Agent chooses whether to reuse or load a matching Skill.
16. The local research session keeps a tamper-evident Skill-usage ledger with
    the actual Skill identity, version, content fingerprint, approval
    reference, description-match rationale, load/reuse mode, and token cost.
    This local audit ledger is not uploaded to the server.
17. Model identity is telemetry, not graph semantics. Codex, model, or Skill
    provider changes cannot alter graph hashes or guards. A changed external
    source invalidates the local resolution cache and fails closed until
    conformance review.
18. Capability resolution cache entries are explicitly process-local. They
    avoid duplicate deterministic work only inside one long-lived Agent
    process and are not counted as cross-process or token savings. Cross-command
    Skill reuse is decided from the local research session's hash-chained
    Skill-usage ledger; no server Skill registry or extra cache database is
    introduced.

## Existing Observed Workflow

The current Harness supplies the first observed workflow:

```text
inspect_factor_expr_dsl
  -> prepare_factor_workspace
  -> understand_factor_source
  -> build_validation_slices
  -> create_research_workspace
  -> freeze_configuration
  -> submit_run
  -> observe_jobs
  -> control_jobs
  -> audit_results
```

Existing runtime branches are coarser than the documented workflow:

```text
command failure classified as platform gap
  -> code_improvement_required
  -> resolve all open gaps
  -> research_ready

poor result decision
  -> factor_improvement_required
  -> manually edit factor workspace and rerun diagnostics
```

The sequential research phases are advisory today. The gap states are persisted
locally, but the Harness does not persist a current phase, enforce diagnostic
gates, attach validation slices to RunSpecs, or resume the exact affected
branch.

## Semantic Sources

Each normative node or edge must cite one or more of:

- an existing Harness trace or persisted FactorTester run/job/artifact;
- a FactorTester invariant or accepted ADR;
- a statistical validation rule with an attributable source;
- a market/data contract, including point-in-time availability;
- an independently reproduced empirical result;
- a correctness or safety defect that makes the existing transition invalid.

An agent opinion without evidence is not sufficient to activate an edge.

## Statistical Research Semantics

There is no single industry-standard factor-research state graph. The stable
constraints come from research protocols and statistical methods whose
preconditions differ:

- freeze the hypothesis, selection boundary, holdout role, rejection rule, and
  complete trial family before inspecting selection results;
- count every factor, transform, horizon, universe, slice, parameter, and
  adaptive revision in a trial ledger;
- use false-discovery control only when more than one trial participates in
  selection, never only on the surviving subset;
- create an authoritative, net-of-cost return stream before applying Sharpe
  uncertainty methods;
- use Deflated Sharpe only after selection among multiple recorded trials;
- use PBO/CSCV only when complete candidate return paths over common partitions
  have been retained; it does not replace a true holdout;
- reject a failed hypothesis without forcing mutation, and treat every revision
  as a new hypothesis version with a trial-ledger increment and explicit
  holdout status.

The Draft Graph therefore follows:

```text
hypothesis preregistration
  -> capability resolution
  -> point-in-time data contract
  -> hypothesis/code/timing semantics
  -> validation and trial-family design
  -> cheap in-sample diagnostics
       -> reject -> independent result audit
       -> revise -> new hypothesis preregistration
       -> authoritative backtest
            -> statistical robustness
                 -> reject -> independent result audit
                 -> revise -> new hypothesis preregistration
                 -> independent result audit
                      -> research decision
```

The audit node has no post-result loop back to statistical robustness. An
omitted or newly invented statistical method is a new research version, not a
license to tune the same holdout result.

Statistical Skills remain guidance or candidate implementations until their
exact method, inputs, outputs, version, and preconditions are approved. Runtime
Agents receive capability descriptions and triggered conditions, not a full
Skill document. The current implementation gaps for the trial ledger,
bootstrap Sharpe, FDR, Deflated Sharpe, and PBO are intentionally visible; the
graph must not silently substitute generic examples.

Factor semantics also require evidence linking the hypothesis hash to the
factor source or AST hash, financial rationale, numerical examples, and
semantic invariants. The terminal decision writes only a bounded reference to
provisional local memory containing the hypothesis, code, data, RunSpec, trial
ledger, result, failure cause, and decision. Full artifacts remain local and
behind hashes; one experiment never promotes itself into a graph edge.

The graph also borrows cross-domain research controls without copying
domain-specific publication workflows:

- [OSF Preregistration](https://www.cos.io/initiatives/prereg) supplies the
  planned-versus-unplanned distinction and permits predeclared conditional
  analyses. A branch may adapt, but the condition and alternate path must be
  frozen before the selection result is observed.
- [Registered Reports](https://www.cos.io/initiatives/registered-reports)
  supply the separation between method review and outcome review. This maps to
  proposal/reviewer/grill approval before evidence-generating execution, not to
  publication machinery.
- The
  [ASA Statement on P-Values](https://www.amstat.org/asa/files/pdfs/p-valuestatement.pdf)
  prevents a single threshold from becoming a research conclusion. Decisions
  retain effect magnitude, uncertainty, assumptions, multiplicity, economic
  meaning, and implementation evidence.
- W3C provenance standards supply execution lineage as described below.

These are complementary controls, not one universal standard. Clinical
reporting checklists and journal-specific rules are not imported as factor
research requirements.

Primary semantic sources:

- Arnott, Harvey, and Markowitz,
  [A Backtesting Protocol in the Era of Machine Learning](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3275654);
- Harvey, Liu, and Zhu,
  [The Cross-Section of Expected Returns](https://academic.oup.com/rfs/article-abstract/29/1/5/1843824);
- Bailey and López de Prado,
  [The Deflated Sharpe Ratio](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551);
- Bailey et al.,
  [The Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf);
- GIM,
  [XALPHA](https://arxiv.org/abs/2607.08332), used for the
  hypothesis-to-code and provisional-experiment-memory loop rather than as a
  statistical standard.

## Decision Graph versus Knowledge Graph

The Active Graph is not a general knowledge graph. Its normative core is a
versioned executable state graph: nodes are research states, while edges carry
deterministic guards, evidence requirements, risk, authorization, and bounded
side-effect rules. A knowledge graph answers semantic relationship and
provenance queries; it does not replace transition authorization.

Knowledge-graph standards are useful only as a compact metadata vocabulary:

- map immutable artifacts and graph versions to `Entity`, research execution
  to `Activity`, and human or software reviewers to `Agent`, following
  [W3C PROV-O](https://www.w3.org/TR/prov-o/);
- retain equivalents of `used`, `wasGeneratedBy`, `wasDerivedFrom`,
  `wasAssociatedWith`, and `wasRevisionOf` in evidence envelopes;
- use the constraint-oriented idea from
  [W3C SHACL](https://www.w3.org/TR/shacl/) when validating bounded evidence
  shapes, without introducing RDF or SPARQL into the runtime hot path.

The server continues to store normalized JSON, hashes, receipts, and bounded
references. It does not serialize the whole research history as RDF, load an
ontology into every Agent context, or ask an LLM to infer routine transitions.
If cross-project semantic discovery later becomes necessary, a read-only
knowledge projection can be derived from the authoritative state/evidence
records. It must not become a second source of transition truth.

## Graph Protocol

The first protocol version uses plain JSON and pure Python validation. It does
not require an agent framework.

### Graph

```yaml
schema_version: 1
graph_id: factor-research
version: 1
lifecycle: observed | draft | active | retired
parent_version: 0
research_semantics: product_neutral
content_hash: sha256
nodes: []
edges: []
provenance: {}
```

### Node

```yaml
node_id: inspect_factor_expr_dsl
kind: research | validation | execution | audit | capability_gap
purpose: Confirm operator semantics and causal visibility.
enforcement: advisory | deterministic | audited
required_capabilities: []
entry_evidence: []
exit_evidence: []
```

### Edge

```yaml
edge_id: inspect_factor_expr_dsl__prepare_factor_workspace
from_node: inspect_factor_expr_dsl
to_node: prepare_factor_workspace
edge_type: recommended | conditional | failure | recovery
guard: {}
required_evidence: []
counterexamples: []
risk_level: L1 | L2 | L3 | L4
```

### Capability contract

```yaml
capability_id: statistical-validation.block-bootstrap
contract_version: 1
input_schema: {}
output_schema: {}
semantic_invariants: []
permissions: []
```

Concrete implementations belong to a separate registry and bind the contract
to an exact CLI version, server feature, or code revision. For Skills, the
registry supplies reviewed descriptions and local load-time conformance data;
the Agent selects the actual runtime Skill by description. The server receives
only the capability description and descriptor hash. Each implementation also
declares `product_scopes`; the resolver reports an explicit gap when no
approved implementation supports the selected product group.

`graph capabilities` returns only compact bindings and gaps by default.
`--include-contracts` is an explicit human-audit option. Conditional
capabilities remain separate from mandatory node requirements until their
predicate matches.

### Runtime context packet

The default Agent handoff is bounded to:

```json
{
  "graph": "factor-research@v3",
  "branch": {"status": "running", "product_group": "china_futures"},
  "node": {"node_id": "cheap_factor_diagnostics"},
  "available_edges": [],
  "required_capabilities": [],
  "conditional_capabilities": [],
  "evidence_refs": [],
  "open_gaps": [],
  "token_telemetry": {}
}
```

Full artifacts, graph history, source, traces, and capability contracts stay
behind references and explicit inspection commands.

The packet also carries the fixed compact policy
`reuse_matching_runtime_skill_else_load_after_trigger_and_approval`. It does
not carry a Skill name. Exact usage is appended only to the local
`skill-usage` audit chain.

## Server Ownership

The server will own:

- immutable observed, draft, active, and retired graph versions;
- one active-version pointer per graph;
- proposals, independent reviews, validation evidence, and audit dispositions;
- capability descriptions and approval receipts, never concrete Skill identity;
- shadow replay reports and activation decisions.

The existing `user -> ResearchWorkspace -> ResearchRun -> JobAttempt` ownership
remains unchanged. Graph state must reference these identities rather than
becoming another job owner.

## Agent Roles

Use roles only when their outputs are independently useful:

- **Process Miner**: converts existing traces into an Observed Graph.
- **Semantic Reviewer**: checks market and data meaning.
- **Statistical Reviewer**: checks causal alignment, selection, multiple
  testing, sample sufficiency, and robustness.
- **Counterexample Reviewer**: searches for invalid transitions and missing
  alternatives.
- **Graph Curator**: merges evidence into a versioned proposal.
- **Capability Agent**: investigates missing Skills, CLI surfaces, data, or
  code.
- **Implementation Agent**: changes the owning branch within approved scope.
- **Audit Presenter**: produces the bounded grill-me evidence package.

Do not spawn every role for every edge. L1/L2 changes may use one proposer and
one independent reviewer only when deterministic checks are insufficient.
L1 ordinary transitions use no reviewer. L3/L4 semantic or capability changes
use the minimum relevant specialist reviewers and may enter human audit.

## Delivery Slices

### Slice 1: Observed graph protocol

- define graph, node, edge, evidence, and capability-contract validation;
- deterministically project the existing Harness plan and persisted gap states
  into an Observed Graph;
- expose human-readable and JSON CLI inspection;
- prove content hashes are stable and invalid references fail loudly.

### Slice 2: Server draft/active registry

- store immutable graph versions in the existing cache SQLite database;
- expose authenticated read APIs for observed/draft/active versions;
- expose proposal and validation APIs without adding a new login or port;
- add FactorTester CLI commands using the existing authenticated session.

### Slice 3: Evidence-conditioned transitions

- turn checklist rules into explicit guards and required evidence;
- separate diagnostic jobs from expensive backtest branches;
- bind slice plans and hypothesis counts to frozen RunSpecs;
- pause only branches whose guards or capabilities are unsatisfied.
- return only current-node state through `research-graph context`;
- make `research-graph next` a distinct deterministic readiness interface with
  candidate edges, missing guard/evidence fields, blockers, and explicit Agent
  judgment triggers;
- record per-transition input, output, cache-read, Skill-document, artifact
  summary, and reviewer token telemetry.

### Slice 4: Capability contracts

- register capability descriptions plus concrete CLI/server implementations;
- persist only capability descriptions on the server while keeping actual
  Skill usage in the local audit ledger;
- invalidate local binding caches when a provider source fingerprint changes;
- keep research semantics independent from factor and implementation product
  scopes;
- resolve the selected product profile without changing graph topology;
- create a CapabilityGap when no approved implementation satisfies a contract;
- preserve running unrelated branches;
- require audited permission before executing a newly acquired Skill.

### Slice 5: Proposal, review, and audit

- persist proposer and independent reviewer records;
- detect reviewer disagreement and scope drift;
- create grill-me evidence packages for the server auditor;
- support freeze, reject, quarantine, rollback, and re-proposal dispositions.

### Slice 6: Replay and shadow activation

- import structured historical research traces;
- replay observed and draft graphs without submitting duplicate live work;
- compare paths, blocked states, evidence coverage, cost, and outcomes;
- activate only when declared gates pass.

## Acceptance Matrix

| Requirement | Authoritative evidence |
|---|---|
| Branch derives from issue-123 | merge-base and parent commit output |
| Existing Harness behavior preserved | old Harness unit and subprocess tests |
| Default context is token-bounded | context schema excludes full graph, contracts, artifacts, and history |
| Routine packet size is bounded | `routine_context_bytes <= 6000` activation gate |
| Context and next have distinct leverage | context returns state; next deterministically returns readiness, blockers, and judgment triggers |
| Next packet is also bounded | server measures final serialized next packet and rejects anything above 6000 bytes |
| Runtime resolution is node-local | no untriggered conditionals or future-node gaps in context |
| Full contracts are opt-in | CLI subprocess test for `--include-contracts` |
| Reviewer use is risk-bounded | L1/L2 default zero; L3 one specialist; L4 proposer plus one reviewer, third only on disagreement |
| Token cost is attributable | per-node/role/Skill/artifact telemetry aggregation |
| Token regression blocks activation | graph shadow token total cannot exceed the recorded baseline |
| Shadow comparison is like-for-like | distinct owned graph/baseline run IDs must share one immutable RunSpec hash |
| Shadow totals are real and non-zero | server derives both totals from committed provider usage; `0/0` cannot activate |
| Token budget preserves work | over-budget context disables new reviewers and keeps backend jobs running |
| Work cannot start beyond budget | Agent execution requires a live pre-execution reservation |
| Usage cannot be self-reported as authoritative | commit requires a trusted provider/gateway receipt |
| Attribution does not double count | Skill/artifact/cache subsets cannot exceed input tokens |
| Context has a real response cap | server measures final serialized packet and rejects anything above 6000 bytes |
| Request hot paths are schema-free | startup migration runs once; traced graph requests execute 0 DDL and 0 `PRAGMA table_info` |
| Context database cost is history-independent | branch aggregates are updated atomically; routine context performs 0 trace-history scans |
| Context reads have a fixed upper bound | warm-cache context uses three SELECTs: owner/branch JOIN, current resolution, and token budget |
| Routine transition has bounded I/O | warm-cache zero-token transition uses two SELECTs, one branch UPDATE, and one trace INSERT |
| Immutable graph reads are cached safely | cache key includes database path, graph ID, version, and content hash; callers receive defensive copies |
| Unchanged resolution does not write | content-addressed UPSERT reports zero changed rows for identical semantics |
| Graph protocol deterministic | stable hash tests over canonical JSON |
| Invalid graphs rejected | public validator tests |
| CLI is agent-readable | installed-command JSON subprocess tests |
| Server graph is authenticated | Flask route tests with distinct users |
| Active graph immutable/versioned | SQLite service tests and API history |
| Unaffected jobs continue | integration test with two independent branches |
| Skill cannot execute unapproved | capability registry and execution-gate test |
| Server stores no Skill identity | SQLite persistence inspection and server input rejection tests |
| Local Skill usage is auditable | hash-chained session ledger records identity, approval, load/reuse, and tokens |
| Provider updates fail closed | source fingerprint mismatch invalidates cache and creates an explicit gap |
| Cache scope is truthful | capability output declares `cache.scope=process`; separate installed CLI calls do not claim a hit |
| Model replacement is semantics-neutral | model/Codex telemetry changes do not change semantic cache or graph hash |
| Provider roots are relocatable | environment-root conformance tests for Codex and external providers |
| Scope drift re-enters audit | proposal lifecycle integration test |
| Auditor cannot edit graph directly | API authorization/transition tests |
| Draft does not constrain live work | shadow-mode integration test |
| Active graph can roll back | activation-pointer and audit-trace test |
| Historical replay is non-mutating | run/job count and artifact integrity test |
| Real backend remains authoritative | end-to-end CLI against FactorTester API |

Activation validation must include:

```json
{
  "token_efficiency_passed": true,
  "token_measurement_refs": {
    "routine_instance_id": "shadow-instance-id",
    "routine_branch_id": "shadow-branch-id",
    "baseline_run_id": "baseline-research-run-id"
  }
}
```

The server requires distinct graph and baseline research runs with the same
RunSpec hash. It recomputes context bytes, conditional/gap leakage, Agent
execution count, and both non-zero token totals. Token totals come only from
committed provider usage receipts; client-submitted metric values are ignored.
Activation accepts only evidence marked `server_derived`.

## Deferred Decisions

These are empirical engineering questions for agents to resolve, not questions
for the auditor:

- whether orchestration eventually uses LangGraph, OpenAI Agents SDK, or a
  smaller internal runner;
- the exact statistical edge library shared across products and the
  product-profile overlays needed by China futures;
- activation thresholds for replay coverage and reviewer agreement;
- whether semantic retrieval needs FTS only or later benefits from embeddings;
- which capability gaps justify a Skill versus a FactorTester code change.
