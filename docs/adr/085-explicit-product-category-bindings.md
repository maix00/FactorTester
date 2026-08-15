# ADR 085: Explicit Product Categories and Canonical Product-Group Paths

## Status

Accepted

## Context

The product catalog exposes two different concepts that had been conflated:
the category-free classifier path of a Product, and a category projection such
as `日夜盘/日盘` or `行业/工业品`. Product groups persisted the path emitted by
the selected tree, while composite-category choices lived in browser
`localStorage`. As a result, a group could not be resolved reproducibly away
from the browser that created it, and the old resolver had an implicit category
context.

## Decision

1. A canonical product path is the classifier object path, for example
   `Product/Futures/CNFutures/_products/SI.GFE`. Category segments are never
   persisted in a new product-group `paths` value.
2. A category-qualified path is normalized at write time. The selected
   `category_ids` are required for new product groups; the category tree is
   used to expand a category branch to exact canonical object paths while
   preserving positive and negative path semantics.
3. User-created category definitions and composite definitions are stored in
   the Manager account SQLite store, scoped by username. Provider categories
   remain source-owned projections and carry a data-source bundle identity
   such as `Local`; a bundle identity is not a server identity. Composite
   definitions are explicit rows, not browser-local state.
4. Product groups persist `category_ids` even after their paths have been
   expanded. This records the category context used to create the group and
   lets the UI display the binding. The runtime resolver uses the canonical
   paths and never adds a default category.
5. Existing rows are read with a compatibility migration: recognizable
   legacy category paths infer a source category and are rewritten to
   canonical paths. Unrecognized legacy rows remain readable and report their
   unresolved paths; new writes fail instead of silently guessing.

## Consequences

- Product groups are portable across Web, Swift, and Manager instances that
  share the same canonical catalog contract.
- One data-source bundle may have multiple server providers. The federated
  source descriptor is authoritative for the online provider list; category
  metadata must never select a single server implicitly.
- Changing a category later does not silently mutate an existing group; the
  group contains the exact canonical product paths used at creation time.
- The product tree is a read/selection surface. Category creation and
  composition are managed only from the dedicated 产品分类 tab.
- User category synchronization can be added as an account-domain projection
  later without reintroducing browser-local definitions.
