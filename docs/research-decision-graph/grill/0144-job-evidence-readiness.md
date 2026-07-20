# Grill 144: trusted Job evidence readiness

## Observed conflict

Real v5 acceptance produced five successful, server-trusted Jobs across the
SgCCS replay and trend-factor branches, but no accepted graph evidence delta.
The direct `authoritative_backtest -> statistical_robustness` edge both bound
the terminal JobAttempt and entered a node requiring
`performance.bootstrap-sharpe`. Target-capability validation ran in the same
transaction, so the missing downstream capability rolled back the factual Job
binding. Both branches then paused through the generic capability-gap edge.

This made an unavailable interpretation method erase graph visibility of
computation that had already completed and passed server assurance.

## Question and disposition

Question 144 asked whether to split authoritative JobAttempt fact binding from
downstream statistical capability resolution by adding a capability-free
`job_evidence_ready` node, instead of retaining rollback behavior or adding a
Job-specific exception to the generic gap edge.

The human auditor answered `好`; option A was accepted.

## Accepted topology

```text
authoritative_backtest
  -- trusted terminal JobAttempt / bind_job_attempt -->
job_evidence_ready
  -- downstream bindings resolved --> statistical_robustness
  -- downstream binding missing --> capability_gap
```

`job_evidence_ready` means only that the server retained a trusted factual
EvidenceEnvelope with immutable run and trial identity. It has no required
capabilities and makes no claim about robustness, usefulness, or research
completion.

## Rejected alternatives

- Keep the direct edge and allow missing target capabilities to roll back Job
  evidence: rejected because interpretation availability must not rewrite
  completed computation.
- Teach the wildcard capability-gap edge to bind JobAttempts: rejected because
  it gives a generic failure path hidden source-specific behavior and duplicates
  the successful evidence transition.
- Implement bootstrap Sharpe as part of this repair: rejected because the
  method remains separately deferred and is not necessary to repair evidence
  continuity.

## Complexity and resource bounds

- Reuse the existing branch, trace, JobAttempt assurance, EvidenceEnvelope, and
  `bind_job_attempt` transaction.
- Add no table, receipt, reviewer, Agent call, polling loop, or database read on
  routine context construction.
- Carry only the bounded evidence reference and envelope already produced by
  the server; do not load Job output or Skill content into Agent context.
- The intermediate node is deterministic and therefore consumes no model
  tokens.

## Acceptance proof

Tests must establish that:

1. a trusted terminal Job transitions to `job_evidence_ready` and retains its
   server-owned envelope;
2. forged terminal or artifact facts remain rejected;
3. a Job owned by another branch remains rejected;
4. failure to resolve statistical capabilities after that transition leaves
   both the checkpoint and bound Job envelope unchanged; and
5. the draft graph exposes only the two-stage topology, with no legacy direct
   edge.

## Grill 145: bounded gap closure and recovery

The follow-up was accepted with a smaller persistence design:

- a paused downstream gap may record the existing Research Cycle `blocked`
  closure after its required independent challenge;
- that closure keeps Claims and open obligations unchanged and is neither
  validation success nor factor rejection;
- recovery returns to `job_evidence_ready` and re-resolves the downstream
  capability without rerunning the accepted Job;
- the server derives the permitted recovery origin from the existing latest
  trace edge, so no `resume_node_ref`, column, table, or history scan is added;
  and
- only stale immutable RunSpec, TrialPlan, backend, artifact, or evidence
  identity requires a new JobAttempt.

A blocked run may truthfully complete an acceptance receipt but cannot claim
that the graph is release-ready.

### Capability diagnosis is not code modification

`capability_gap` classifies what is missing and why research cannot currently
advance. It does not own implementation. Resolution can come from an already
approved binding, a separately approved local Skill, data access, or a
source-authorized backend change.

Backend modification remains a Maintenance/code-improvement concern with code
access, tests, revision, deployment, and audit authority. Ordinary users and
client Agents cannot perform it. The research branch remains paused while that
work occurs and consumes only the resulting approved-binding fact. This keeps
research semantics independent from software-delivery mechanics.

## Grill 146: immutable cross-version continuation

The real v5 acceptance branches already own immutable ResearchRun and
JobAttempt bindings. Updating their `graph_version` would reinterpret history;
creating an ordinary v6 branch would correctly fail Job binding. The accepted
solution preserves both invariants:

1. The source instance, branch, trace, ResearchRun binding, and Job remain
   unchanged.
2. A read-only preview hashes the owner, source and target graph hashes,
   source trace and checkpoint, workspace, Job evidence, target version, and
   `job_evidence_ready` node.
3. One exact-hash Maintenance Gate must bind that descriptor and the approved
   `continue_graph_branch` action.
4. The server rechecks Contract, Methodology, TrialPlan, RunSpec, workspace,
   terminal assurance, artifacts, direct graph parentage, active target, and
   capability-free target node.
5. Gate consumption and insertion of one target instance, branch, and
   `__graph_continuation__` bootstrap trace share a transaction.
6. The Job envelope gains a bounded migration limitation and a new hash. The
   Job itself is neither rebound nor rerun.

The continuation uses the existing Graph and Maintenance tables. It adds no
catalog, migration, lineage, receipt, or evidence table, and shadow replay
understands the one bounded bootstrap trace without loading source history.
