# ADR-050: Test Workbench and Job Detail Boundary

## Status

Accepted.

## Context

The original service-port IC and group-backtest pages combined reusable test
configuration, transient execution controls, task monitoring, domain result
exploration, and artifact management in one page. The current client also has
a durable, cross-port Job page backed by the canonical ResearchRun and
JobAttempt records. Copying the original pages literally would create two
competing representations of progress, frozen configuration, results, and
artifacts.

The restored test experience must preserve the useful domain interactions of
the original pages without weakening the durable Job lifecycle or duplicating
its implementation.

## Decision

The test workbench owns authoring and comparison:

- reusable test settings and templates;
- factor, factor-set, product-group, category, and group-strategy selection;
- per-run fields such as service port, retention, step mode, profiling, and
  requested outputs;
- preview of the execution matrix and one submission per independently frozen
  product scope;
- product-scope tabs containing status, compact result comparison, and links
  to the corresponding Job, frozen test configuration, and RunSpec.

The three linked objects remain distinct:

- the frozen test configuration is the normalized application settings used
  to create the run;
- the RunSpec is the content-addressed execution contract derived from that
  configuration;
- the Job is one concrete execution attempt and its retained outputs.

The Job detail page is the canonical execution record:

- lifecycle state, progress, caller, research binding, and deployment port;
- the exact frozen configuration and RunSpec;
- full domain result exploration and every retained artifact;
- after-run artifact generation, download, deletion, approval, step, cancel,
  retry, and restoration of a frozen run as editable configuration.

IC and backtest visualizations are shared modules. The workbench may embed the
same domain viewer for a compact, manually refreshed result preview; it must not
implement another parser, chart, or result state model. The Job page mounts the
same viewer with the complete declaration and artifact set.

For IC, one product scope creates one Job. Within that Job, factor values are
reused while evaluating the factor × forward-horizon × entry-delay × IC-method
matrix. A matrix cell is not a Job. Multiple product scopes remain independent
Jobs because they have independent RunSpecs and execution outcomes.

`factor_selections` is the ordered set of concrete factors used by an
application configuration. A factor-set may populate that selection, but the
selection is not itself a factor-set: the former belongs to one mutable test
configuration, while the latter is a stable reusable domain object with its
own identity and membership.

Old interactions are migrated by semantic value:

- domain selectors, result switching, highlighting, drill-down, and comparison
  views move into the shared viewer;
- placeholders, browser-owned polling, and fields that were never consumed by
  the executor are not reproduced;
- a field that affects execution must be declared by the application settings
  registry and frozen into a configuration or RunSpec;
- a local file control is exposed only when the registered field contract has
  an explicit upload serialization and authority boundary.

## Consequences

- The workbench retains the original interactive research workflow while Job
  detail remains the single source of truth for an execution.
- Opening a Job, its configuration, or its RunSpec uses an explicit link rather
  than copying opaque JSON into the workbench.
- Web and embedded Swift clients consume the same pages and result components.
- Restoring old UI becomes a contract-driven gap audit instead of a literal
  source-code transplant.
