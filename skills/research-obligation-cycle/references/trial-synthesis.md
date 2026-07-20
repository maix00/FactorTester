# TrialPlan synthesis

Use this mode only for an open obligation whose answer is actionable with the
available authoritative backend.

Before emitting a plan, classify each considered obligation as
`actionable_trial`, `semantic_resolution`, `provenance_repair`, `backend_gap`,
`infeasible`, or `bounded_unknown`, and attach a compact reason reference.
Validate the bounded synthesis output with
`scripts/validate-trial-synthesis.py`. A canonical TrialPlan may reference only
`actionable_trial` obligations. This actionability assessment is semantic and
reviewable; it is not inferred from `materiality`, so a `non_blocking`
obligation is not automatically non-actionable.

## Select

Prioritize decision-blocking obligations, then tests with high expected
information value relative to data, compute, token, and multiplicity cost.
Do not create a TrialPlan for a semantic correction, provenance repair, known
backend defect, infeasible question, or bounded unknown that cannot change the
decision.

## Freeze the design

Bind the plan to the current Decision Contract, obligation, Claim scope,
factor-family version, parameter coverage, product universe, data snapshot,
signal availability, outcome horizon, sample roles, costs, margin/accounting,
RunSpec members, methodology, and graph branch.

Before freezing the plan, require compact references for the user-confirmed
product/source scope, the current Data Availability Profile, and every
material data-availability obligation. Also bind relevant trading calendars,
market-regime/comparison definitions, selection history and multiplicity
ledger, execution timing, capacity, resource limits, and permitted use.
Availability is one input, not sufficient authority to synthesize a plan.
If a required availability obligation remains open, either design a trial that
services it first or return a bounded gap; never infer missing data.

Specify:

- primary and secondary outcomes;
- an obligation-driven ordered stage policy and its sample roles;
- comparisons and relevant alternatives;
- rejection, revision, continuation, and stopping rules;
- multiplicity family and correction or a justified no-adjustment rule;
- diagnostics that distinguish mechanism from implementation failure;
- resource boundary and expected information gain.

Do not confuse sample stage with comparison arm: `selection`, `validation`,
`confirmation`, and `holdout` describe sample use; `candidate`, `control`, or
another declared `trial_role` describes a comparison member. The initial plan
freezes all stage sample identities, RunSpecs, comparisons, outcomes, criteria,
and stopping/multiplicity rules. A child version may update bounded obligation
references, but may not replace that frozen trial design after outcome
inspection. A new factor or design starts a new hypothesis and TrialPlan
lineage; it does not reuse a protected sample. Keep the old plan and exposure
history immutable. Release its current binding only on the server-owned
new-hypothesis transition, then freeze the replacement as version 1 of a new
plan identity.

Use only the stages justified by the obligations. Direct confirmation is
allowed only with an explicit entry-basis reference. Stage advancement is an
adjudication recommendation and becomes effective only after an accepted
decision; never invent a client completion boolean.

For temporal-transfer obligations, prefer a preregistered expanding or rolling
walk-forward sequence when the available history and frequency support it. For
example, one stage may use 2024 for selection and seal 2025 as holdout; only
after that stage is adjudicated may a new stage or hypothesis lineage use the
now-exposed 2025 interval and seal 2026 as the next holdout. This is an example,
not a universal calendar. Intraday factors may use month- or day-scale stages
when they contain enough independent market variation. Apply purge or embargo
where overlapping labels, lookbacks, positions, or execution horizons would
leak information across adjacent stages.

For product-transfer obligations, freeze the product membership and whether
each product is selection, validation, confirmation, or holdout evidence.
Testing different products is transfer evidence only within that declared
scope; an unseen product is not out-of-sample unless it was sealed before
selection.

Bind each stage to its market-state definition and relevant event-evidence
references. Report whether a result is broad, regime-dependent,
instrument-specific, or confounded by a material interval event. Post-outcome
event explanations create exploratory obligations and a new trial; they do not
alter the current stage's predeclared interpretation. Freeze an independent
event-source cutoff with every walk-forward stage so later event labels cannot
enter an earlier context snapshot.

Never select a threshold after looking at the outcome. Recency alone does not
create out-of-sample status: the latest interval or prospective stream is
untouched only when it was sealed after the factor, selection boundary, and
TrialPlan were frozen. Historical regime evidence seen during selection
remains regime validation, not holdout. When future-transfer relevance is part
of the decision, preserve the latest feasible interval or prospective stream
as a protected final stage instead of consuming it during earlier selection.
After an Agent uses a holdout result to alter a factor, parameter, event
hypothesis, or rule, reclassify that interval as
`historical_adaptive_evidence`; it is no longer pristine OOS. Create a new
forward obligation for the next available sealed interval.

Keep data-delivery evidence grades explicit:

- `live_execution_evidence` requires real orders, fills, fees, slippage,
  rejects, and funding constraints;
- `forward_shadow_evidence` covers prospective paper/shadow execution, with
  `latency_class=delayed` when the feed is delayed;
- `historical_simulation_evidence` covers every replay of historical data,
  including tick-by-tick playback.

Forward shadow evidence can test signal generation, drift, and prospective
stability, but it cannot discharge actual fill, impact, or latency obligations.
Live evidence remains bounded to the market states actually observed.

## Output

Return a canonical TrialPlan schema version 4. Bind its
`decision_contract_hash` and `methodology_hash` to the current checkpoint, and
put every selected serviceable obligation ID in the bounded
`obligation_refs`; do not copy obligation bodies. Include `stage_policy` and
`parent_trial_plan_hash` (`null` for the first version). Return the expected
evidence kind separately. If a required operator, strategy behavior, timing rule,
authoritative data field, frozen identity, or pre-outcome decision rule is
unavailable, return a Capability Gap without approximating it. You may return
a clearly labeled `provisional_outline` to preserve useful design work, but it
is not a canonical TrialPlan and cannot authorize execution.
