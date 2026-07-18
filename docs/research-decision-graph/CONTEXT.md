# Research Decision Governance

This context defines how evidence-driven factor research is orchestrated,
reviewed, resumed, and evolved without replacing FactorTester computation or
turning routine transitions into LLM conversations.

## Language

### Research method

**Factor Research Graph**:
A versioned graph whose nodes and edges express factor-research decisions,
guards, evidence requirements, and triggered capability descriptions.
_Avoid_: Agent workflow, job scheduler, fixed checklist, knowledge graph

**Candidate Discovery**:
The bounded process that finds, creates, repairs, or re-roles a factor
candidate before its hypothesis is frozen.
_Avoid_: Alpha whitelist, full factor-library scan

**Hypothesis Branch**:
An immutable research path beginning when a testable candidate is
preregistered and bound to its trial records.
_Avoid_: Draft idea, mutable experiment

**Provisional Memory**:
Local, reviewable process evidence from one research path that has not been
promoted into a reusable graph rule.
_Avoid_: Active edge, global memory, chat history

**Factor Evidence Status**:
A scope-bound statement that a factor is untested, evaluated, supported,
contradicted, inconclusive, or superseded for a specific immutable
configuration and research scope.
_Avoid_: Valid factor, invalid factor, `$Rev`

**Market State Snapshot**:
A point-in-time, versioned, deterministic summary of market conditions used to
rank candidates or preregister conditioning hypotheses.
_Avoid_: Ex-post regime label, candidate whitelist

### Orchestration

**Agent Flow**:
The runtime-neutral orchestration layer for Agent identity, goals, Work
Packages, checkpoints, watchers, budgets, Git coordination, and routing.
_Avoid_: Factor Research Graph, LangGraph requirement

**Workspace Research Objective**:
The user-owned long-term direction covering all factor families in one
workspace.
_Avoid_: One factor run, server maintenance goal

**Work Package**:
A user-confirmed bounded research authorization containing objective, mode,
factor/product/data scope, permissions, exclusions, and expected evidence for
one Research Agent.
_Avoid_: Entire workspace objective, backend maintenance case

**Targeted Research**:
A Work Package mode with an already identified primary factor or factor range.

**Open Discovery**:
A Work Package mode authorizing an Agent to create and study new candidates
inside a confirmed market, data, theme, permission, and exclusion boundary.

**Coordination Checkpoint**:
The compact server record needed to resume an Agent identity and affected
branch without storing local source, full artifacts, or reasoning.
_Avoid_: Full research checkpoint

### Capability and governance

**Capability Gap**:
A bounded, general, source-free contract showing that an exact approved
implementation required by the current branch is unavailable.
_Avoid_: Factor failure, approximate fallback, whole-graph capability scan

**Maintenance Case**:
A bounded Server Maintenance workflow that reviews, implements, validates, and
releases one graph, Skill, statistical-policy, or backend change.
_Avoid_: Factor Research Graph node, permanent LLM monitor

**Document-grounded Grill Audit**:
A one-question-at-a-time high-risk change audit grounded in domain documents,
code facts, industry or statistical rules, concrete scenarios, and
counterexamples.
_Avoid_: Ordinary graph transition, UI approval, fixed Skill name

**Grill Decision Log**:
The working record of audit questions, user responses, final semantics,
evidence, impact, acceptance criteria, and revision lineage.
_Avoid_: ADR, transcript-only archive, routine Agent context

## Relationships

- A **Workspace Research Objective** produces one or more **Work Packages**.
- A **Work Package** is owned by one Research Agent at a time and may create
  many independent **Hypothesis Branches**.
- A **Work Package** may reference an Agent Flow resource-budget scope, but
  does not define token, compute, time, concurrency, statistical stopping, or
  multiplicity semantics.
- **Candidate Discovery** may short-circuit for **Targeted Research** or
  generate bounded candidates for **Open Discovery**.
- A **Hypothesis Branch** follows one pinned **Factor Research Graph** version.
- An affected **Hypothesis Branch** emits at most one deduplicated
  **Capability Gap** for the same gap hash.
- A **Capability Gap** creates a **Maintenance Case** outside the
  **Factor Research Graph**.
- A high-risk **Maintenance Case** may require a
  **Document-grounded Grill Audit**.
- Accepted audit semantics are appended to the **Grill Decision Log** and are
  implemented by an Agent; the human auditor does not edit graph or source
  records.
- **Provisional Memory** can propose a graph change but does not itself become
  an active edge.

## Example dialogue

> **Research Agent:** "The current hypothesis branch needs a pointwise `tanh`
> capability, but the local binding has no approved implementation. I recorded
> a source-free Capability Gap and checkpointed only this branch."
>
> **Server Maintenance Agent:** "The change affects a backend contract, so I
> opened a Maintenance Case. The audit will compare the proposed semantics,
> existing FactorExpr contract, NaN behavior, batch/incremental parity, and
> counterexamples one question at a time."
>
> **Auditor:** "The capability intent is accepted. Implement it without
> changing existing operator semantics, then publish a conformance receipt."

## Flagged ambiguities

- “Active flow” previously referred to both research method and Agent
  orchestration. Resolved: **Factor Research Graph** owns research semantics;
  **Agent Flow** owns runtime orchestration.
- “Grill inside the Active Graph” implied a routine graph node. Resolved:
  high-risk audit belongs to a **Maintenance Case** outside the ordinary
  research graph.
- “Validated factor” implied global truth. Resolved: use scope-bound
  **Factor Evidence Status**.
- “Goal keeps an Agent online” implied continuous LLM execution. Resolved: the
  goal persists while deterministic event/watch logic wakes an Agent only when
  action is possible.
- “Work Package budget” previously mixed user authorization, statistical
  stopping, and runtime resource control. Resolved: **Work Package** owns
  research authorization, **Factor Research Graph** owns statistical research
  semantics, and **Agent Flow** owns operational resource enforcement.
