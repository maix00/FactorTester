# TrialPlan synthesis

Use this mode only for an open obligation whose answer is actionable with the
available authoritative backend.

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
- selection, validation, and untouched sample roles;
- comparisons and relevant alternatives;
- rejection, revision, continuation, and stopping rules;
- multiplicity family and correction or a justified no-adjustment rule;
- diagnostics that distinguish mechanism from implementation failure;
- resource boundary and expected information gain.

Never select a threshold after looking at the outcome. A changed frozen body is
a new TrialPlan version. Recency alone does not create out-of-sample status:
the latest interval or prospective stream is untouched only when it was sealed
after the factor, selection boundary, and TrialPlan were frozen. Historical
regime evidence seen during selection remains regime validation, not holdout.

## Output

Return the canonical TrialPlan body plus the selected obligation reference and
expected evidence kind. If a required operator, strategy behavior, timing rule,
authoritative data field, frozen identity, or pre-outcome decision rule is
unavailable, return a Capability Gap without approximating it. You may return a
clearly labeled `provisional_outline` to preserve useful design work, but it is
not a canonical TrialPlan and cannot authorize execution.
