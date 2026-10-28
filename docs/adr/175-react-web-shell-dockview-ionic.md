# ADR 175: One React web shell with desktop Dockview and mobile Ionic tabs

Status: proposed migration; existing IIFE pages remain the fallback.

Brand rule: the new shell is TradeResearch. FactorTester remains the name of the
factor-testing sub-capability and of compatibility aliases only; do not add new
user-visible FactorTester labels to React pages.

Visual rule: this is a shell/runtime migration, not a redesign. Reuse the
existing FactorTester tokens, typography, navigation density, spacing, chart
chrome and dark/light behavior. A page may move into React only after its
desktop, mobile and macOS WebView appearances match the current page.

## Decision

Use one React application and one React runtime for the web client.

- Desktop: React Router + Dockview React for the workspace, preserving the
  current FactorTester navigation and visual language.
- Mobile/PWA: React Router + Ionic React `IonTabs` for a narrow bottom
  navigation and a workspace/open-pages list.
- Charts: keep the vendored Lightweight Charts build; it renders only, while
  data, indicators and Job state stay in FactorTester APIs.
- Native later: Capacitor wraps the same web build; it does not fork pages.

The existing `web/chart-workbench` React package is the first consumer and must
eventually share the shell's React runtime instead of shipping a second runtime.

## Workspace rules

- A page is identified by a stable page ID and URL; layout serialization stores
  only page IDs, groups and positions, never business results.
- Dockview's `always` rendering is opt-in for pages that require retained DOM.
  Hidden chart pages pause subscriptions and drawing.
- Mobile uses the same page registry and recent/open-page list, but not the
  desktop split layout.
- Lazy-load routes; the mobile build must not include desktop-only modules.

## Client/server boundary

- Manager serves only Web/API assets needed by the selected branch and port.
- Desktop can add local data sources and connect a local Nautilus for
  backtest/paper/live.
- Mobile only calls a server; execution and data authority stay server-side.
- No duplicate page implementation or duplicate React runtime between manager,
  macOS WebView and chart workbench.

## Deployment rule

apt/pip/Docker and build caches are reused across releases. A new release
transfers only changed repository objects and the Nautilus submodule delta, and
compiles only affected artifacts. A failed release keeps the previous image.

## Migration order

1. Baseline routes, tab sessions, assets, startup and chart memory.
2. Add the React Router shell and page registry.
3. Move one real page (Job result or product chart) into Dockview.
4. Add Ionic tabs and the mobile open-page list.
5. Migrate routes with desktop/mobile/macOS viewport acceptance.
6. Add PWA/Capacitor and remove legacy IIFE pages only after parity.


## ADR hygiene

When a page or boundary changes, update the ADR that owns it. Mark superseded
sections explicitly instead of leaving contradictory instructions. Do not keep
an old "independent runtime" or "legacy page is authoritative" statement after
the replacement has passed parity.
