# ADR 124: WebMCP uses the visible browser action surface

## Status

Accepted

## Context

FactorTester agents can use the research CLI, while people can also use the
Manager Web application. The Web application contains additional account,
device and subordinate-management operations that intentionally do not belong
to the research CLI. Duplicating every backend route as a browser tool would
create another authorization and workflow surface, and would let an agent
change server state without sharing the form state visible to the user.

## Decision

1. The Web shell registers a small, stable set of imperative WebMCP tools for
   capability discovery, route navigation, visible-control inspection, form
   filling and explicit action activation.
2. Capability discovery maps every public `factortester` CLI command family to
   one or more Web surfaces and separately identifies Web-only management
   surfaces.
3. Form and action identifiers are ephemeral and issued only for visible
   controls in the active page and its open modal dialogs. An agent must inspect
   again after rendering or submitting a surface.
4. WebMCP changes controls and dispatches their ordinary input/change/click
   events. It does not call business APIs directly. Existing page validation,
   session credentials, role checks and backend authorization remain the
   authority.
5. Reading is bounded and marked as potentially untrusted. Password values are
   never returned. Action activation requires an explicit `confirmed: true`,
   and cross-origin links cannot be activated.
6. Browsers without `document.modelContext` keep the normal application with
   no polyfill or additional dependency.

## Consequences

- Agents and users operate one shared, inspectable Web state, including dynamic
  IC/backtest forms and Web-only subordinate management.
- New pages are automatically operable when they use semantic controls; adding
  a top-level capability mapping makes them easier for agents to discover.
- The adapter cannot bypass a disabled or hidden control. Complex custom
  widgets remain a sequence of visible actions, matching ordinary UI use.
- WebMCP remains an experimental browser capability, while the site continues
  to work unchanged in unsupported browsers and embedded WebKit clients.
