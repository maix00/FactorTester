---
name: research-obligation-cycle
description: Guide a factor-research Agent through first-principles obligation discovery, selective TrialPlan synthesis, factual-evidence adjudication, bounded search exhaustion, or methodology-impact review. Use when the current Active Graph packet requests one of those semantic capabilities, when evidence creates or changes an unresolved research question, or when a changed graph or methodology may reopen prior research. Do not use for routine deterministic guards, backend computation, or ordinary graph transitions.
---

# Research Obligation Cycle

Use this Skill only after the current Agent conversation has approved this
exact local content or a fingerprint-valid reuse. Keep execution, approval,
provider identity, and token use in the local Harness audit; never submit Skill
identity to the server.

## Select exactly one mode

Read the current local Graph packet and load one reference:

- `discover`: read [references/obligation-discovery.md](references/obligation-discovery.md).
- `synthesize`: read [references/trial-synthesis.md](references/trial-synthesis.md).
- `adjudicate`: read [references/evidence-adjudication.md](references/evidence-adjudication.md).
- `exhaustion`: read [references/search-exhaustion.md](references/search-exhaustion.md).
- `impact`: read [references/methodology-impact.md](references/methodology-impact.md).

Do not preload the other modes. If the packet does not establish a trigger,
return a capability gap instead of guessing.

## Preserve the protocol boundary

- Treat `EvidenceEnvelope` v2 as facts, never as a conclusion.
- Reject generic or unbound research evidence. Semantics evidence must bind the
  current Contract and methodology; trial-derived evidence must also bind the
  TrialPlan and RunSpec. Local `control_command` audit is not research evidence.
- Treat the adjudication next action as a proposal; only an accepted decision
  authorizes a server-derived route.
- Never request or read legacy EvidenceEnvelope v1.
- Bind every proposal to the current Decision Contract, TrialPlan when
  applicable, methodology, and Claim scope. The Harness binds submission and
  replay to the current checkpoint hash; do not invent or copy that hash into
  a server proposal field that does not define it.
- Put the settled local research/proposer Agent invocation ID that authored
  the proposal in `proposer_invocation_id` and include it in the transition's
  `agent_invocation_ids`. This is execution provenance, not Skill identity.
- When the current node is `research_decision`, carry a material discovery,
  adjudication, or closure event on its declared self-edge. Do not create a
  second Graph, move the branch, or emit an empty Research Cycle event.
- Express interpretation as a proposal. Only an authority-bearing decision
  changes accepted Claim, obligation, or closure state.
- Keep exploratory support exploratory and open a confirmation obligation.
- Preserve explicit Claim and obligation no-ops.
- Use the real FactorTester backend through the existing Harness for
  computation; do not approximate a missing operator or backend capability.

## Validate before submission

For obligation discovery:

```bash
python scripts/validate-obligation-proposal.py --input proposal.json
```

For any paired evidence adjudication:

```bash
python scripts/validate-adjudication-proposal.py --input proposal.json
```

For selective TrialPlan synthesis:

```bash
python scripts/validate-trial-synthesis.py --input synthesis.json
```

Treat a nonzero exit as a proposal defect. The scripts validate bounded,
provider-neutral shapes; the server remains authoritative for current hashes,
state transitions, and approval.

If an identity, authoritative input, or backend capability required by the
selected mode is absent, do not fabricate a submission. Return a compact gap
with `missing_inputs`, `blocked_output`, and `suggested_transition`. A
non-submittable design sketch may be included only as `provisional_outline`
and must not be labeled a TrialPlan or proposal.

## Return a compact result

Return only:

- selected mode and trigger;
- proposal or TrialPlan reference;
- current identity hashes;
- evidence references, not artifact bodies;
- unresolved capability gaps;
- suggested next Graph transition.

Do not return the full Graph, capability catalog, trace history, Skill body, or
raw stdout/stderr.
