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

## Deliberately unresolved follow-up

This decision does not define whether a branch paused for a missing downstream
capability can reach a bounded non-success closure, or exactly how it returns
to `job_evidence_ready` when that capability later becomes available. Those
closure and recovery semantics require the next grill decision and must not be
inferred from this topology change.
