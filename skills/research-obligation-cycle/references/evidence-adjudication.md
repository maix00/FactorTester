# Evidence adjudication

Use this mode when current EvidenceEnvelope v2 facts may change a Claim,
obligation, or bounded interpretation.

## Separate fact from inference

Verify envelope identity, RunSpec, TrialPlan, factor/data/backend versions,
command outcome, metrics, conflicts, limitations, and artifact references.
The envelope does not decide anything. Never read EvidenceEnvelope v1.

## Propose paired changes

1. Match the evidence to a preregistered rule or classify it as exploratory,
   semantic, conflicting, deterministic, or non-standard.
2. State the current and proposed Claim evidence state at the same scope.
3. State the current and proposed obligation state and cite its discharge
   criterion.
4. Give a Decision Warrant with finding, rule, alternative, limitation, and
   re-entry references.
5. Use an explicit no-op when one side does not change.

A failed preregistered test may discharge the test obligation while
contradicting its Claim. A favorable post-hoc result remains exploratory and
opens a confirmation obligation. A provenance failure may open an obligation
without strengthening any Claim.

Use the protocol states `absent`, `open`, `serviced`, `discharged`, `bounded`,
`rejected`, or `reopened`. When evidence satisfies an obligation's declared
criterion but cannot change the Claim because its proposition, preregistered
rule, identity, or scope is missing, propose an explicit Claim no-op and the
justified obligation delta. Missing inputs that prevent identity or criterion
verification instead produce a Capability Gap and no submittable proposal.

## Authority

Use deterministic or preregistered authority only for exact predeclared rules.
Material semantic, post-hoc, non-standard, or conflicting inference requires
one relevant independent reviewer. Reserve and settle that reviewer invocation
with actor role `reviewer`, authority scope `local_research`, and task reference
`research-cycle-adjudication:<proposal_hash>`. Put its invocation ID in the
decision's `authority_ref` and in the transition's `agent_invocation_ids`.
The reviewer must have a different principal and lineage from the proposal
author. Do not add routine reviewers.

## Output

Produce one bounded AdjudicationProposal. A separate authority-bearing
AdjudicationDecision accepts, rejects, or requests revision. Never partially
apply a paired delta. The proposal contains `schema_version`, `proposal_id`,
`proposer_invocation_id`, the Contract, TrialPlan, and methodology hashes,
evidence references, Claim and obligation delta arrays or their explicit
no-op reasons, and one Decision Warrant. Validate that exact object with the
script named in the parent Skill.
