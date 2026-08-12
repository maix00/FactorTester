# ADR 061: Long-file audit and semantic module boundaries

## Status

Accepted as the staged refactoring direction on 2026-08-13.

## Context

The Manager composition-root migration reduced `server/manager/runtime.py` from
more than six thousand lines to roughly 350 lines and retired the former
`scripts/worktree_*` import namespace. A repository-wide follow-up audit found
that length alone was not the remaining architectural problem:

- 61 production Python files contain at least 600 lines;
- 31 contain at least 800 lines;
- 12 contain at least 1,200 lines;
- some files are cohesive, deep domain Interfaces with a deliberately broad
  API, while others combine unrelated storage, transport, projection, CLI, and
  compatibility Implementations;
- several incomplete migrations retain both the old compatibility function and
  the new owning Module.

This ADR records the priority and constraints for subsequent refactoring. It is
an audit decision, not authorization to change runtime behavior while moving
code.

## Decision

Long files are split only where a semantic ownership Seam exists. Line count is
a review signal, not the design goal. A new Module must improve at least one of
the following without reducing the others: Interface Depth, ownership
Locality, independent testability, dependency direction, or removal of a
duplicate Implementation.

The staged order is:

1. Finish the grouped-test migration. Keep
   `server/modules/single_factor_test/group.py` as a shallow HTTP Adapter, move
   snapshot, product metadata, detail projection, and research-run behavior to
   the existing `tools/factors/tester_calc/single_factor_test/group/` package,
   migrate tests to public Interfaces, and delete compatibility stubs and
   duplicate helpers.
2. Split Manager persistence by ownership. PostgreSQL connection and
   transaction handling remain shared, while account/device, organization and
   level, source version and Profile, and quota/task reservation behavior gain
   focused repository Implementations. The local job index separates event
   synchronization, routing projection, reconciliation, and read queries behind
   a stable facade.
3. Separate Manager federation responsibilities: server registry, remote HTTP
   Gateway Adapter, route and capability selection, synchronization workers,
   task projection, and administrative HTTP routes. Public, server-wide, and
   account task aggregation must share one paging/projection pipeline instead
   of repeating the same control flow.
4. Extract native scheduler audit serialization and step-diff projection from
   the scheduling core. `FlowContext`, `EventQueue`, flow ordering, and their
   hot-path caches remain colocated unless profiling proves a better boundary.
5. Separate FieldHistory CLI, persistence codec/store, and runtime integration
   from the lookup Provider. Shared FieldHistory view normalization and
   serialization become one implementation.
6. Split broad CLI controllers by user-facing command family while retaining a
   single composed CLI Interface. Artifact conversion and terminal rendering
   are not command registration responsibilities.
7. Refactor MarketData, FactorSignal, and TermStructure only after
   characterization and performance tests cover their cache and event-order
   contracts. Candidate Seams are request planning, source loading, historical
   rules, event snapshots, live versus precomputed signals, lifecycle data, and
   rollover execution.
8. Decompose Research Graph transitions into pure preparation, guard,
   projection, and trace-construction stages, but retain one outer atomic
   database transaction. CLI navigation and obligation commands remain
   Adapters over those domain operations.

Confirmed active duplicate Implementations are removed as the owning areas are
changed, including:

- factor-execution and market-data setting registration in both
  `tools/testers/settings/applications.py` and `tools/testers/_shared/`;
- executable-delta calculation duplicated by the Qlib and Zipline runners;
- FieldHistory unified-frame normalization repeated in three view modules;
- grouped-test parent inheritance and product-selection identity helpers in the
  old route module and the new research-run settings Module.

## Constraints

- `FactorExpr`, `DataIndex`, and `FactorFamily` are not split merely to lower
  line counts. They currently provide cohesive, deep Interfaces; shallow
  mixins would reduce discoverability and Locality.
- Hot-path stores and caches remain with the state they protect, consistent
  with ADR 053.
- A transaction may call extracted pure functions, but database atomicity must
  not be distributed across independently committing repositories.
- Compatibility Adapters are temporary and must have an explicit deletion
  condition. A moved implementation is not complete while production or tests
  still depend on the retired private helper.
- Generated or deliberately mirrored skill payloads are excluded from duplicate
  consolidation unless their packaging contract is changed first.

## Enforcement

After the first three stages establish representative boundaries, CI will add
an architectural size audit. New production Python files at or above 800 lines
and new functions at or above 250 lines require either decomposition or a
documented allow-list reason. Existing files are tracked as a non-increasing
baseline until their owning stage is completed. The guard must not reward
shallow pass-through Modules or moving code into untyped data files.

## Consequences

- Refactoring follows ownership and dependency direction rather than arbitrary
  file-size targets.
- The highest-Leverage incomplete migration and Manager control-plane work are
  addressed before riskier backtest hot paths.
- Long but cohesive domain Interfaces remain readable and stable.
- Duplicate behavior has one owner, and compatibility paths have a defined end
  state.
