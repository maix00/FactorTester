# Grill Record: Pre-numbering Phase

## Provenance and limitation

The early design discussion did not emit stable question numbers. This record
therefore follows the chronological design branches visible in the task,
external audit attachments, repository plan, and commits. It does not invent
questions 1–47 or claim verbatim recovery where the durable record contains
only a compacted conclusion.

## Harness and research-method boundary

**User concern.** The Harness appeared to be only a CLI caller or a fixed
flowchart derived from `cli-anything`; the desired research process instead
needed branches, adaptive next steps, multiple Agents, and a statistical
hypothesis/validation discipline.

**Resolved meaning.** The Harness is the Agent-facing contract around the real
FactorTester workspace, RunSpec, job, artifact, capability, and evidence
lifecycle. `cli-anything` contributes a deterministic, scriptable interface,
but does not define the research method. The research method is a versioned
graph with deterministic guards and bounded semantic judgment.

**Rejected extremes.**

- A fixed linear flow cannot represent revision, early stopping, capability
  gaps, counterevidence, or multiple admissible next states.
- A free-form LLM workflow cannot guarantee evidence fields, reproducibility,
  authorization, or bounded token/database cost.
- LangGraph may be an implementation option, but it is not the domain model and
  cannot become a required paid service or graph identity.

**Evidence and impact.** Existing FactorTester lifecycle code and the
`cli-anything` Harness were treated as the runtime baseline. The plan must
preserve production paths rather than build a parallel research engine.

## Industry and statistical discipline

**User concern.** A tool catalog does not tell an Agent how to analyze a
factor. The system needed industry/statistical semantics, including
hypothesis formation, validation, multiple testing, robustness, and an
evidence-backed way to improve the research process itself.

**Resolved meaning.**

- Deterministic code validates topology, required evidence, hashes, job state,
  product support, and permissions.
- LLM judgment is reserved for economic/market meaning, ambiguity,
  counterexamples, and material graph change.
- Research must distinguish discovery, preregistration, diagnostics,
  authoritative backtest, robustness, audit, and decision.
- Trial history, failures, holdout use, selection choices, and stopping
  conditions must remain auditable.
- Backend computation is trusted through conformance evidence unless a concrete
  anomaly triggers a specialist review.

**Rejected extremes.**

- Treating one p-value, IC, Sharpe, or `$Rev` as proof of universal validity.
- Rerunning or modifying an exposed hypothesis without recording selection.
- Starting a backend-code review on every run.

**Evidence and impact.** Vibe-Trading research Skills, FactorTester Harness
behavior, quantitative-research guidance, external statistical literature, and
the XALPHA/CogAlpha material informed the plan. Exact statistical capabilities
remain capability contracts rather than mandatory full-document context.

## Experience, memory, and graph evolution

**User concern.** Temporary decisions made during research should remain
searchable and reviewable. Repeated or norm-supported decisions may deserve a
new graph edge, but the initial graph is still being formed by one developer
and should not prematurely become a multi-user server consensus system.

**Resolved meaning.**

- One experiment creates local **Provisional Memory**, not an active edge.
- The local record preserves decisions, alternatives, failures, evidence
  references, and replay identity.
- A deterministic trigger may open a server-side generalization review when
  repetition, counterevidence, a capability gap, or a documented norm makes a
  reusable rule plausible.
- A Server Maintenance Agent proposes the graph change; the sole human acts
  only as auditor in a one-question-at-a-time review.
- Multi-user pooling, automatic submission, and server promotion of user
  decisions are deferred.

**Rejected extremes.**

- Equating a successful experiment directly with an active edge.
- Uploading complete local process files or user factor source as global
  memory.
- Asking the human to author the research graph in natural language.

## Skill discovery, authorization, and audit

**User concern.** Agents should find useful local or online Skills and reuse
previously loaded ones, but must never execute newly obtained Skill content
without approval. The system must survive Codex, model, and Skill-provider
updates.

**Resolved meaning.**

- Server-side graph records persist need descriptions and descriptor hashes,
  not selected Skill names, providers, paths, or bodies.
