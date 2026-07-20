# Search exhaustion

Use this mode when the Agent cannot identify another meaningful TrialPlan or
obligation that could change the current bounded decision.

## Assess the frontier

Summarize declared search regions, attempted trials, open blocking obligations,
remaining unknowns, discovery lenses used, candidate next trials, and why each
excluded candidate cannot change the decision or exceeds an explicit resource
boundary.

The proposal's coverage summary must truthfully mark
`declared_scope_assessed`, `stopping_rules_assessed`, and `frontier_assessed`.
The two closure dispositions `decision_ready` and
`exhausted_without_support` require all three to be true. Do not set them from
the absence of a new idea; cite the corresponding bounded references.

“No idea” is not exhaustion. Challenge the checkpoint from factor semantics,
timing, measurement, alternative mechanisms, regime dependence, selection,
execution, and provenance. Load no other mode reference while doing so.

## Choose a truthful disposition

- `decision_ready`: no unresolved blocking obligation or actionable frontier,
  and the Contract's bounded action can now be taken even when that action is
  rejection, watchlisting, or another limited permitted use;
- `exhausted_without_support`: the authorized question sought evidential
  support, adequate search ended without it, and that absence is itself the
  truthful closure disposition;
- `stopped_by_resource_boundary`: useful work remains but exceeds authority or
  budget;
- `blocked`: a capability, data, or backend gap prevents adjudication;
- `superseded`: the Contract or Claim no longer governs the work.

Choose between `decision_ready` and `exhausted_without_support` from the
Decision Contract's decision and permitted use, not from the Claim label alone.

Bound unresolved unknowns instead of pretending to clear them. Define concrete
re-entry predicates for new evidence, scope, methodology, graph, data, or
backend changes.

## Independent challenge

Submit a SearchExhaustionProposal bound to current Claim and obligation
projection hashes and its settled `proposer_invocation_id`. Closure requires
one independent challenge decision. Reserve and settle that reviewer with task
reference `research-cycle-closure:<proposal_hash>`, put its invocation ID in
the decision's `authority_ref`, and include both current invocations in the
transition's `agent_invocation_ids`. The reviewer principal and lineage must
differ from the proposal author. A rejected or revision-requested closure
changes no accepted state.

Closure remains defeasible. An accepted adjudication that creates or reopens a
decision-blocking obligation invalidates both accepted and pending closure in
the same replay event. A rejected proposal or a non-blocking obligation does
not.
