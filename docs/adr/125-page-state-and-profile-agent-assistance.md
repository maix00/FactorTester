# ADR 125: Page state and Profile Agent assistance share registered semantics

## Status

Accepted

## Context

Left-navigation tabs can keep live DOM briefly, but memory eviction and reload
must rebuild a page. DOM control snapshots alone cannot restore selected nested
tabs, custom widgets, owned overlays, or the JavaScript model behind a form.
Server-hosted Profile Agents also need to understand and update the page that a
person is viewing, while the Agent process cannot access the browser's WebMCP
runtime directly.

## Decision

1. Each left-navigation tab owns a versioned `FTPageState` registry. Shared
   components register serializable state under stable section identifiers.
2. A tab checkpoint captures registered state into the existing browser-local
   tab workspace. Performance eviction disposes live registrations and DOM but
   retains their serializable state; route reconstruction registers the same
   sections and restores them before the page is presented.
3. A reusable right-side Agent drawer binds a page to one Profile. Research
   reports use their bound Profile; every other assisted surface uses the
   current account's `self` Profile.
4. Drawer visibility and Agent runtime lifetime are separate. Hiding a drawer
   does not stop the Agent. A browser-local profile ownership registry starts
   once and stops only after the last tab that opened that Profile is evicted.
5. An assisted page registers one versioned Agent Assistance Document Adapter:
   schema, export, validation and atomic import. Registration automatically
   mounts the right-edge trigger and drawer; pages never assemble that UI.
6. While a drawer is open, the browser publishes the schema, complete document
   and optimistic-lock revision to a short-lived Manager memory channel. The
   FactorTester CLI inspects, validates or atomically applies one complete JSON
   document. The browser acknowledges success only after the page Adapter has
   validated, imported, saved and rendered it.
7. Test assistance edits a ResearchConfiguration-shaped document whose
   `configuration` member is exactly the structure later frozen as
   `RunSpec.configuration`. RunSpec adds immutable identity and execution
   metadata; there is no second handwritten field mapping.
8. Page documents and applications are ephemeral, profile-scoped, authenticated,
   versioned, size-bounded, and independent of business ports. They are not a
   research record and are never written to the control database.
9. ADR-124 WebMCP and this CLI channel retain separate transports but share the
   same principle: registered documents, ordinary validation, and no
   backend or DOM bypass.

## Consequences

- Reload and memory reclamation no longer require retaining whole page DOM.
- Pages must register non-native widgets explicitly; ordinary controls retain
  the existing generic snapshot fallback.
- Agent assistance cannot write a document that the active page schema and
  Adapter do not accept, and stale revisions cannot overwrite newer edits.
- Multiple assisted tabs can safely share one Profile Agent without a hidden
  drawer terminating another tab's conversation.