- A runtime Agent sees descriptions and decides whether to reuse a locally
  matching implementation or load another.
- Full `SKILL.md` is progressively loaded only when the need triggers and the
  required execution approval exists.
- Local research keeps a tamper-evident Skill-usage ledger with actual identity,
  version/fingerprint, approval, rationale, load/reuse mode, and token cost.
- A changed Skill source invalidates the local resolution and requires renewed
  conformance/authorization as applicable.

**Rejected extremes.**

- Hard-coding Vibe, Codex, or one Skill repository into graph semantics.
- Sending the full Skill catalog or Skill bodies to every Agent step.
- Letting discovery imply execution permission.

## Token, context, reviewer, and database limits

**External audit concern.** Whole-graph capability resolution, complete
contracts, full artifacts, repeated reviewers, and hot SQLite writes would
consume tokens and create false early blockers.

**Resolved meaning.**

- Runtime context contains only the current node, triggered candidate edges,
  required current capabilities, evidence references, open gaps, and budget.
- Conditional predicates execute deterministically; future-node capabilities
  are not resolved.
- Routine L1/L2 work starts no reviewer. Higher-risk work uses the minimum
  relevant reviewer set and reuses unchanged review hashes.
- Grill audit reviews only change diffs.
- Token reservation occurs before Agent/reviewer/Skill work; authoritative
  usage comes from a trusted provider/gateway receipt.
- Unchanged heartbeat performs zero LLM work and zero database writes.
- SQLite stores low-frequency authoritative facts; progress, stdout, large
  results, and full prompts remain outside hot tables.

**Acceptance direction.** Context/next packet sizes, token totals, cache hits,
SQL statement counts, WAL growth, lock waits, and graph-versus-baseline shadow
cost are release gates rather than post-release observations.

## Client workspace, profiles, and source retention

**User concern.** A Research Agent must start factor work immediately without
being blocked by Pylance errors, hidden paths, login/profile friction, or
server source assumptions. UI should configure settings, not approve Agent
actions.

**Resolved meaning.**

- Generated factor workspaces include the typed SDK/stubs required for
  Pylance/Pyright and must pass a real client-style type check.
- Settings such as paths, profile selection, source-sync policy, and storage
  limits are managed through UI/CLI configuration surfaces.
- UI uses a human profile while managing all human and Agent profiles; each CLI
  Agent may claim its own profile/Agent ID.
- Approval happens in the relevant Agent conversation. UI can display past
  approvals but cannot grant them.
- Local factor-family files can run directly. Server jobs and factor-library
  metadata remain, but source and reconstructable formulas are not retained
  unless the configured source channel explicitly permits it.

**Correction retained.** “Do not retain source” never meant “do not register
the factor.” Identity, version, parameters/schema that do not reconstruct the
formula, job records, results, evidence, and audit metadata remain eligible for
server storage.

## Product scope and factor construction

**User concern.** China futures matters now, but product support should not
distort the general research architecture. The Agent also needs to discover
main/auxiliary factors and construct richer single factors without silently
crossing into multi-factor portfolio research.

**Resolved meaning.**

- Product applicability is a factor/data/implementation/profile binding, not
  graph topology.
- FactorTester may add other product profiles without redesigning the research
  graph.
- An auxiliary input can transform or gate one final factor expression, or
  condition a trading strategy.
- Independently predictive signals selected or weighted together require
  deferred multi-factor capabilities even if they output one column.
- Both single-factor and future multi-factor signals may be strategy
  conditioned; the evidence must state whether it belongs to the factor
  construction or factor-plus-strategy combination.
- Missing admissible general operators or strategy capabilities create
  mandatory platform work under normal approval, implementation, and release
  controls.

## Transition to numbered grill

The discussion began stable numbering at question 48 while refining mandatory
capability completion, conditional factor enrichment, Agent Flow, candidate
discovery, trial accounting, and audit persistence. See:

- [questions 48–72](0048-0072.md)
- [questions 73–93](0073-0093.md)
- [questions 94 onward](0094-current.md)
