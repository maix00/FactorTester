# ADR-011: Page state debug registration follows runtime ownership

## Context

Page debug data was assembled in the lifecycle route and the single-factor page route. This duplicated fields, coupled the generic endpoint to single-factor internals, and caused debug probing to construct factors instead of observing existing page caches.

## Decision

- `server/services/page_state_debug.py` is the only debug-section registry and payload builder.
- A service that owns page-scoped state registers its own section. Page identity is registered by `page_runtime`; single-factor `FactorFamily` and `Factor` caches are registered by `factor_registry`.
- Global sections apply to every page. Page-specific sections are selected by `page_kind`.
- Registering the same `section_id` again replaces the previous registration. Every request builds a fresh, complete snapshot of currently active registrations.
- Every section includes the requested `page_uuid`. Providers only inspect existing state and must not create runtime objects.
- The HTTP route only validates the query and serializes the registry result; page route modules do not register debug content.

## Consequences

Future test pages register their debug data in the service that owns their page-scoped state. Adding a module no longer requires changing the shared debug route, and debug requests cannot alter factor lifecycle state.
