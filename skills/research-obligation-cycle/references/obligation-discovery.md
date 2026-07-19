# Obligation discovery

Use this mode when a Decision Contract is new, evidence exposes a new material
question, or the current checkpoint may omit a first-principles alternative.

## Inputs

Read only the current Decision Contract, compact Claim and obligation state,
applicable evidence references, permitted use, and current methodology hash.
Do not read legacy evidence or a sealed baseline conclusion.

## Discover

1. Restate the bounded decision and what is genuinely unknown.
2. Derive candidate questions from the factor's economic meaning, information
   timing, measurement construction, universe, data provenance, selection
   process, market-state dependence, execution path, and plausible competing
   mechanisms.
3. Add a question only when answering it could change the bounded decision,
   scope, construction, TrialPlan, or permitted use.
4. Give it a falsifiable epistemic question, scope, materiality, and discharge
   criterion. The criterion may be empirical, semantic, provenance-based, or a
   deterministic backend check.
5. Link it to the affected Claim. If there is no new empirical evidence,
   propose an explicit Claim no-op.

The lenses above are prompts, not a universal checklist. Create factor-specific
obligations when first principles require them, and omit irrelevant lenses.

## Reject low-value obligations

Reject a candidate that merely restates a metric, duplicates an open
obligation, cannot affect the authorized decision, has no observable discharge
path, is outside permitted scope, or substitutes for a deterministic guard.
Record a bounded unknown instead when no feasible test exists.

## Output

Produce an AdjudicationProposal whose new obligation delta is
`absent -> open` and includes the complete obligation body. Cite the discovery
lens and current evidence references. Do not strengthen the Claim merely
because a plausible question was articulated.
