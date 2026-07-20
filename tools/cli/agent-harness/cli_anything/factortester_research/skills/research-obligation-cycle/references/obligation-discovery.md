# Obligation discovery

Use this mode when a Decision Contract is new, evidence exposes a new material
question, or the current checkpoint may omit a first-principles alternative.

## Inputs

Read only the current Decision Contract, compact Claim and obligation state,
applicable evidence references, permitted use, and current methodology hash.
Do not read legacy evidence or a sealed baseline conclusion.
Load only the single current Claim or obligation body referenced by
`detail_ref` when its full question, scope, or discharge criterion is
necessary; do not load the whole checkpoint or trace history.

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

For data availability, derive the obligation from the exact product, field,
frequency, history, visibility-time, latency, and permitted-use needs of the
decision. A preliminary availability profile is feasibility evidence, not a
universal discharge. Use the deterministic `data-availability.inspect`
capability to collect facts; do not use this Skill to probe files or providers.
Do not treat provider configuration, account access, or quote entitlement as
proof of usable coverage, latency, point-in-time integrity, or reproducibility.
Keep routine existence, permission, and exact predeclared coverage checks as
deterministic constraints or Capability Gaps. Create an obligation only when
the remaining data question could change the bounded research decision,
representativeness, transfer boundary, TrialPlan, or permitted use.

The lenses above are prompts, not a universal checklist. Create factor-specific
obligations when first principles require them, and omit irrelevant lenses.

## Discover transfer and market-context obligations

For each researched factor, ask whether the bounded decision depends on
transfer across time, market state, or instruments. When it does, consider:

- materially different time intervals and market environments rather than one
  aggregate full-period result;
- heterogeneous behavior across the authorized products or instruments,
  including concentration in one product;
- interval-specific events that could affect the selected instrument, such as
  contract-rule, session, price-limit, liquidity, listing, policy, supply,
  inventory, venue, or data-source changes.

Turn these lenses into obligations only when the answer could change the
factor's permitted use, construction, product scope, or next TrialPlan. Define
the market-state or event question with observable, point-in-time inputs and
source references. An event noticed after outcome inspection is exploratory:
it may open a new obligation, but cannot retroactively redefine a frozen test
or rescue a failed Claim.

When a decision-blocking performance break, cross-instrument difference,
trading/liquidity anomaly, or preregistered institutional event makes event
context material, load
[market-context-event-search.md](market-context-event-search.md). Do not load
it or search the web for ordinary stable windows.

Do not generate the Cartesian product of every interval, regime, event, and
instrument. Prefer the smallest representative coverage that distinguishes the
mechanism, an important alternative explanation, or a declared transfer
boundary. Record uncovered regions as bounded limitations or later
obligations.

Create `performance_transportability` as a coverage obligation when the
Decision Contract depends on transfer across time, market state, or products.
Store the coverage intent and selection policy, not every
interval-by-instrument cell; let the TrialPlan expand only feasible,
decision-relevant contrasts. Create `market_context_heterogeneity` only after a
predeclared event or deterministic diagnostic exposes a material break,
instrument difference, or execution/liquidity anomaly. It is non-blocking
unless the unresolved context changes the product scope, execution assumptions,
sample design, permitted use, or promotion decision.

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
