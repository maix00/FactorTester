# Context Map

## Contexts

- [FactorTester](CONTEXT.md) — owns factor, data, expression, execution, test,
  workspace, run, and job language.
- [Research Decision Governance](docs/research-decision-graph/CONTEXT.md) —
  owns the research-method graph, Agent orchestration boundary, evidence
  lifecycle, capability-gap routing, and high-risk change audit language.

## Relationships

- **Agent Flow → Factor Research Graph**: supplies an Agent identity, confirmed
  Work Package, checkpoint, budget, and compact current-node request.
- **Factor Research Graph → FactorTester**: freezes FactorTester factor, data,
  RunSpec, job, result, and artifact identities as evidence references.
- **Factor Research Graph → Server Maintenance**: emits a bounded
  **Capability Gap** when the current research branch lacks an exact approved
  implementation.
- **Server Maintenance → Agent Flow**: publishes an implementation receipt that
  can resume only the affected checkpointed branches.
- **Research Decision Governance → FactorTester**: never becomes another owner
  of a workspace, run, job, factor source file, or result artifact.
