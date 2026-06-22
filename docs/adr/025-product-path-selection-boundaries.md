# ADR 025: Product Path Selection Boundaries

## Status

Accepted

## Context

The single-factor page used to treat a frontend submission as a page-scoped
`FactorTester`.  That blurred three different concepts:

- a user product-group template stored in SQLite,
- a product/path universe selected for one test configuration,
- the `FactorTester` runtime object used by IC or group-test execution.

This caused page-level state to leak into IC/group tests, made sorting ambiguous,
and forced global overlays such as product category and return-frequency settings
to exist outside the concrete test that actually needs them.

## Decision

Introduce `ProductPathSelection` as the backend object for a selected
product/path universe.  It owns only path and product-universe semantics:

- `selection_id`
- `selected_paths`
- `product_group`
- source metadata such as `manual_selection` or `user_product_group_template`
- lazily resolved products

One row in the user product-group SQLite store can build exactly one
`ProductPathSelection` through `product_group_to_path_selection`.

`ProductPathSelection` must not create, update, or delete `FactorTester`
instances.  IC test and group test runners create their own `FactorTester`
objects at run time from the product selection carried by that test's settings.
The page-level product selection lookup is only a compatibility bridge until the
frontend sends `product_selection` or `product_selections` inside the concrete
test payload.

Ordering is owned by the user product-group template store.  Page-level
product-path selections do not implement reorder semantics.

## Consequences

The frontend should remove page-level product category and return-frequency
overlays.  These choices should be opened from the IC/group test setting modules
that need them.

IC test and group test must keep independent backend setting applications.  They
can share registry infrastructure and base-field builders, but each test module
owns its own tabs, defaults, disabled values, chips, and lazy-loaded setting UI.

Existing result and snapshot APIs may continue to expose `submission_id` where
the meaning is the strategy owner id inside a specific test run.  New product
universe APIs should use `product_path_selection_id` or `selection_id`.

`FactorTester` remains a runtime compute context.  Business runners such as IC
and group test own tester creation for their run, attach the selected product
universe metadata, and register the tester only for result lookup after the run.
