# ADR 015: Explicit Factor Author SDK and Repository Boundary

## Status

Accepted

## Context

Factor workspace stubs were selected by recursively following implementation
dependencies from `@factor_workspace`, `__factor_workspace__`, and guarded
`FACTOR_WORKSPACE` imports. Internal runtime types therefore became visible to
authors, generated imports could point to missing stubs, and the public surface
changed when implementation imports changed.

Workspace Git behavior was also split between construction, synchronization,
hooks, and the autosync script. Generated hooks captured the current issue
worktree path, which became invalid after that worktree was removed.

## Decision

- `tools.data.factor_workspace.sdk` is the sole module-level allowlist for the
  generated author SDK.
- `@factor_workspace` selects author-visible symbols and methods only inside an
  allowed source module. It never pulls another module into the SDK.
- `__factor_workspace__` identifies exported singleton values inside an allowed
  module. Runtime imports do not define the SDK surface.
- Generated stubs omit authoring decorators and their scanner infrastructure.
- `FactorWorkspaceRepository` owns initialization, branch selection, commits,
  branch materialization, state, HEAD lookup, and download-to-upload merging.
- Hooks target the stable shared `feat` root rather than the worktree that
  happened to generate them.
- The manifest is refreshed after branch materialization so its selected branch
  matches the actual repository state.

## Consequences

Adding a new author API now requires an explicit SDK contract change and a
generated-artifact test update. This is intentional review friction. Runtime
refactoring no longer expands the author workspace accidentally, while operator
method signatures can still be maintained next to their implementation with
`@factor_workspace`.
