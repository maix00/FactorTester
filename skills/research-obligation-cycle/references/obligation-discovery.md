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

## Preserve discovery provenance and category

A material question may originate from self-discovery, a grill, or an external audit.
Treat all three as valid prompts for obligation discovery. Preserve the
stable prompt or audit reference in the proposal, but do not treat the source
of the question as evidence that its answer is true.

Before choosing `obligation_kind`, match an existing obligation category when
its semantics genuinely fit the new question. Do not force a question into a
nearby category merely to avoid taxonomy work. If no existing category fits,
record it as explicitly unclassified with
`obligation_kind: unclassified_material_question`; keep the epistemic question,
scope, materiality, and discharge criterion fully specific so a later
classification does not change the research meaning.

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

Every new obligation body must include `title_zh`: a concise, one-line Chinese
display title of at most 32 characters. It names the unknown rather than
restating the full question. Keep the complete, falsifiable wording in
`epistemic_question`; do not put the stable `obligation_id`, punctuation-only
abbreviations, or the full question into `title_zh`.

For data availability, derive the obligation from the exact product, field,
frequency, history, visibility-time, latency, and permitted-use needs of the
decision. A preliminary availability profile is feasibility evidence, not a
universal discharge. Use the deterministic `data-availability.inspect`
capability to collect facts; do not use this Skill to probe files or providers.
Do not treat provider configuration, account access, or quote entitlement as
proof of usable coverage, latency, causal scheduling, or reproducibility.
Keep routine existence, permission, and exact predeclared coverage checks as
deterministic constraints or Capability Gaps. Create an obligation only when
the remaining data question could change the bounded research decision,
representativeness, transfer boundary, TrialPlan, or permitted use.
When the obligation bears on a deterministic data gate, attach stable machine
`requirement_refs` rather than encoding gate meaning in `obligation_kind`:
use `data-availability.scope` for usable-scope debt. Visibility-time,
membership, revision and look-ahead questions stay as explicitly scoped
research obligations; no source-wide boolean stands in for them.
`obligation_kind` remains open research vocabulary; the deterministic runner
must never infer authorization from its wording.

Use a two-stage gate. The initial `data_contract` checks product, source,
frequency, coverage, and provenance feasibility. After factor semantics and a
candidate TrialPlan exist, inspect the union of expression `ColumnRef` leaves
and execution fields before any diagnostic job starts. The deterministic CLI
first reads the shared catalog without inspecting source files:

```text
factortester product-library capabilities --json
```

If the exact scope has no frozen snapshot, capture the query as a Terminal
source. Do not copy the output into Markdown and cite the Markdown file as the
primary Evidence:

```text
factortester research evidence source capture-terminal --profile-id <profile> -- \
  factortester product-library availability \
    --product <product> --source <source> --frequency <frequency> \
    --field <logical-field> --field-catalog --historical-fields --json
```

Repeat `--product`, `--source`, and `--field` as needed. Select an exact stdout
fragment, create Evidence, and bind the returned frozen profile reference.
Read the full catalog only for this gate or through an artifact reference. Do
not place it in the routine Agent packet. Direct and correctly derived fields
may satisfy the deterministic field gate. `fallback_unadjusted` and `missing`
must create or reopen a scoped data obligation. Historical fee, margin,
multiplier, limit, session, or other accounting fields required by the
TrialPlan must be explicitly checked; a catalog query is not proof that every
day in the trial has a valid point-in-time value.

The lenses above are prompts, not a universal checklist. Create factor-specific
obligations when first principles require them, and omit irrelevant lenses.

## Inspect factor expression semantics

At `factor_semantics`, inspect the exact expression revision authorized for the
current Profile before creating empirical obligations. Read an authorized local
worktree source directly. When local source is unavailable but source access is
authorized, use `factortester factor-library describe <factor-ref> --source-code
--json`; otherwise use the same command without `--source-code` and retain the
visibility limitation. Do not infer a private expression from execution access.

Review the original expression for economic mechanism, units, price basis,
direction, timing, numerator/denominator construction, and factor-specific
errors. The describe response's `column_refs` contains only fixed `ColumnRef`
leaves; compare it with `factor.params` to ask whether a fixed input has an
economically coherent parameterized alternative. Do not create an obligation
for every fixed column. Create one only when the alternative is material,
falsifiable, and could change construction, TrialPlan, scope, or permitted use.

Before leaving `factor_semantics`, produce a compact Chinese semantics report
fragment. Include the exact authorized expression as LaTeX, explain each
material term and its economic and timing meaning, and state the semantic gap
that motivated any parameterization, revision, or derived family. For every
new expression, include its LaTeX, the structural change, expected mechanism,
and the parts that remain hypotheses rather than evidence. Link each material
change to the new or changed comparison obligation that can test whether the
observed effect matches the expectation. Prefer short lists and a comparison
table over long prose. This fragment is a narrative projection, not an
`EvidenceEnvelope`; retain source, expression-tree, and hash details behind
references. If exact LaTeX is unavailable, record a visibility gap instead of
reconstructing the formula from a name or result.

Code may be implemented before its mechanism or effectiveness is established.
Treat that implementation only as a versioned candidate artifact. A derived
interaction that is not a strict parameter-point generalization remains a
separate comparator: keep the parent as the research focus unless an accepted
decision transfers focus, and open a paired incremental-comparison obligation
under matched sample, timing, cost, and trial-ledger semantics.

When a derived family strictly generalizes its parent, create a migration
obligation that tests structural and numerical equivalence at the parent
parameter point under identical data, timing, cost, and product scope. Preserve
old job evidence, sample exposure, trial-ledger history, and multiplicity. Old
evidence may extend to the exact special-case scope only after accepted
equivalence evidence; it never validates the rest of the new parameter space.

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
