# ADR 118: Factor References and Semantic RunSpec v3 Ordering

## Status

Accepted for Issue #287.

## Context

Test authoring represented one factor repeatedly as `factorAlias`,
`factorAliases`, analysis-level family aliases, and a shared family catalog.
Aliases are display labels and can change or collide; they are not suitable as
runtime identity. Canonical RunSpecs were also serialized with sorted object
keys, making their human-facing order alphabetical instead of preserving the
backend registration order and its semantic grouping.

## Decision

- A strategy stores only `factor_candidate_refs`. Role bindings also store
  factor refs. It does not store factor aliases as execution identity.
- `shared.factors` is the frozen ref-to-descriptor table. Each descriptor owns
  its label, owner, family, parameters, and optional Git revision metadata.
- Immediately before execution, the Manager resolves every selected ref into
  a real `Factor` object. Backtest runtime modules continue to receive Factor
  objects and never aliases or refs.
- A factor-family catalog is loaded only by the factor-create/view surface. It
  is not part of a workspace or RunSpec. Inline uploaded family source remains
  a retained run input under `temporary_objects.factor_families`; revision
  manifests freeze its executable semantics.
- RunSpec v3 removes analysis/root family aliases and legacy strategy alias
  fields. Older RunSpec versions are rejected rather than repaired at runtime.
- Persistent and displayed RunSpec JSON preserves insertion order from backend
  registration. Only identity hashing uses a temporary sorted-key encoding.

## Consequences

Strategy identity is stable across label changes, chip detail actions resolve
the same objects used for execution, and a frozen RunSpec has one canonical
factor representation. Human readers retain semantic field grouping while
content hashes remain independent of object-key order. Existing v1/v2 RunSpecs
must be previewed and submitted again as v3 before they can run.
