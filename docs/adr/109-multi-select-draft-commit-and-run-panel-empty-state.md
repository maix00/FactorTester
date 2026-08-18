# ADR 109: Multi-select draft commit and test-run empty state

## Status

Accepted

## Context

The shared multi-select control is used by product, factor, category, output,
and test configuration surfaces. Several callers rerender their parent after a
selection changes. Calling the change callback for every checkbox click caused
the newly created `<details>` element to close after the first selection, so a
user could not make a multi-selection in one interaction.

The test-run batch surface also appeared before a product group existed and
showed disabled actions plus an empty-state message. That duplicated the
product selector's guidance and made an unconfigured test look broken.

## Decision

- Multi-select controls maintain a draft selection while the menu is open.
- They render one save/apply action. The caller callback runs only after that
  action succeeds, and the menu then closes. Closing without saving restores
  the last committed selection.
- Single-select controls continue to commit immediately and close after one
  choice.
- The test-run batch surface is not rendered until at least one product group
  is selected. The product selector remains the single place that asks the
  user to choose a product group.

## Consequences

All shared multi-select callers get the same predictable interaction and can
still provide a custom apply label or persistence callback. The workbench has
no misleading run panel before it has a runnable product scope; after a
selection, RunSpec, run, progress, and result controls are unchanged.
