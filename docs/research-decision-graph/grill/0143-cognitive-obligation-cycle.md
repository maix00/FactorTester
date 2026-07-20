# Grill 143 — Cognitive Debt and the Research Obligation Cycle

Status: accepted through Grill 143.6.

This is the detailed document-grounded audit record. The compact canonical
decision is indexed in `research-decision-graph-grill-log.md`; domain language
is normalized in `CONTEXT.md`; implementation sequencing lives in the separate
Research Obligation Cycle work package. This detailed record is not runtime
Agent context.

## Sources and evidence boundary

The immediate prompt is the third WeChat article:

- [当 Agent 接管量化，如何破解投研的认知债务？](https://mp.weixin.qq.com/s/jYy8vzYMUy-oFUmsn-q3dw)

Its underlying general paper is:

- Shuchen Meng, [Cognitive Debt: AI as Intellectual Leverage and the Dynamics
  of Systemic Fragility](https://arxiv.org/abs/2606.15078), preliminary,
  June 2026.

The paper develops a theory of cognitive debt. The paper itself treats the
empirical magnitude as an open problem. The detailed quantitative-research
application in the WeChat article is therefore the article author's extension,
not an empirical result established by Meng.

Related research considered during this grill includes:

- [FactorMAD](https://doi.org/10.1145/3768292.3770377), as a design reference
  for bounded proposer/critic candidate generation, not as a replacement for
  statistical validation.
- [Problems with Shapley-value-based explanations as feature
  importance measures](https://proceedings.mlr.press/v119/kumar20e.html), for
  the distinction between attribution and causal understanding.
- [Quantitative Strategies for Achieving Alpha](https://www.nber.org/papers/w14465),
  for liquidity and crowding considerations.

The following FactorMAD details remain unavailable from open primary sources:
exact data splits, prompts, model versions, debate stopping rules, holdout
information isolation, multiple-testing controls, and official reproducible
code. FactorMAD must therefore remain a design reference rather than an
approved implementation or validation capability.

## What the third article is actually warning about

Cognitive debt is not merely missing documentation. It is the accumulation of
unverified reasoning obligations when an Agent can quickly produce factors,
code, backtests, and plausible explanations while the research process loses
track of:

- assumptions on which the conclusion depends;
- rejected paths and why they were rejected;
- parameter and feature sensitivity;
- competing explanations;
- evidence that would falsify the proposed mechanism;
- market states or data conditions in which the conclusion should decay;
- unexplained residual behavior.

An execution trace is not causal understanding. A long natural-language
explanation is also not evidence that the Agent understands the mechanism.

The useful methodological elements are:

1. Preserve decision genes, including sensitivity, feature contribution,
   rejected paths, competing explanations, and validity boundaries.
2. Use an independent simplified reconstruction or red-team pass when semantic
   uncertainty is material.
3. Prefer falsifiable failure and decay conditions over a demand for complete
   understanding.
4. Examine data geometry, cross-regime behavior, exposures, liquidity,
   capacity, and crowding only where the data and research stage make those
   questions identifiable.

The article's specific diagnostics must not become rules without statistical
qualification:

- covariance trace measures total variance, not conditioning or geometric
  deterioration;
- high-dimensional covariance diagnostics need shrinkage or other robust
  estimation and uncertainty;
- exposure similarity needs a baseline distribution, uncertainty, and
  preregistered state definitions;
- SHAP-style attribution is not causal explanation;
- crowding and market-impact evidence usually belongs to production or
  execution monitoring when ordinary factor research lacks real execution
  observations;
- tuning monitoring thresholds after seeing results creates additional trials
  and selection risk.

## Rejected simplification

The initial idea to add a generic “first-principles obligation” to every graph
edge is withdrawn.

That design would encourage boilerplate explanations, increase token usage,
make deterministic transitions depend on prose, and still fail to preserve
testable assumptions or rejected paths. It would turn first-principles
reasoning into a checklist.

## No second graph

The current recommendation is not to create a cognitive-debt graph or a
first-principles graph beside the Factor Research Graph.

A second graph would introduce duplicated state, versioning, replay,
migration, context loading, and evidence ownership. It would also encourage the
same evidence to be persisted twice. The existing Active Graph should continue
to govern the research lifecycle while existing research artifacts carry the
appropriate semantics.

## Proposed ownership boundary

### Active Graph

The Active Graph governs:

- the current research stage;
- available next stages;
- deterministic guards and required evidence;
- return, revision, pause, capability-gap, and escalation paths;
- the risk conditions that require a reviewer or grill-with-docs.

It does not store the complete reasoning history and does not prove that an
economic mechanism is true.

### TrialPlan

The TrialPlan freezes the testable design before material result inspection:

- hypothesis and competing explanations;
- primary and auxiliary tests;
- sample, frequency, product, timing, and information boundaries;
- baselines and comparison identities;
- perturbations, ablations, and market-state slices;
- rejection, revision, continuation, and stopping conditions;
- rules for upgrading a conclusion versus creating a new exploratory trial.

Batch 4 must not implement this pending semantic design. It may persist only an
opaque `current_trial_plan_hash` projection on the branch.

### Evidence Envelope

The Evidence Envelope records what verifiably happened:

- RunSpec, factor-family version, expression hash, data snapshot, and backend
  identity;
- command outcome and bounded stdout/stderr references;
- metrics and artifact references;
- trial role, comparison identity, and number of tested hypotheses;
- failure paths, missingness, criterion evaluation, and stopping-condition
  outcomes;
- the resulting decision and its evidence references.

It records facts rather than research understanding.

### Provisional Memory

Local Provisional Memory preserves unresolved or not-yet-generalized research
understanding:

- current and competing mechanism explanations;
- counterexamples;
- sensitivity and abandoned paths;
- market-state boundaries;
- unexplained residuals;
- constraints for the next iteration;
- explicitly marked cognitive debt.

It remains locally auditable and retrievable. It does not become a server graph
rule merely because one or several Agents reused it.

Promotion into a Graph edge, guard, or capability contract requires applicable
statistical or industry support, or repeated independent evidence with
counterexamples and validity boundaries, followed by server-Agent
grill-with-docs audit.

## Proposed staged reasoning obligations

### Candidate exploration

An Agent may create a factor from zero, revise an existing factor, search for
main or auxiliary factors, construct a conditional single factor, or use a
bounded FactorMAD-style proposer/critic process.

Unverified mechanisms are permitted at this stage if:

- every generated, modified, retained, and discarded candidate is included in
  the Trial Ledger;
- unverified assumptions are explicitly marked;
- exploratory output is not reported as a robust conclusion.

Demanding complete understanding before exploration would suppress useful
novelty.

### Hypothesis preregistration

The Agent must make the hypothesis testable by stating:

- the proposed mechanism;
- reasonable competing explanations;
- at least one initial falsifier;
- timing, data, accounting, or selection assumptions most likely to invalidate
  the result.

The mechanism need not already be proven.

### Validation design

The testable portion is frozen in the TrialPlan:

- perturbations and ablations;
- controls and baselines;
- market-state slices;
- stopping conditions;
- conclusion-upgrade rules.

Tests added after material result inspection must be recorded as new trials or
explicit exploratory analysis rather than silently appended.

### Result audit

An independent reviewer is invoked only when semantic or statistical
uncertainty is material. The audit asks whether:

- a simpler mechanism explains the result;
- timing leakage or information-boundary violations exist;
- existing risk exposures dominate the apparent factor;
- one parameter, product, or market state drives the result;
- an auxiliary factor supplies conditional information or accidentally changes
  the object into a multi-factor portfolio;
- rejected paths were selectively hidden;
- the conclusion is no stronger than the evidence permits.

Routine deterministic transitions require no reviewer.

### Research decision

Cognitive debt need not be reduced to zero:

- non-material unknowns may remain in Provisional Memory;
- bounded unknowns require a weaker or narrower conclusion;
- material unresolved obligations that could reverse direction, validity,
  timing, scope, or statistical interpretation block a strong conclusion.

The Agent may instead downgrade the conclusion, narrow its scope, revise the
hypothesis, create a new candidate, or preserve the unknown for later evidence.

## FactorMAD placement

FactorMAD is proposed only as a bounded local pattern:

```text
hypothesis
  -> proposer creates executable candidate
  -> independent critic examines semantics, timing, complexity, and counterexamples
  -> deterministic compile/debug
  -> freeze candidate
  -> ordinary TrialPlan and validation path
```

The proposer must not see final holdout outcomes. The critic must not use
holdout ranking to guide expression changes. Debate rounds, candidate count,
and token usage must be bounded in advance. Multi-Agent agreement is not
independent statistical evidence, and debate cannot replace out-of-sample,
cost, risk, robustness, or multiple-testing controls.

## Minimal implementation implication if accepted

Do not add:

- another graph;
- a cognitive-debt table;
- a decision-gene table;
- long prompts on every edge;
- a reviewer at every node;
- a global cognitive-debt score;
- another persistent Agent.

Use the existing owners:

```text
Hypothesis Branch
  -> current TrialPlan hash

Research Run / Job
  -> TrialPlan hash, trial role, comparison ID, RunSpec hash

Graph Trace
  -> bounded Evidence Envelope

Local workspace
  -> hash-addressed Provisional Memory

Active Graph
  -> only audited lifecycle states, edges, guards, and capability requirements
```

Deterministic code continues to own routine transitions. Reviewers and
grill-with-docs remain limited to semantic conflict, non-standard statistics,
backend changes, first Skill execution, and graph or governance changes.

## 143.1 response and reopening

The user accepted the direction but correctly rejected it as underspecified:

- Who manages and stores cognitive debt?
- How is it modelled?
- Where does it enter the Graph?
- Does debt identified before a backtest still exist after the backtest?
- Since backtests rarely create strong conclusions, should the system model
  changes in debt rather than conclusions?
- Can one test simultaneously falsify an old claim and create new questions?
- Should changes in debt become Graph edges, and what evidence permits a debt
  increase or decrease?

Decision 143.1 is therefore not final. “Direction accepted” does not yet mean
that an implementation contract has been accepted.

## Correction after rereading the article and primary paper

Meng's formal model defines cognitive debt as the stock of AI-assisted outputs
that an agent cannot independently reproduce, verify, or correct. Deliberate
practice repays debt by rebuilding that unaided verification capacity. This is
not identical to uncertainty about whether a factor works.

The quantitative article makes a related but narrower claim: backtest failure
is usually easy to observe after the fact, while live deterioration is
ambiguous. Its proposed target is not proof that a strategy is correct but a
statistically observable high-probability failure or decay boundary. It
therefore supports persistent monitoring and repeated diagnosis rather than a
one-time “test passed, debt cleared” transition.

This requires two corrections:

1. Cognitive debt must not be used as a synonym for hypothesis uncertainty,
   weak statistical evidence, or unexplained return.
2. A successful test does not repay debt unless it services a specific
   reasoning obligation under criteria declared for that obligation.

For example:

- A deterministic point-in-time and replay check may discharge a timing
  obligation.
- A backtest can add performance evidence but does not by itself discharge a
  causal-mechanism obligation.
- A regime-sliced test may narrow the validity boundary while leaving the
  mechanism open.
- One good backtest cannot discharge selection or multiplicity debt created by
  many hidden candidates.
- Historical data without real executions cannot discharge live crowding and
  market-impact obligations.
- A turnover anomaly may create a new cost-sensitivity obligation even while
  the original directional hypothesis survives.

## Revised model: two orthogonal research axes

Do not replace factor evidence status with a cognitive-debt score. Preserve two
orthogonal axes:

```text
Empirical evidence axis
  untested / evaluated / supported_in_scope / contradicted /
  inconclusive / superseded_in_scope

Reasoning-obligation axis
  a set of open, bounded, discharged, reopened, split, or superseded
  epistemic obligations
```

The first axis answers what the observed evidence currently supports in a
declared scope. The second answers what reasoning the Agent still cannot
independently reproduce, verify, correct, or delimit.

A factor can have:

- promising evidence and high cognitive debt;
- weak evidence and low cognitive debt;
- contradicted evidence with a successfully discharged obligation, because a
  planned test cleanly falsified the claim;
- supported-in-scope evidence with bounded unresolved production obligations.

“Strong research conclusion” should therefore not become another persistence
object. It is a derived authorization level from both axes. Existing
scope-bound Factor Evidence Status remains necessary; it must be revisable when
new evidence reopens an obligation.

## Revised model: Epistemic Obligation, not scalar debt

The atomic object should be an **Epistemic Obligation**. “Cognitive debt” is the
set of currently unserviced material obligations, not one numeric balance.

A compact obligation needs:

- stable local identity and subject reference;
- kind: mechanism, timing, data provenance, accounting, selection/multiplicity,
  parameter sensitivity, regime boundary, implementation parity, attribution,
  capacity/crowding, or residual uncertainty;
- the claim or question that cannot yet be independently reproduced, verified,
  corrected, or bounded;
- origin: Agent-generated decision, imported factor, test observation,
  anomaly, contradictory evidence, or environment change;
- scope and materiality to a particular research decision;
- declared falsifier or resolution criteria when currently knowable;
- current state;
- bounded evidence references;
- parent/child references for split or derived questions;
- the boundary or monitoring trigger when retained as an explicit unknown.

Avoid a single “debt increased/decreased” number. Obligations are not
commensurable. Closing one high-materiality timing obligation and opening two
minor monitoring questions cannot be truthfully represented as `-1` or `+1`.
UI or Agent context may derive bounded counts by kind/materiality, but those
counts are not a scientific score or a transition guard.

## Proposed obligation state changes

Use a small set of semantic operations:

- `open`: a new unverified reasoning obligation is identified;
- `service`: new matched evidence is added but the declared criterion is not
  yet satisfied;
- `discharge`: matched evidence satisfies the resolution criterion, or the
  associated claim is cleanly falsified;
- `bound`: the unknown remains, but its scope, materiality, and monitoring or
  re-entry condition are explicit;
- `split`: one broad obligation is replaced by more precise child
  obligations;
- `reopen`: new evidence invalidates a prior discharge or boundary;
- `supersede`: a factor/hypothesis version or research scope makes the old
  obligation inapplicable without rewriting history.

An obligation itself is not “falsified”. A claim is falsified; the obligation
to test that claim may then be discharged. This distinction prevents a failed
factor test from being mislabeled as unresolved debt.

## Proposed owner and storage boundary

### Management

- The Research Agent manages obligations for its Hypothesis Branch.
- Deterministic code validates identity, allowed state transitions, evidence
  references, and TrialPlan correspondence.
- One independent Statistical or Semantic Reviewer appears only when a material
  state change depends on non-standard or ambiguous interpretation.
- The Server Maintenance Agent owns proposals to generalize recurring
  obligations into Graph rules or new backend capabilities.
- The human auditor participates only in the document-grounded grill for those
  high-risk changes, not in ordinary obligation bookkeeping.

### Storage

Full obligations remain in local Provisional Memory because they may include
private factor reasoning, rejected formulas, and local source context. Use a
hash-addressed, append-oriented local ledger plus a derived current index;
avoid a new server database table and avoid rewriting the full ledger after
every test.

The server receives only:

- opaque obligation/evidence refs and hashes;
- a bounded branch-local summary needed for the current transition;
- compact obligation deltas inside the existing Evidence Envelope/graph trace
  when a material transition occurs.

The TrialPlan binds selected obligations to planned tests. Job and test
evidence remains in its canonical owner. This preserves replay without copying
private reasoning or turning SQLite into a research-log hot path.

The exact local file schema and path remain undecided. They must be designed
only after the semantic object is accepted.

## How obligations enter the existing Graph

Do not create one Graph edge per debt increase or decrease. The Graph edge
represents a research-method transition; the obligation delta is evidence
produced by that transition. One transition may simultaneously discharge,
bound, split, and open different obligations.

Proposed placement:

| Existing stage | Obligation effect |
|---|---|
| candidate discovery | open mechanism, data, timing, selection, and construction obligations; register every executed candidate |
| factor semantics | discharge or open expression, timing, NaN, accounting, and information-boundary obligations |
| hypothesis preregistration | choose material obligations, competing claims, falsifiers, and initial boundaries |
| validation design | bind obligations to planned deterministic checks, perturbations, ablations, OOS tests, and stopping rules |
| diagnostics/backtest/robustness | service, discharge, bound, split, reopen, or create obligations from actual evidence |
| factor improvement/conditional construction | create a new factor version and new or inherited obligations rather than mutating old evidence |
| result audit | independently reconstruct material reasoning and challenge obligation state changes |
| research decision | derive scope-bound evidence status and permitted use from evidence plus remaining material obligations |
| production monitoring outside the research graph | reopen regime, decay, capacity, crowding, and execution obligations when live evidence crosses preregistered triggers |

Only a repeated and generalizable pattern may propose a new Graph edge or
guard. Ordinary obligation changes remain branch evidence, not topology.

## Evidence required for state changes

Evidence must match the obligation's declared resolution criterion:

- deterministic verification: hashes, point-in-time lineage, expression
  semantics, batch/incremental parity, compile/runtime checks;
- planned empirical falsification: OOS, sensitivity, ablation, regime slices,
  cost/accounting tests, robustness and uncertainty procedures;
- independent reconstruction: a reviewer reproduces a simplified argument or
  identifies a counterexample without receiving a desired conclusion;
- production evidence: actual execution, drift, liquidity, capacity, and
  crowding observations when those questions cannot be identified from a
  historical factor backtest.

Positive performance alone is insufficient. A failed planned test can
discharge an obligation more strongly than a successful backtest when it
cleanly falsifies the claim. A `bound` transition requires an explicit scope,
materiality judgment, and monitoring/re-entry trigger rather than a prose
disclaimer.

## Decision 143.2 — accepted

Accepted by the human auditor.

> Should the system preserve two orthogonal research axes—scope-bound empirical
> evidence status and a non-scalar set of Epistemic Obligations—so that tests
> update matched obligations through `open/service/discharge/bound/split/reopen/
> supersede`, while Graph edges continue to represent research-method
> transitions rather than numeric cognitive-debt increases or decreases?

The human auditor agreed, then challenged three unresolved parts:

1. A fixed list of obligations cannot truthfully represent a factor that is
   initially unknown, and future research may discover better initialization
   obligations.
2. Evidence Envelope, empirical evidence status, and obligation delta need a
   precise separation.
3. “Research complete” for one family with many parameter configurations, or
   for multiple families, cannot mean that a hard-coded metric threshold was
   crossed. The authority and evidence needed to discharge an obligation must
   also be constrained so that an Agent cannot close it by assertion.

The earlier stage table also conflated workflow stages such as
`candidate_discovery` and `factor_semantics` with obligation categories. Those
stages are occasions that may generate or service obligations; they are not an
ontology of obligations.

## Revised separation of evidence objects

An Evidence Envelope is an immutable event record. It carries:

- subject, scope, factor-family/configuration and RunSpec identities;
- method and test-plan identity;
- canonical result and artifact references;
- uncertainty, attempted-hypothesis and stopping-rule information where
  applicable;
- limitations and counterevidence;
- the obligations the evidence was intended to address;
- a proposed obligation delta and a compact auditable decision basis.

It is not itself the empirical evidence status. The evidence status is a
derived, replayable projection for a particular claim and scope over accepted
Evidence Envelopes. The obligation ledger is another derived projection. One
Envelope may weaken one claim, discharge one verification obligation, service
one mechanism obligation, and open a new regime-boundary obligation.

## Dynamic initialization, not a fixed obligation inventory

Do not hard-code a universal list of instantiated obligations for every
factor. Use three sources:

1. **Small invariant generators** ask questions that any research claim must
   make answerable: identity/scope, causal information boundary, data
   provenance, semantic reproducibility, target definition, selection history,
   and declared use assumptions. If deterministic evidence already answers a
   question, no open obligation needs to remain.
2. **Predicate-triggered domain generators** inspect the actual subject:
   intraday, term-structure, cross-sectional, conditional construction,
   parameter search, imported/precomputed signal, cost-sensitive strategy, and
   other semantics. They instantiate only applicable obligations.
3. **First-principles gap analysis by the Research Agent** maps the actual
   claim to its proposed mechanism, minimal assumptions, observables,
   counterfactuals, failure conditions, transfer boundary, and unknowns. The
   Agent may open factor-specific obligations that no template anticipated.

Opening an obligation is conservative and does not require approval. It does
require a structured subject, question, origin, scope, materiality, and reason.
Resolution criteria may be unknown initially; that fact is explicit and makes
the obligation ineligible for discharge until criteria are specified.

Generators are versioned research-policy descriptions, not Graph nodes and not
Skill identities. Research can propose a new reusable generator. Promotion
requires recurrence or clear external methodology, a scope/applicability
predicate, counterexamples, replay against prior branches, token and database
cost evidence, and the existing Graph-governance grill. Existing branches pin
the generator version used at initialization. A newly approved material
generator produces an impact diff: unaffected work continues; affected
closures may be reopened without rewriting their historical decision.

## Hierarchical research scope and bounded completion

Use explicit scope levels:

```text
Research Campaign
  -> Factor Family Version
       -> parameter/configuration space
            -> executed candidate/configuration
                 -> claim
```

An obligation attaches at the lowest truthful scope and can be inherited:

- formula/timing/provenance may be family-level;
- parameter sensitivity and multiplicity may cover a configuration space;
- one execution result is candidate-level;
- cross-family selection and comparison are campaign-level.

Research never becomes universally “true” or epistemically complete. A
specific research cycle reaches **bounded closure** when:

- the versioned in-scope inventory is known;
- each in-scope family/configuration has a recorded disposition such as
  evaluated, eliminated, superseded, bounded/deferred, or explicitly
  out-of-scope;
- no unresolved obligation marked blocking for the requested decision remains;
- every retained unknown is bounded by scope, materiality, permitted use, and
  re-entry/monitoring condition;
- preregistered stopping rules or an explicit resource/utility stop are met;
- candidate-attempt and multiple-testing exposure is preserved;
- evidence and obligation state changes are replayable;
- the risk policy's required independent review is complete.

Metric thresholds can satisfy a predeclared criterion for one obligation, but
there is no framework-wide set of IC, Sharpe, or significance thresholds that
turns a family into “passed”. Closure is always relative to a declared decision
such as reject, continue research, retain as a bounded candidate, or permit a
specified use.

Unknown unknowns cannot be proven absent. Bounded closure therefore means:
given the declared scope, current methodology version, recorded attempts and
counterevidence, no known material unresolved obligation blocks this particular
decision. It is versioned and reopenable.

## Authority to change obligation state

An Agent may always propose or open an obligation. It cannot delete history or
discharge an obligation by unsupported assertion.

State-change authority is evidence-class dependent:

- deterministic obligations may be discharged automatically by trusted,
  reproducible verifier output bound to the relevant hashes;
- standardized empirical obligations may use preregistered machine-evaluable
  criteria;
- post-hoc evidence may service or bound an obligation, but normally cannot
  satisfy a criterion invented after seeing the result;
- non-standard mechanism, semantic, external-validity, or conflicting-evidence
  decisions require one relevant independent reviewer according to risk;
- promotion/production decisions, methodology changes, reviewer conflict, and
  Graph changes enter the existing document-grounded human grill.

The durable audit record must not request hidden chain-of-thought. It records a
compact decision basis:

- evidence facts used;
- rule or first-principles question applied;
- inference type;
- material counterevidence;
- resulting scope and limitation;
- state change proposed;
- reviewer/auditor disposition when required.

Deterministic code validates identity, chronology, criterion version, evidence
references, allowed state transition, and review requirement. The Agent judges
semantic relevance only where code cannot. Rejected state-change proposals
remain in the append-only history.

## Pending question 143.3

Recommended answer: accept the model, while leaving the exact generator
catalog and closure schema for the next grill and industry-methodology audit.

> Should initialization use versioned obligation generators plus
> factor-specific first-principles gap analysis, rather than a fixed obligation
> list; should completion mean scope- and decision-relative bounded closure over
> a hierarchical campaign/family/configuration/claim inventory; and should an
> Agent be allowed to open obligations freely but only propose discharge through
> evidence-bound, replayable state changes whose reviewer/human requirement is
> determined by evidence class and risk?

## Challenge to 143.3 — the paper's object and the research object's state differ

The human auditor agreed with the direction but correctly challenged the model:

- initial obligations cannot be a hard-coded checklist, and research may
  discover new kinds of initial questions later;
- workflow stages such as candidate discovery and factor semantics are not
  obligation categories;
- an Evidence Envelope cannot also be called the factor's evidence state;
- a family with many configurations, or a campaign with many families, needs a
  truthful completion rule that is neither “all metrics pass” nor “all unknowns
  disappeared”;
- an Agent must not be able to discharge a material obligation merely by
  writing a plausible first-principles explanation.

Re-reading Meng (2026) requires a more fundamental correction. In that paper,
**cognitive debt belongs to an agent**: it is the gap between task demands and
the agent's unaided capacity to reproduce, verify, or correct AI-assisted work.
The paper is a preliminary economic model of AI substitution, cognitive
capital, leverage, stress exposure, and correlated fragility. It is not an
operational protocol for representing uncertainty about a factor.

The Active Graph therefore must not treat a factor's unresolved empirical
questions as the paper's scalar cognitive-debt state. The paper instead
motivates controls on the research process: preserve unaided or independent
reconstruction capacity, expose AI-produced work to stress/counterexample
tests, avoid patching one unverified AI conclusion with another, and avoid
mistaking a tranquil sequence of successful backtests for declining true risk.

## Revised canonical objects

Use separate objects:

1. **Evidence Envelope** — immutable record of an observation or verification
   attempt. It contains facts, method identity, scope, artifacts, limitations,
   and proposed effects. A proposal inside the Envelope is not authoritative.
2. **Research Claim** — a scoped, falsifiable assertion about semantics,
   mechanism, empirical behaviour, transfer, or permitted use.
3. **Verification Obligation** — a currently unresolved question whose answer
   is material to a declared decision about a Claim.
4. **Obligation Event** — append-only proposal or accepted adjudication that
   opens, services, bounds, splits, supersedes, reopens, or discharges an
   obligation.
5. **Research Evidence Projection** — a replayable, decision-relative view
   derived from accepted Evidence Envelopes, Obligation Events, claim scope,
   methodology version, and counterevidence.
6. **Cognitive-debt control** — a separate process assurance concerning
   whether AI-generated reasoning can be independently reconstructed,
   challenged, and corrected. It is not a Factor state and must not be copied
   into every Graph edge.

This is intentionally not a second graph. Claims, evidence references,
obligations, and adjudications are branch-local research state. Active Graph
edges remain approved research-method transitions.

## Initialization is a discovery procedure, not an inventory

“Knowing nothing about a factor” is not represented by pre-opening a universal
debt list. The system normally still knows the research mandate, Factor Family
version, expression or candidate source, intended product/frequency scope, and
requested decision. Initialization should run a versioned **claim-decomposition
procedure**:

```text
declared decision and intended use
  -> claims required for that decision
  -> assumptions each claim depends on
  -> observable implications and counterfactuals
  -> material failure modes and alternative explanations
  -> verification obligations that discriminate among them
```

The procedure is versioned, but the resulting obligations are not hard-coded.
Reusable prompts, statistical standards, product semantics, and deterministic
preconditions may assist discovery. They do not define a closed ontology.

Some properties should be guards rather than open obligations. For example, an
unidentified Factor Family version, an invalid RunSpec hash, or an impossible
causal time alignment prevents a valid test from starting. Turning every
missing machine field into epistemic debt would inflate both state and token
cost.

An Agent may create a new factor-specific obligation whenever it identifies a
material assumption, alternative explanation, failure condition, or transfer
boundary. It may also propose a reusable discovery rule after recurrence or
methodological support. A new rule is replayed against prior scopes and enters
Graph governance only if it changes approved method transitions or guards.

## Completion is coverage of a decision contract, not universal truth

The unit of completion is a versioned **Research Decision Contract**, not an
individual good-looking metric and not a Factor in the abstract. The Contract
pins:

- the requested decision and permitted-use boundary;
- the Campaign and Factor Family versions in scope;
- how a parameter/configuration space is enumerated or sampled;
- selection history and attempted-candidate coverage;
- stopping/resource rules;
- the methodology and obligation-discovery procedure versions;
- which obligation classes are decision-blocking;
- the independent review required by risk.

For a large parameter space, research cannot truthfully require every possible
configuration to pass. It must preserve the search design and coverage:
enumerated configurations, sampled regions, adaptive choices, eliminated
regions, retained candidates, and multiplicity exposure. For multiple families,
the Campaign additionally owns cross-family selection and comparison claims.

A Contract reaches bounded closure when every in-scope item has a disposition,
the planned search/coverage and stopping rules are satisfied, no known
decision-blocking obligation remains unresolved, and every retained unknown is
explicitly bounded or transferred to monitoring with a re-entry trigger.
Closure authorizes only the named decision and use boundary. It does not assert
that the Factor is true, universally valid, or free of unknown unknowns.

Metrics and thresholds are evidence for particular Claims. They may satisfy a
preregistered criterion, but no global IC/Sharpe/p-value table defines research
completion.

## Agent judgment must create adjudication proposals, not facts

An Agent can always open an obligation and propose a state change. The
authoritative projection accepts a material state change only through a typed
adjudication:

- exact Claim, obligation, scope, and evidence references;
- criterion or external methodological rule used;
- compact warrant connecting evidence to the proposed change;
- alternatives and material counterevidence considered;
- whether the criterion was declared before seeing the result;
- permitted-use boundary and re-entry condition;
- required verifier/reviewer disposition.

This records an auditable argument without requesting hidden chain-of-thought.
Deterministic code checks identity, chronology, criterion version, evidence
existence, allowed transition, and reviewer requirement. A trusted verifier may
accept deterministic obligations. A preregistered machine-evaluable rule may
accept standardized empirical ones. A semantic, post-hoc, conflicting, or
high-impact discharge requires independent review; Graph/methodology or
production-policy changes retain the human grill.

An unsupported Agent statement remains a rejected or pending proposal and
cannot alter the accepted Research Evidence Projection. New evidence may reopen
an earlier bounded or discharged obligation. Thus tests can reduce one
uncertainty while exposing another without pretending that a backtest created
a strong final conclusion.

## Pending question 143.4

Recommended answer: accept the terminology and ownership correction before
deciding the exact initialization protocol.

> Should “cognitive debt” be reserved for the Agent/process risk described by
> Meng, while factor research uses scoped Research Claims and Verification
> Obligations; should Evidence Envelopes and Obligation Events remain immutable
> inputs to a separate replayable Research Evidence Projection, so that an
> Agent may propose but cannot unilaterally make a material discharge
> authoritative?

## 143.4 response and refinement

The human auditor accepted the direction but challenged the operational model:

- what can be initialized when nothing substantive is yet known about a
  Factor;
- whether initialization can evolve without hard-coding an obligation
  inventory;
- whether workflow stages had accidentally been presented as obligation
  categories;
- how an Evidence Envelope differs from factor evidence state;
- what completion means for one Factor Family with many configurations, or a
  Campaign containing several families;
- who may decide that an obligation has been sufficiently serviced or
  discharged;
- how to prevent an Agent from manufacturing closure with an unsupported
  explanation.

The accepted terminology correction does not yet accept the exact
initialization, closure, or adjudication protocol.

## Recommended resolution: initialize a decision contract and discovery pass

There is no truthful “complete initial obligation set”. Even before Factor
evidence exists, however, the system normally knows:

- the requested research decision and intended use;
- the Campaign or workspace snapshot in scope;
- the Factor Family versions or the authorization to create candidates;
- the product, frequency, timing, and data boundaries currently declared;
- the search and resource boundary for the current cycle.

Initialization should persist those facts in a versioned **Research Decision
Contract**, then run an **Obligation Discovery Pass**. The pass decomposes the
requested decision into Claims, assumptions, competing explanations,
observable implications, counterfactuals, failure conditions, and transfer
boundaries. It produces the known Verification Obligations at that point in
time.

The pass is extensible and versioned; the resulting obligations are not
hard-coded. It may use:

- deterministic admissibility checks;
- applicable statistical and market methodology modules;
- product- and construction-specific predicates;
- a first-principles gap analysis by the Research Agent;
- obligations newly exposed by later evidence.

Only a few meta-rules are invariant: a material obligation must identify its
subject, scope, decision relevance, origin, and evidence needed to change its
accepted state. These are integrity rules for an auditable object, not a closed
catalog of scientific questions.

A newly discovered reusable method may be proposed as a new discovery module.
Approval versions the method for future work and produces an impact analysis
for open work. It does not rewrite what an earlier Agent knew or pretend that
an earlier closure used the new method. Material affected closures may be
reopened through a new event.

## Workflow stage is not obligation type

`candidate_discovery`, `factor_semantics`, `validation_design`, and
`result_audit` are Active Graph stages. They identify when discovery or
verification work occurs. They must not define a closed obligation ontology.

Obligations attach to Claims at the lowest truthful research scope. Labels such
as timing, provenance, multiplicity, sensitivity, mechanism, or transfer may
help retrieval and route an appropriate verifier, but remain extensible
descriptors. Authority depends primarily on the evidence and adjudication
class, not on a fixed domain label.

## Evidence Envelope is not evidence state

An **Evidence Envelope** is an immutable record of one observation,
verification attempt, or execution. It may contain a proposed effect on
Claims and obligations, but the proposal is not authoritative.

A **Research Evidence Projection** is the current replayable view derived from
accepted Evidence Envelopes and accepted Obligation Events under a pinned
methodology version. It answers what the evidence currently supports, for which
Claim and scope, with which unresolved limitations.

Therefore:

```text
Evidence Envelope = immutable input event
Obligation Event   = proposed or accepted state-change event
Evidence Projection = derived current research state
```

No Envelope is overwritten when a later test changes the interpretation.

## Completion has three different meanings

Avoid one overloaded `completed` flag:

1. **Execution complete** means all jobs selected by the current TrialPlan are
   terminal and their Evidence Envelopes exist.
2. **Research-cycle closure** means the Research Decision Contract's coverage
   and stopping rules are satisfied, every in-scope item has a disposition,
   and every known decision-blocking obligation has an accepted disposition.
3. **Decision authorization** means the resulting Evidence Projection supports
   one named use within a declared boundary.

A cycle can be complete with a negative or inconclusive result. Good IC,
Sharpe, or significance metrics do not by themselves make it complete.
Conversely, not every configuration must “pass”.

For a Factor Family, the Contract pins the Family version and describes how its
configuration space is enumerated, sampled, adaptively searched, eliminated,
or deferred. It preserves every attempted candidate and the resulting
multiplicity exposure. For several families, a Campaign-level Contract also
owns cross-family search, comparison, and selection Claims. The workspace
scope is a versioned inventory snapshot; later additions create a new Contract
revision rather than silently expanding a nearly closed cycle.

Research-cycle closure is bounded and decision-relative:

- planned coverage and stopping/resource rules are met;
- every in-scope family, region, or candidate has a disposition;
- no known obligation classified as blocking for this particular decision
  remains open or merely serviced;
- unresolved non-blocking obligations are explicitly bounded by scope,
  materiality, permitted use, and a re-entry or monitoring trigger;
- selection history, counterevidence, and accepted adjudications are
  replayable;
- the required independent review is complete.

This does not prove that unknown unknowns are absent. It says only that, under
the pinned methodology and evidence available at closure, no known material
unresolved obligation blocks the named decision.

## Agent authority is proposal authority

An Agent may freely:

- open a new obligation;
- add matched evidence;
- propose service, bound, split, reopen, supersede, or discharge;
- explain which first-principles rule connects the evidence to the proposal.

It may not make a material discharge authoritative merely by writing that the
evidence is sufficient. Accepted state changes use a typed adjudication:

- deterministic reproducibility and identity checks may be accepted by a
  trusted deterministic verifier;
- standardized empirical criteria may be accepted mechanically only when the
  criterion and scope were fixed before material result inspection;
- a post-hoc criterion normally services or bounds an obligation and starts a
  new confirmatory trial rather than retroactively discharging it;
- material semantic, mechanism, transfer, conflicting-evidence, or
  non-standard statistical judgments require a relevant independent reviewer;
- Graph, methodology, backend, or production-policy changes retain the
  document-grounded human grill.

The audit record should not request hidden chain-of-thought. It records a
compact **Decision Warrant**:

- the evidence facts and references used;
- the declared criterion, external rule, or first-principles test applied;
- the inference type;
- alternatives and material counterevidence;
- whether the criterion was predeclared;
- the proposed state change, resulting scope, limitation, and re-entry trigger;
- the verifier or reviewer disposition.

Deterministic code checks identity, chronology, hashes, evidence existence,
criterion version, allowed transition, and required authority. Unsupported
Agent assertions remain pending or rejected events and do not change the
accepted projection. New evidence can later reopen a discharged or bounded
obligation.

## Canonical numbering correction

The human auditor identifies the already accepted two-axis decision as Grill
143.2. The intermediate pending labels in this scratch document were internal
continuation labels produced while reconstructing a swallowed conversation.
They do not override the human-audited sequence. The next unresolved decision
is therefore recorded as Grill 143.3.

## Grill 143.3 — dynamic obligation initialization

The human auditor agrees that test output should be an Evidence Envelope with
a proposed obligation change set, but asks:

- what can be initialized when nothing is yet known about a Factor;
- how initialization can evolve without hard-coding scientific obligations;
- whether the alleged factor evidence state was merely the Evidence Envelope;
- why workflow stages such as `candidate_discovery` and `factor_semantics` had
  been presented as if they were obligation categories.

### Recommended resolution

There is no truthful complete set of initial scientific obligations. Even a
new Factor is not literally context-free: the system knows the requested
research decision, the permitted use, the product and information boundary,
the Factor expression or candidate-creation authority, the configuration
search policy, and the workspace inventory snapshot. Initialize this boundary
in a versioned **Research Decision Contract**, not as a set of claims already
believed true.

Then run a versioned, extensible **Obligation Discovery Pass**. It is a
procedure rather than an inventory. It asks, for the named decision:

1. What Claims would have to be true?
2. What data, timing, accounting, construction, and selection assumptions do
   those Claims depend on?
3. What materially different explanations could produce the same observation?
4. What observable consequence would discriminate among those explanations?
5. What failure, counterfactual, regime, or scope boundary would change the
   permitted decision?
6. Which Verification Obligations follow from those answers?

These questions are discovery lenses, not hard-coded instantiated obligations.
Product, frequency, statistical, execution, or strategy modules may contribute
additional lenses only when applicable. The Research Agent may add a
factor-specific obligation that no module anticipated. A recurring or
methodologically supported lens can later be proposed as a new version of the
discovery procedure. Historical work remains pinned to its original procedure
version; a newly material lens reopens affected research by an explicit impact
event rather than silently rewriting history.

Only audit-integrity fields are invariant. An instantiated obligation must
identify its subject, Claim or first-principles question, scope, origin,
decision relevance, proposed materiality, evidence needed to change it, and
adjudication class. Its scientific `kind` remains extensible. Missing identity,
timing, chronology, or provenance is normally a deterministic Graph guard,
not an epistemic obligation.

`candidate_discovery`, `factor_semantics`, `validation_design`, and
`result_audit` are workflow stages. They are occasions at which obligations may
be opened, serviced, split, bounded, or reopened; they do not define an
obligation ontology.

Evidence Envelope and evidence state are also distinct:

```text
Evidence Envelope
  = immutable observation or verification attempt

Obligation Event
  = proposed or accepted adjudication

Research Evidence Projection
  = replayed current support and limitation by Claim and scope
```

An Evidence Envelope may carry a **proposed** obligation delta, but it is not
the accepted state and is not itself the Factor's evidence state. The latter
is a replayable projection over accepted Claims, obligation events, and
Evidence Envelopes. Completion and adjudication are dependent questions and
will be grilled separately after initialization is settled.

### Pending question 143.3

Recommended answer: accept the initialization boundary before selecting
concrete statistical discovery modules, persistence, completion rules, or
adjudication authority.

> Should the initial design initialize a versioned Research Decision Contract,
> then let a versioned but extensible Obligation Discovery Pass and
> factor-specific first-principles analysis instantiate applicable
> obligations—without hard-coding a universal obligation list—and treat later
> improvements to discovery as explicit versioned methodology changes that may
> reopen affected research but never silently rewrite historical state?

If accepted, Grill 143.4 will address bounded completion for one Factor Family
with many configurations, several Factor Families, and a workspace-wide
Campaign. Grill 143.5 will separately address Agent proposal authority,
evidence-class adjudication, and protection against unsupported discharge.

## Grill 143.3 continuation — graph placement and coupled adjudication

The human auditor accepts the dynamic-initialization direction in principle
but does not yet accept its placement or object model. The unresolved
questions are:

- whether obligation generation is part of Active Graph;
- whether the initial obligation set comes from current evidence or from the
  Research Plan/Research Decision Contract;
- whether plan-to-obligation discovery is a Graph edge, a Skill, or a
  graph-versioned method;
- whether Research Decision Contract duplicates Work Package, Hypothesis
  Branch, or TrialPlan;
- whether selected obligations must generate TrialPlans;
- whether obligation discharge and evidence-state change are one fact;
- whether an Evidence Envelope should propose both deltas;
- which graph stages may generate obligations without a computational Evidence
  Envelope;
- how obligation creation is encouraged without admitting vague, duplicate,
  mechanically decidable, or decision-irrelevant obligations;
- whether inability to produce a useful obligation or TrialPlan can establish
  research completion;
- how later methodology or graph changes reopen prior research.

### Current implementation reality

The current product-neutral Draft Graph represents `factor_semantics` and
`result_audit` as nodes. Edges are the guarded transitions into or out of those
nodes. The previously accepted `candidate_discovery` node from Grill 97 is not
yet present in the Draft Graph implementation. Batch 6 implemented the bounded
Graph/AgentFlow/TrialPlan infrastructure; it did not activate the pending
cognitive-obligation semantics or complete the accepted candidate-discovery
topology.

The current branch schema projects capability resolution and the current
TrialPlan hash, but it does not yet own an accepted Claim-evidence projection
or obligation projection. Therefore no current field should be retroactively
renamed as if this grill had already been implemented.

### Recommended Active Graph boundary

Obligation **discovery requirements** belong to Active Graph; concrete
obligations do not become Graph topology.

The Graph should version:

- the occasions that require a discovery checkpoint;
- the capability description needed to perform it;
- the minimum admissibility schema for its output;
- the guards that prevent closure when a required checkpoint is stale;
- the routes to capability gap, revision, audit, or closure.

The initial trigger set should be small:

1. after the authorized research boundary is frozen;
2. after a material Evidence/Adjudication update changes a Claim, assumption,
   scope, or competing explanation;
3. after factor semantics, data, product, strategy, methodology, or permitted
   use changes;
4. before bounded research-cycle closure.

Do not execute a full discovery pass on every edge. Deterministic code compares
the Contract, accepted projection, applicable methodology, and triggering
artifact hashes. An unchanged checkpoint is reused. Only a material hash or
an explicit unresolved first-principles trigger wakes the Agent.

Plan-to-obligation discovery is not itself an edge. An edge describes a
lifecycle transition. Discovery is a graph-governed transition effect or
checkpoint: the applicable edge cannot become ready until it references a
fresh discovery event. Initially, no extra generic `obligation_discovery` node
is required. A dedicated node should be added only if discovery later proves
to have an independently meaningful wait/retry/cancel lifecycle that cannot be
represented by staying at the current node or entering CapabilityGap.

### Capability and Skill boundary

The Graph should require a provider-neutral capability description such as
`research-obligation.discover`, not a concrete Skill name. Its implementation
may be an installed Skill, built-in Agent procedure, or future deterministic
module.

The server retains only the capability description, descriptor hash, and
methodology reference. The local Agent reuses or loads a matching Skill after
the existing approval gate and records the actual Skill identity/version in
the local audit ledger. Changing a Skill implementation does not automatically
change Graph topology. Changing the semantic discovery contract, triggers, or
admissibility rules requires a methodology or Graph version and an impact
review.

### Initial state is unassessed, not evidence-free

At initialization, the accepted empirical projection may be entirely
`unassessed`, but discovery input is not empty. It includes:

- the authorized decision and permitted use;
- the Work Package/workspace inventory snapshot;
- the Hypothesis Branch scope or candidate-creation authority;
- product, data, timing, strategy, and information boundaries;
- Factor Family/configuration identities when they already exist;
- search/coverage/resource/stopping boundaries;
- applicable methodology and product-profile versions.

The initial discovery pass derives Claims and obligations from that boundary.
It does not infer them from a blank evidence-state object. Later incremental
passes use both the pinned boundary and the accepted Claim/obligation
projection.

### Do not create a second planning owner

Use three views with different meanings:

```text
Work Package / Hypothesis Branch
  authorized research scope and current branch identity
  └── Research Decision Contract
      normalized, versioned decision boundary for this research cycle

TrialPlan
  immutable statistical plan for obtaining information about selected
  obligations and Claims

Agent Flow plan/checkpoint
  local operational sequencing and resources; not scientific evidence
```

`Research Decision Contract` should initially be a normalized, hash-addressed
contract view over the existing Work Package/Hypothesis Branch and trace, not a
new table, service, or persistence owner. “Research Plan” remains too
ambiguous: it may mean user scope, Agent scheduling, or statistical design.
Use `Research Decision Contract` only for the decision boundary and retain
`TrialPlan` for the statistical experiment.

One Decision Contract may produce many successive TrialPlans. A TrialPlan must
declare the unresolved obligation refs and Claims it intends to discriminate,
the expected information/state change, and its stopping/selection semantics.
Not every obligation produces a TrialPlan: identity/timing guards may be
deterministic; literature or semantic review may service others; an unknown
may be bounded because no identifiable test currently exists.

### Claim evidence and obligation state are coupled but not identical

They are two projections changed by one accepted adjudication:

```text
Claim evidence state
  unassessed / supported-in-scope / contradicted / mixed / inconclusive

Obligation state
  open / serviced / discharged / bounded / split / reopened / superseded
```

Examples:

- A negative confirmatory test may contradict a predictive Claim while
  discharging the obligation to test that Claim.
- A positive backtest may support a predictive Claim and discharge its
  preregistered prediction obligation while leaving mechanism, transfer, cost,
  or regime obligations open.
- A data-lineage failure may leave the economic Claim unassessed while opening
  or retaining a provenance obligation.

Therefore discharge cannot be inferred from “supported”, and support cannot be
inferred from discharge. They are one adjudication's two coordinated outputs,
not one state under two names.

### Evidence Envelope is not the universal event container

Do not force every obligation change into an Evidence Envelope. A discovery
checkpoint, semantic audit, counterexample, methodology-impact review, or
scope change may open an obligation without a new backend result.

Use the existing append-only branch trace as the container for bounded
research events. A trace event may contain or reference:

```text
EvidenceEnvelope?
  immutable observations and verification-attempt facts

AdjudicationProposal?
  proposed Claim-evidence delta
  proposed obligation delta
  compact Decision Warrant
```

When evidence exists, both proposed deltas should be evaluated together in one
AdjudicationProposal so they cannot drift. The Evidence Envelope itself
remains factual. A discovery-only event may contain an obligation-opening
proposal with a Contract, methodology, semantic artifact, counterexample, or
review reference instead of a computational Evidence Envelope. Accepted
projections change only after the applicable adjudication authority accepts
the proposal.

### Admissible obligation creation

Agents should be encouraged to propose obligations at the four discovery
triggers, but a proposal is admissible only when it states:

- a concrete subject, Claim, assumption, or uncertainty;
- the truthful scope;
- how it could change the named decision or permitted use;
- a distinguishable observation, resolution criterion, or explicit reason it
  can only be bounded;
- its origin and material alternatives/counterevidence;
- non-duplication or a justified split from an existing obligation;
- the evidence/adjudication class needed to change it.

Reject or keep non-authoritative:

- “do more research” without a decision-relevant question;
- duplicates phrased differently;
- deterministic schema/hash/timing checks that belong to Graph guards;
- obligations created solely because a metric was poor, with no changed Claim
  or falsifiable alternative;
- post-hoc thresholds presented as preregistered resolution criteria;
- questions outside the authorized scope unless they form an explicit scope
  expansion proposal.

Opening a well-formed obligation remains cheap and conservative. Classifying
it as a material decision blocker, or discharging it, requires the applicable
adjudication authority.

### Exhaustion is a stopping signal, not proof of truth

An Agent's inability to imagine another obligation or TrialPlan cannot by
itself establish completion. It may reflect weak prompting, missing Skills,
token exhaustion, unavailable data, or a backend capability gap.

A bounded **search-exhaustion checkpoint** can contribute to closure only when:

- the current versioned discovery procedure was executed over the pinned
  Contract and accepted projections;
- no new admissible material obligation survived deduplication/adjudication;
- no unresolved decision-blocking obligation has a feasible TrialPlan with
  positive expected decision value under the declared cost/resource policy;
- every failure to propose a TrialPlan is classified as `not_identifiable`,
  `low_information_value`, `capability_gap`, `data_gap`, `budget_pause`, or
  `out_of_scope`;
- capability/data/budget failures pause or route the branch rather than
  masquerading as completion;
- the closure remains decision-relative, methodology-versioned, bounded, and
  reopenable.

Thus “no meaningful obligation and no meaningful TrialPlan” may be one closure
evidence item, but not the definition of truth or the sole completion guard.

### Methodology updates and reopening

A new discovery lens, changed Graph trigger, changed admissibility rule, or
newly available verification capability creates a methodology-impact event.
Deterministic applicability first narrows affected Contracts/branches. The
Agent then proposes any newly implied obligations. Only affected research with
a material accepted delta reopens; a global update must not automatically
restart every historical Factor.

### Pending question 143.3-A

Recommended answer: accept the ownership boundary before deciding the exact
closure adjudication in Grill 143.4.

> Should Active Graph own only the versioned triggers, capability description,
> admissibility contract, freshness guard, and routing for obligation
> discovery, while concrete obligations and coordinated Claim/obligation
> deltas remain branch-local trace/projection state; should the Research
> Decision Contract be a normalized view over the existing Work
> Package/Hypothesis Branch rather than a new persistence owner; and should
> TrialPlans be generated only for selected actionable obligations?

### Human response to 143.3-A

Accepted. The human auditor then asks how Agents receive usable methodology
for obligation discovery, TrialPlan synthesis, evidence adjudication,
search-exhaustion assessment, and methodology-driven reopening when no such
Skill normally exists. The auditor also asks whether a server can learn from
client Skill updates and propose improved server methodology versions.

## Grill 143.3-B — reference Skill and methodology evolution

### These operations are capabilities, not edges

The following are graph-governed operations:

```text
research-obligation.discover
research-trial.synthesize
research-evidence.adjudicate
research-exhaustion.assess
research-methodology.impact
```

They are not themselves Graph edges. An edge remains a lifecycle transition.
Nodes or edge-readiness checks declare which operation must have a fresh,
valid output before transition. A lifecycle-changing result may then select an
edge:

- a new material obligation can route to TrialPlan design or revision;
- no approved implementation can route to CapabilityGap;
- accepted contradictory evidence can route to revision or rejection;
- an accepted methodology impact can reopen an affected closed branch;
- an admissible search-exhaustion result can contribute to closure readiness.

### Provide one client reference Skill, not five monolithic Skills

The system should ship a canonical **reference implementation** with the
client/Harness because an abstract capability description alone cannot teach a
new Agent the project's adjudication schema, statistical boundaries, and
first-principles procedure.

To preserve token efficiency, provide one concise router Skill with modes
rather than loading five Skills:

```text
research-obligation-cycle/
├── SKILL.md
├── agents/openai.yaml
├── references/
│   ├── obligation-discovery.md
│   ├── trial-synthesis.md
│   ├── evidence-adjudication.md
│   ├── search-exhaustion.md
│   └── methodology-impact.md
└── scripts/
    ├── validate-obligation-proposal.py
    └── validate-adjudication-proposal.py
```

The `SKILL.md` should contain only routing, compact input/output contracts,
approval rules, and the instruction to load exactly one relevant reference.
Product-specific accounting/statistical protocols remain separate
capabilities and are loaded only when triggered. Deterministic scripts validate
shape, hashes, scope, duplicate keys, and allowed proposal transitions; they
must not decide scientific truth.

The five modes are:

1. **discover** — Contract/projection to proposed Claims and obligations;
2. **synthesize** — selected actionable obligations to a TrialPlan proposal;
3. **adjudicate** — Evidence Envelope plus existing projections to coordinated
   proposed Claim-evidence and obligation deltas;
4. **exhaustion** — assess whether another admissible obligation or
   positive-information-value TrialPlan can be proposed and classify why not;
5. **impact** — compare methodology descriptors and identify affected
   Contracts plus proposed reopening obligations.

Shipping the reference Skill does not authorize execution. The first execution
is approved in the applicable Agent conversation against its exact content
hash. A matching installed hash and authority may be reused; changed content
requires fresh approval. If the Skill is unavailable or unapproved, the branch
enters CapabilityGap or waits rather than silently substituting an untracked
prompt.

### Preserve three independent version axes

Do not equate Skill version with Graph or methodology version:

| Version | Owns | Changes when |
|---|---|---|
| Graph version | lifecycle nodes, edges, triggers, guards, routing | lifecycle semantics change |
| methodology/capability descriptor version | inputs, outputs, admissibility, inference contract | scientific/procedural semantics change |
| local Skill/provider fingerprint | one executable implementation | implementation content changes |

The Decision Contract and search-exhaustion checkpoint pin the applicable
Graph and methodology descriptor hashes. The local audit pins the actual Skill
fingerprint and approval. A refactor or clearer wording can change the local
Skill fingerprint without requiring a new Graph. A semantic change must
produce a methodology-change proposal even if the capability ID remains
stable.

### Server may collect semantic proposals, not Skills

The proposal to let the server collect client Skill updates conflicts with the
accepted boundary that the server stores no concrete Skill identity, source,
version, or body. Do not reverse that boundary.

The client may instead submit a bounded **MethodologyChangeProposal**:

- current and proposed capability descriptor hashes;
- semantic input/output/admissibility diff;
- newly added discovery lens or adjudication rule;
- evidence, counterexamples, validation and failed-case refs;
- affected-Contract predicate;
- expected token/database/reviewer cost;
- compatibility and rollback target;
- opaque local implementation-validation refs, without Skill identity/body.

The existing Maintenance Case owner can reference this proposal. A Server
Maintenance Agent may use a separate local reference mode/capability,
`research-methodology.propose-version`, to compare repeated proposals,
applicable statistical/industry rules, counterexamples, and current Graph
semantics. It proposes a methodology or Graph version; it cannot approve or
install a client Skill. Graph/methodology changes retain grill-with-docs and
human audit.

In the current single-developer phase, submit methodology proposals explicitly
rather than building cross-user automatic collection. Multi-user aggregation,
privacy, consent, weighting, and poisoning resistance remain future policy
work and must not be smuggled into the first Active Graph.

### Update and reopening flow

```text
local Skill fingerprint changes
  -> invalidate local reuse authority
  -> conversation approval for changed execution
  -> conformance and forward tests
  -> implementation-only compatible change
       -> local audit update; no server version change
     semantic change
       -> MethodologyChangeProposal
       -> Server Maintenance Agent proposal
       -> grill-with-docs + human audit
       -> approved methodology descriptor / Graph version
       -> deterministic affected-Contract scan
       -> impact-mode obligation proposals
       -> accepted material obligations reopen only affected research
       -> new TrialPlans where actionable
```

The search-exhaustion checkpoint stores the Decision Contract hash, accepted
Claim/obligation projection hashes, Graph version, methodology descriptor
hashes, applicable product/protocol refs, and bounded search result. A new
approved methodology version invalidates only checkpoints whose applicability
predicate matches.

### Pending question 143.3-B

Recommended answer: accept one progressively loaded client reference Skill and
one server-side methodology-proposal capability while preserving the
server-no-Skill-identity boundary.

> Should the initial system ship one approved, progressively loaded
> `research-obligation-cycle` reference Skill with discover/synthesize/
> adjudicate/exhaustion/impact modes; let Graph nodes and guards require those
> capability outputs without turning the operations into edges; and allow the
> server to collect only bounded semantic MethodologyChangeProposals—not Skill
> identities or bodies—so a Server Maintenance Agent can propose audited
> methodology/Graph versions and selectively reopen affected research?

### Human response to 143.3-B

Accepted.

## Grill 143.4 — coupled adjudication without conflating evidence and obligations

### Claim evidence state and obligation state are coupled but distinct

A Claim evidence state answers:

> What does the currently admitted evidence indicate about this bounded Claim?

An obligation state answers:

> Has a specified epistemic responsibility been handled sufficiently under its
> declared discharge criterion?

They are not two names for the same state. In particular, completing a
well-designed test may discharge the obligation to run that test while
contradicting the Claim. Conversely, a favorable exploratory backtest may
increase support within a narrow scope while leaving confirmatory,
mechanistic, transfer, cost, and data-lineage obligations open.

Concrete cases make the boundary explicit:

| Event | Proposed Claim evidence change | Proposed obligation change |
|---|---|---|
| preregistered confirmatory test fails | `supported -> contradicted` in the tested scope | prediction-test obligation `open -> discharged` |
| exploratory backtest is favorable | `unknown -> supported_in_scope` with exploratory limitation | exploration obligation may discharge; confirmatory and transfer obligations remain or open |
| data lineage cannot be established | no positive Claim-state change; possibly `unassessed` | provenance obligation opens or is strengthened |
| first-principles review finds an untested alternative mechanism | no Claim-state change | a new mechanism-discrimination obligation opens |

The last case may have no new empirical Evidence Envelope. Obligation discovery
can arise from a lifecycle review, Contract change, contradiction, or
methodology impact. It still requires an auditable proposal and cannot silently
mutate the accepted projection.

### Evidence Envelope records facts; adjudication proposes meaning

The Evidence Envelope must remain a factual, reproducible record:

- TrialPlan and RunSpec/protocol hashes;
- inputs, time/data scope, chronology, code/backend identity where available;
- metrics, artifacts, failure and stopping information;
- multiplicity ledger and relevant limitations;
- compact references rather than embedded bulk output.

It does not directly declare a Claim true or an obligation discharged. An
Agent applies the relevant methodology and first-principles questions to
produce one bounded **AdjudicationProposal** containing:

```json
{
  "evidence_refs": ["evidence:..."],
  "claim_evidence_delta": [],
  "obligation_delta": [],
  "decision_warrant": {},
  "methodology_hash": "...",
  "proposal_fingerprint": "..."
}
```

Both delta fields are mandatory, but either may explicitly be a no-op. This
prevents an Agent from discharging an obligation without stating what the same
evidence did—or did not do—to the associated Claims, and prevents it from
upgrading a Claim while ignoring newly exposed obligations.

The Decision Warrant is not hidden chain-of-thought. It is a compact,
reviewable argument record:

- admitted evidence and factual findings;
- the applicable rule or first-principles question;
- inference type and whether the criterion was preregistered;
- alternatives and material counterevidence considered;
- the paired proposed deltas;
- scope, limitations, and reopening triggers;
- required adjudication authority and final disposition.

### One decision applies the paired deltas atomically

An **AdjudicationDecision** accepts, rejects, or requests revision of the
proposal. Acceptance applies the Claim-evidence and obligation deltas
atomically to their separate replayable projections. Rejection changes neither
projection. This avoids a transient or permanent state in which one projection
reflects an interpretation that the other does not.

This does not require a second graph or a new database object per proposal.
The branch-local trace can record bounded proposal and decision events; the
current research projection retains only compact accepted state, hashes, and
references. Exact persistence should reuse the existing trace/projection
owners unless measurement shows a missing invariant.

### Authority is determined by the kind of inference

The proposing Agent always has proposal authority, not unrestricted
self-certification authority:

1. Deterministic checks may accept identity, hash, chronology, scope,
   completeness, and reproducibility facts.
2. A preregistered machine-evaluable criterion may automatically accept only
   the exact matched empirical delta and declared scope.
3. A post-hoc criterion cannot retroactively masquerade as confirmation. Its
   result is exploratory, service, or bounded evidence and normally opens a
   confirmatory obligation.
4. Material semantic, mechanism, transfer, conflicting-evidence, or
   non-standard statistical judgments require one relevant independent
   reviewer.
5. Graph, methodology, backend, accounting, or production-policy changes
   require the already accepted grill-with-docs and human-audit path.

An unsupported or insufficiently authorized proposal remains pending or is
rejected; it never changes the accepted projections merely because an Agent
asserted that an obligation was discharged.

### Token-efficient execution

Routine validation of hashes, chronology, scope, criterion identity, and
delta shape is deterministic. A reviewer receives only the proposal,
Decision Warrant, relevant evidence summaries/references, and conflicting
state—not the complete Graph, catalog, artifacts, or research history. An
unchanged proposal/evidence/methodology fingerprint reuses its prior decision.
Only material, non-standard, or conflicting inferences invoke a reviewer.

### Pending question 143.4

Recommended answer: accept paired but distinct deltas under one atomic
adjudication.

> Should every research adjudication explicitly propose both a
> `ClaimEvidenceDelta` and an `ObligationDelta`—allowing either side to be an
> explicit no-op—and should one `AdjudicationDecision` accept or reject them
> atomically; with Evidence Envelopes limited to factual records, Agents
> limited to proposal authority, deterministic or exactly preregistered
> matches eligible for automatic acceptance, and post-hoc, semantic,
> non-standard, material, or conflicting judgments downgraded or independently
> reviewed?

### Human response to 143.4

Accepted.

## Grill 143.5 — bounded closure, search exhaustion, and reopening

### “Research complete” is too strong

Neither a favorable metric nor the absence of another immediately suggested
test proves that a Factor Family is fully understood. The canonical term
should therefore be **bounded closure**, not universal completion.

Bounded closure means:

> Under one versioned Research Decision Contract, applicable methodology,
> admitted evidence, declared search coverage, and stopping/resource
> boundary, the current research cycle has no unresolved decision-blocking
> obligation and no admissible, non-duplicative TrialPlan with positive
> expected information value that the Agent can presently justify.

This is a defeasible checkpoint. It authorizes only the Contract's named
decision and permitted-use boundary. It makes no assertion that the Factor is
universally valid, that all parameter configurations are good, or that unknown
unknowns do not exist.

### Closure belongs to a Decision Contract, not a bare Factor

A Factor Family version with many parameter configurations is not “complete”
because a threshold was crossed. The Contract must preserve:

- Factor Family and candidate-expression versions in scope;
- enumeration, sampling, adaptive-search, and elimination rules;
- configurations and parameter regions attempted, retained, or excluded;
- selection history and multiplicity exposure;
- relevant product, frequency, time, regime, cost, and implementation scope;
- the decision and permitted use that the evidence is meant to support.

For a scope containing multiple Factor Families, each scoped branch receives a
disposition, while the Campaign-level Contract additionally owns cross-family
selection and comparison Claims. Closing one family does not silently close
the Campaign; closing the Campaign does not imply that every possible family
was exhaustively searched.

The workspace planning Agent may maintain Contracts covering all authorized
workspace Factor Families, but bounded closure is still evaluated per Contract
and aggregated from explicit dispositions. This avoids one weak or blocked
family preventing unrelated research from progressing.

### Search exhaustion is a reviewable proposal

The `research-obligation-cycle` exhaustion mode should produce a compact
**SearchExhaustionProposal**, not a boolean assertion. It must show:

1. the pinned Decision Contract, Graph, methodology, Claim projection, and
   obligation projection hashes;
2. achieved versus declared candidate/configuration/regime coverage;
3. every decision-blocking obligation and its accepted disposition;
4. the remaining bounded unknowns, limitations, and monitoring transfers;
5. attempted TrialPlans and the current candidate TrialPlan frontier;
6. why each remaining candidate is inadmissible, duplicative, infeasible,
   outside scope, incapable of changing the named decision, or lower-value
   than the declared stopping/resource boundary;
7. the obligation-discovery lenses actually applied and any unresolved
   disagreement;
8. explicit re-entry predicates and freshness/expiry conditions.

Expected information value need not be reduced to a fictitiously precise
number. A typed, reviewable comparison is sufficient, provided the Agent
states what plausible result could change which Claim, obligation, or
decision. “The Agent could not think of another test” is not admissible
evidence of exhaustion.

### Closure has several dispositions

The checkpoint should distinguish at least:

- `decision_ready` — the named decision is supportable within its bounded use;
- `exhausted_without_support` — the search is currently exhausted but the
  requested positive decision is not supportable;
- `stopped_by_resource_boundary` — meaningful work remains but the declared
  budget or stopping rule has been reached;
- `blocked` — data, capability, approval, backend reliability, or another
  dependency prevents admissible progress;
- `superseded` — another Contract or version replaced this research question.

Only `decision_ready` authorizes the named positive use. The other
dispositions preserve negative, incomplete, or operational outcomes rather
than manufacturing a successful result. A stopped or blocked branch may be
inactive without being epistemically closed.

### Closure requires one independent challenge, not routine multi-Agent review

Most research transitions remain deterministic or single-Agent. Bounded
closure is different because an Agent could obtain it merely by failing to
generate a useful obligation or TrialPlan. The proposal should therefore
receive one independent **closure challenge** that is limited to:

- one plausible missing material obligation;
- one plausible decision-changing TrialPlan;
- one material coverage, multiplicity, or scope defect;
- one unjustified discharge or retained unknown;
- one missing or over-broad reopening trigger.

The reviewer receives only the compact checkpoint, projection summaries, and
referenced evidence needed for the challenge. It does not reload the complete
Graph, Skill catalog, research trace, or artifacts. If the reviewer finds a
material omission, it proposes the specific obligation or TrialPlan and the
branch remains active. A matching checkpoint hash reuses its prior review.

This single review occurs only at bounded closure, not after every test, and is
therefore materially cheaper than a fixed multi-Agent workflow.

### Reopening is impact-driven

A checkpoint becomes stale only when a versioned event matches one of its
applicability or re-entry predicates. Examples include:

- a Factor Family or expression version changes;
- intended use or product/regime/data scope expands;
- fresh conflicting or materially stronger evidence is admitted;
- freshness expires or a monitored regime condition is triggered;
- an approved Graph, methodology, statistical protocol, product-accounting
  rule, operator, or backend change affects the Contract;
- a newly accepted obligation-discovery rule identifies a material omission.

Deterministic code compares hashes and applicability predicates. A match does
not automatically rerun every test: it marks the checkpoint stale and invokes
impact assessment. The resulting proposal identifies affected Claims and
obligations; only accepted material deltas reopen the affected Contract and
generate TrialPlans where actionable.

Unrelated active jobs continue. A job whose interpretation is affected may
finish and retain its Evidence Envelope, but its adjudication waits for or uses
the new methodology as the approved migration policy specifies.

### Minimal persistence and token boundary

Persist the checkpoint as one bounded trace event plus its accepted
disposition, hashes, compact coverage summary, limitation/re-entry predicates,
and references. Do not copy full artifacts, full TrialPlans, complete
obligation history, or complete Graph context into it.

Routine validity checks—hash equality, freshness, unresolved blocking state,
coverage counters, and predicate matching—are deterministic. The Agent loads
only unresolved obligations, the candidate TrialPlan frontier, bounded
coverage summaries, and relevant evidence references. The independent
reviewer is invoked once per materially changed checkpoint hash.

### Pending question 143.5

Recommended answer: accept bounded closure as a defeasible,
Contract-scoped, independently challenged checkpoint rather than a metric
threshold or claim of universal completion.

> Should a research cycle pause only through a typed bounded-closure
> disposition backed by a `SearchExhaustionProposal`, requiring resolved or
> explicitly bounded decision-blocking obligations, declared search coverage,
> and no currently justifiable admissible positive-information-value
> TrialPlan; with one compact independent closure challenge, explicit
> limitation/re-entry predicates, and selective impact-driven reopening when
> evidence, scope, Factor versions, Graph, methodology, or backend semantics
> materially change?

### Human response to 143.5

Accepted.

## Grill 143.6 — minimal integration into the existing owners

### The accepted model does not justify a new subsystem

The current domain already has the required semantic owners:

- Agent Flow owns Workspace Research Objective, Work Package, Agent identity,
  authorization, resource accounting, and resume;
- Hypothesis Branch owns the current research/statistical projection;
- existing graph trace owns bounded immutable transition evidence;
- Evidence Envelope validates referenced facts;
- Factor Research Graph owns lifecycle, guards, and capability descriptions;
- Maintenance Case owns methodology, Graph, backend, and release change;
- the local audit owns actual Skill identity, fingerprint, and execution
  approval.

Adding a CognitiveDebt service, obligation graph, Claim database, TrialPlan
service, adjudication service, or closure table would duplicate these owners.
The new concepts should be schemas and replayable events projected through the
existing branch and trace boundary.

### Canonical semantic integration

The accepted terms should enter the canonical context as follows:

| Accepted concept | Existing owner | Minimal representation |
|---|---|---|
| Research Decision Contract | Work Package plus Hypothesis Branch | normalized versioned view and hash, not a new persisted entity |
| Research Claim | Hypothesis Branch | bounded Claim identity and current evidence-projection ref/hash |
| Verification Obligation | Hypothesis Branch | compact accepted current projection; immutable proposals/deltas in trace |
| TrialPlan | existing validation-design trace plus branch hash | unchanged owner; generated only for selected actionable obligations |
| Evidence Envelope | existing graph trace | factual execution/analysis envelope only; no authoritative conclusion |
| AdjudicationProposal/Decision | existing graph trace | paired Claim/obligation deltas plus compact warrant and authority result |
| SearchExhaustionCheckpoint | existing graph trace plus branch projection | one bounded checkpoint/disposition hash, not a new service/table |
| methodology change/reopening | Maintenance Case plus affected branch | semantic diff, impact proposal, accepted selective reopening |
| concrete Skill use | local audit | fingerprint, approval, execution receipt; never server Skill identity/body |

The existing `Factor Evidence Status` term should become the reader-facing
projection of bounded Research Claim evidence, not an independent mutable
status and not an Evidence Envelope field. The existing Evidence Envelope
definition must be narrowed: it may record stopping facts, metrics, conflicts,
and references, but the authoritative interpretation and decision rationale
belong to the accepted adjudication event.

### Versioned schemas before persistence changes

The first implementation artifact should be a small protocol package with
schemas and counterexample fixtures for:

- Decision Contract view;
- Research Claim and Verification Obligation;
- TrialPlan linkage;
- factual Evidence Envelope;
- paired AdjudicationProposal and AdjudicationDecision;
- SearchExhaustionProposal and bounded-closure disposition;
- MethodologyChangeProposal and impact/reopening proposal;
- the local `research-obligation-cycle` Skill mode I/O.

This package defines identity, scope, hashes, chronology, allowed transitions,
no-op semantics, authority class, freshness, and bounded references. It does
not yet dictate a new database layout.

Only after replay and query-path measurement should implementation decide
whether the existing Hypothesis Branch state can hold the compact projection
as-is or needs one bounded projection field. No per-Claim, per-obligation,
per-proposal, per-envelope, or per-checkpoint table should be created without
a measured invariant or hot-path requirement that the trace plus current
projection cannot satisfy.

### Activation order

The minimal implementation order should be:

1. update the canonical context and decision log from this accepted grill;
2. define protocol schemas, examples, counterexamples, and deterministic
   validators;
3. implement trace replay and current-branch projection in shadow mode;
4. ship the progressively loaded local reference Skill and conformance tests;
5. add node-local capability descriptors and compact Agent packets;
6. activate obligation discovery, adjudication, exhaustion, and selective
   reopening behind a new Graph/methodology version;
7. migrate only affected active research through an explicit impact policy;
8. retain rollback to the previous approved Graph/methodology pointer.

This order prevents prompt prose from becoming the de facto protocol and
prevents database migrations before semantic identities and hot reads are
known.

### Legacy evidence must not acquire invented certainty

Old Evidence Envelopes and Factor Evidence Status values remain valid
historical records under their original schema version. Migration must not
fabricate discharged obligations or stronger Claim states.

A legacy branch may be projected as:

- known factual evidence retained by reference;
- Claim interpretation marked legacy, bounded, or requiring adjudication;
- obligations initialized by the current discovery method only when the
  affected Contract is resumed or impact analysis requires it.

The migration is lazy and branch-local. It must not scan and rewrite all
historical research merely to activate the new method.

### Conformance and performance acceptance

Before activation, tests must prove:

- Evidence Envelope facts alone cannot mutate Claim or obligation projections;
- accepted paired deltas apply atomically and rejected/pending proposals apply
  neither side;
- trace replay produces the same projection after process/model/runtime
  restart;
- an unchanged evidence/proposal/methodology hash reuses validation and review;
- legacy records retain their original interpretation, do not gain invented
  discharges, and remain unavailable to Agent-facing retrieval;
- only current-branch projection and referenced changed evidence are read on
  the routine path;
- no whole-Graph, whole-catalog, whole-trace, or artifact-body loading occurs
  in the default Agent packet;
- routine transitions start no reviewer; bounded closure starts at most one
  reviewer for a materially changed checkpoint;
- unrelated jobs and branches continue through methodology impact;
- Graph/methodology activation and rollback are pointer/version operations;
- context bytes, token usage, query count, rows read/written, and cache hits
  satisfy explicit regression thresholds measured against the current
  implementation.

Exact byte, token, and query thresholds should be set from baseline
measurement rather than invented in this grill. A regression gate must still
exist before activation.

### Pending question 143.6

Recommended answer: accept this as the final semantic integration gate for
Grill 143, then formalize the accepted terms and produce a separately
reviewable implementation work package rather than editing the already
completed issue-140 batches retroactively.

> Should the cognitive-obligation design be integrated only as versioned
> schemas, trace events, compact Hypothesis-Branch projections, node-local
> capability descriptors, and one local reference Skill over the existing
> owners—without a second graph or new dedicated persistence services—and
> should implementation proceed schema/conformance first, shadow replay
> second, measured minimal persistence third, and new Graph/methodology
> activation last, with lazy legacy handling and explicit token/database
> regression gates?

### Human response to 143.6

Accepted.

### Post-acceptance access refinement

The human auditor tightened the legacy boundary: old Evidence Envelopes must
not be available to Agents.

The final interpretation is:

- legacy envelopes remain retained only for privileged, non-Agent historical
  audit;
- Research Agents, Reviewers, Skills, and ordinary Agent retrieval cannot load
  legacy payloads, decisions, metrics, artifacts, or references;
- deterministic compatibility code may inspect only the minimum bounded
  schema-version/hash/eligibility metadata needed to mark the record
  `legacy_ineligible`;
- no Agent may use an old conclusion as context for a new adjudication;
- reopening starts current obligation discovery without legacy evidence
  content and requires new current-schema evidence.

This is stricter than lazy Agent-side reinterpretation and replaces that part
of the earlier migration proposal.

## Final disposition

Grill 143 is accepted through 143.6. The accepted design:

- reserves “cognitive debt” for process-level fragility and models factor
  research through scoped Research Claims and Verification Obligations;
- keeps one Factor Research Graph and places concrete obligations in
  branch-local trace/projection state;
- treats Research Decision Contract as a normalized view over existing Work
  Package/Hypothesis Branch ownership;
- uses a progressively loaded local `research-obligation-cycle` reference
  Skill while the server remains Skill-neutral;
- keeps Evidence Envelopes factual and applies paired Claim/obligation deltas
  only through one atomic AdjudicationDecision;
- replaces universal “completion” with independently challenged bounded
  closure and selective impact-driven reopening;
- reuses existing branch, trace, Maintenance Case, capability, and local audit
  owners instead of creating a second graph or dedicated persistence services;
- keeps legacy evidence outside every Agent-facing retrieval/context surface
  and requires new evidence after reopening;
- requires schema/conformance-first delivery, shadow replay, measured minimal
  persistence, lazy legacy handling, and explicit token/database regression
  gates before a new Graph/methodology version is activated.

Implementation is intentionally outside this grill record and must proceed in
independently reviewable, revertible batches.

## Post-acceptance market-context refinement

The human auditor later authorized a bounded industry review of the obligation
Skill's market-environment semantics. This did not add a second graph, a new
edge per event, or a new persistence owner. It refined the existing
Decision Contract → obligation discovery → TrialPlan → Evidence Envelope →
adjudication/closure cycle.

The reviewed refinement is:

- create `performance_transportability` as a coverage intent when the bounded
  decision depends on transfer across time, market state, or products; do not
  persist the Cartesian product of every interval and instrument;
- create or elevate `market_context_heterogeneity` only after a predeclared
  event or deterministic diagnostic exposes a material break, product
  difference, or execution/liquidity anomaly;
- distinguish `co_occurrence`, a falsifiable `mechanism_hypothesis`, and
  separately identified `causal_evidence`; an event narrative cannot promote
  itself from temporal coincidence to causation;
- keep post-outcome event search exploratory, bounded to at most three compact
  mechanism candidates, and require a new unexposed window or product for
  confirmation;
- treat the latest feasible interval as a sealed holdout only while it remains
  unseen by the factor/parameter/event-rule selection chain. Once used for an
  adaptive change it becomes `historical_adaptive_evidence`, and a new forward
  obligation is required;
- distinguish real-order `live_execution_evidence`, prospective
  `forward_shadow_evidence` (including `latency_class=delayed`), and
  `historical_simulation_evidence`. Neither delayed Tiger L2 paper execution
  nor tick replay discharges real fill, impact, or latency obligations;
- allow a market explanation to end as `bounded_unknown` with searched scope
  and reopening predicate. Complete causal explanation is not a universal
  closure requirement.

The implementation remains token-bounded: deterministic heterogeneity
diagnostics trigger the search; the Agent receives only the anomaly summary,
window, products, cutoff, and existing event refs; local cached event refs are
checked before network search; one specialist sub-agent is reserved for a
decision-blocking, cross-jurisdictional, timestamp-conflicted, or
multi-mechanism question.

Industry support is recorded in the evidence registry under
`S-EVENT-STUDY`, `S-PREREG`, `S-REALITY-CHECK`,
`S-REUSABLE-HOLDOUT`, and `S-HYPOTHETICAL-PERFORMANCE`. These sources constrain
evidence language and sample-use semantics; they do not hard-code a specific
calendar split, causal model, metric threshold, or graph edge.
