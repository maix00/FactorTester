# Context Map

## Contexts

- [FactorTester](CONTEXT.md) — owns factors, data, expressions, execution,
  workspaces, Research, Reports, Evidence, Runs and Jobs.
- [IC Testing](docs/ic-test/CONTEXT.md) — owns IC test-result facts and the
  boundary between test execution, result objects, renderers and presentation
  artifacts.

## Relationships

- **Research → Report**: Research supplies collaboration scope and membership;
  Reports and their branches own authored report content and publication.
- **ResearchRun → Job → Artifact**: a frozen run defines execution inputs, a Job
  records execution, and Artifacts preserve selected outputs.
- **Profile → Research/Report**: client and server Profiles use the same
  Research and Report identities while retaining their own runtime and access
  boundaries.
- **IC Testing → FactorTester**: IC testing uses FactorTester for execution and
  result access, but does not persist the runner as a test result.
