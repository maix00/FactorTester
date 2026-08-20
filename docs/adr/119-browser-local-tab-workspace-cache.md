# ADR 119: Browser-local bounded tab workspace cache

## Status

Accepted

## Context

FactorTester uses persistent left-rail tabs as independent workspaces. Users
expect a tab to retain its route, draft values, overlays and reading position
after visiting another tab, refreshing, or signing out and back into the same
Manager from the same browser. Keeping every rendered DOM tree indefinitely,
however, makes long sessions consume unbounded memory. Synchronizing transient
UI state through PostgreSQL or Manager federation would also put presentation
state into server communication paths without improving test or research data.

## Decision

Use three browser-local tiers, scoped by Manager origin and authenticated
username:

1. Keep at most three recently used inactive/active DOM views hot using a
   deterministic least-recently-used policy.
2. Coldify older views into small control and scroll snapshots in
   `sessionStorage`; restore by stable semantic control keys after re-rendering.
3. Persist the tab registry and a versioned durable projection in
   `localStorage`. Test pages persist only user-authored draft state, not loaded
   catalogs, results, promises, DOM nodes, credentials, or server responses.

The active page is checkpointed without detaching its DOM after meaningful
draft changes and on `visibilitychange`/`pagehide`. `unload` is not used.
Closing a tab removes its durable session. A schema mismatch or malformed
payload discards the local snapshot and safely reloads the route.

The window scroll position is always retained. Independent long-lived table,
tree, report and analysis scroll containers opt in with
`data-ft-scroll-state`. Ephemeral popovers and dropdown menus do not persist
their scroll position.

Research reports additionally retain the selected chapter and each report
component's disclosure state by stable `component_id`. A report with no prior
browser-local reading state opens at the bottom only after its initial lazy
chapter has finished rendering; subsequent visits restore the saved reading
position instead.

This state does not synchronize between Managers, browsers, or devices. On
restore, the page revalidates authoritative account, catalog, task and artifact
objects through its normal lazy APIs. Authentication changes invalidate cached
DOM while retaining each account's separately namespaced workspace.

## Consequences

- Refresh and same-browser re-login restore all open tabs and the last active
  tab without making PostgreSQL or federation part of the restoration path.
- Long sessions retain only a bounded number of DOM trees; cold tabs pay the
  normal lazy render cost when reopened.
- UI state is intentionally unavailable on a different device or Manager.
- Adding a durable page type requires an explicit serializable projection and
  schema-version handling; arbitrary application state must not be serialized.
