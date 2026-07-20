# Market-context event search

Load this reference only when an observed market-state or instrument
difference could change the bounded research decision. The goal is a
`market_context_heterogeneity` obligation, not a complete causal story.

## Freeze the search boundary

Before searching, record:

- the triggering EvidenceEnvelope reference, interval, products, and factor;
- the predeclared performance difference or anomaly;
- known event or regime hypotheses and expected direction/horizon;
- the source cutoff, query scope, source tiers, and search/token budget.

Do not search every window. Trigger one directed search only for a
decision-blocking break, cross-instrument heterogeneity, execution/liquidity
anomaly, or a preregistered institutional event.

## Find point-in-time event facts

Prefer timestamped primary sources from exchanges, regulators, central banks,
statistical agencies, or issuers. Use academic or authoritative databases for
method and corroboration. Treat news as discovery material until a material
event is verified against a primary source.

For each retained candidate record only:

- `event_occurred_at` and `publicly_available_at`;
- source reference and tier;
- affected products or assets;
- proposed mechanism, expected direction, and horizon;
- plausible confounders;
- `discovery_mode=preregistered|posthoc`;
- evidence limitations.

Use `publicly_available_at`, at the research frequency's required precision,
as the information boundary. Do not backfill a later revised event label into
an earlier TrialPlan.

## Prevent narrative selection

Retain references and counts for all inspected candidates, including
directionally inconsistent events. Do not keep only a matching story. Limit
the compact proposal to at most three distinguishable, falsifiable mechanisms
per trigger; archive the rest by reference.

A post-outcome event search is exploratory. It may propose a new obligation
and an independently frozen TrialPlan on an unexposed interval or product. It
cannot alter the current test, prove causality, or discharge statistical
robustness. Describe evidence as `consistent_with`, `inconsistent_with`, or
`not_distinguishable` unless a separately justified causal design exists.

## Control Agent and token cost

Give the event-search Agent only the anomaly summary, interval, products,
source cutoff, and existing event references. Cache by
`(market, interval, query_hash, source_cutoff)` and return structured summaries,
not page bodies.

Use one event-research sub-agent only when the question is decision-blocking,
crosses jurisdictions or many products, contains conflicting source
timestamps, or requires independent checks of multiple mechanisms. Otherwise
the primary Agent performs one bounded directed search. When reliable
point-in-time evidence is unavailable or the mechanism is not distinguishable,
record a `bounded_unknown` with search scope and reopening condition.
