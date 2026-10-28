# Design QA — library and configuration continuation (#445)

final result: passed

Scope: this iteration's shared page chrome, library table/detail layout, IC input
rows, settings cleanup and mobile detail/create navigation. This is not full
acceptance of every React migration feature or a real Nautilus Job.

## Targets and evidence

- Selected library reference: generated `exec-9be6540e-0f63-40a4-af71-140a97efaed2.png`.
- Selected Test reference: generated `exec-f9687cb0-797e-443a-99b8-1a48d77d249f.png`.
- Desktop viewport: 1536 × 1024; mobile: 390 × 844.
- Comparison board: `/Users/maxdeux/.codex/visualizations/2026/10/27/tr-workspace-v2/reference-comparison.png`.
- Final browser captures in that directory: `library-zh-CN.png`,
  `library-en-US.png`, `mobile-factor.png`, `settings-desktop.png`,
  `in-app-library.png`.
- Fixture data differs from the concept's illustrative factor names, row count,
  timestamps and formulas. Missing values remain absent; no synthetic versions
  or performance numbers are inserted into application data.
- Account avatars and extra explanatory copy in the generated concept were
  intentionally excluded per the user's explicit instructions.

## Iteration findings and fixes

1. P2: header padding added 48px to the intended minimum height. Fixed with
   border-box sizing and recaptured the page.
2. P2: the library used mixed domain cards and several bespoke overlays. Replaced
   with domain tabs, shared filters/table, inline desktop detail and responsive
   shared detail pages. Source/ref validation entry remains available.
3. P2: factor formulas and identity JSON competed as primary content. Formula
   uses the repository KaTeX asset; frozen identity is collapsed. Registered
   parameter metadata renders with the shared table when provided.
4. P2: mobile table columns overflowed. Secondary metadata moves into the name
   cell; extra columns hide at narrow breakpoints. Detail and creation have
   history-backed return behavior.
5. P2: IC controls used a separate vertical form, exposed unsupported property
   insertion, and lacked unique control IDs. Top-level inputs now use the same
   row rhythm, metadata-driven controls and per-instance IDs. Typed authoring
   validates scale-aware and explicit horizon metadata.
6. P2: hidden DockView content remained in the accessibility tree, and parent
   tab descriptions stayed Chinese in English. Hidden instances are inert and
   aria-hidden; tab API titles update with locale. In-app browser verified.
7. P2: library detail said 'Run detail'. Changed to generic localized 'Details'.
8. P3: data-dependent panel length and exact system font rasterization differ
   from the generated reference. No compensating fake content was added.

## Verification

- TypeScript and 25 focused frontend tests pass.
- Seven focused Python tests pass (metadata/typed IC plus frontend release gate).
- Chrome fixture browser: zh/en library selection/filtering/formulas, localized
  pagination; mobile details/new factor/system back; no page errors.
- Codex in-app browser: actual selected library formula, independent Test tab,
  workspace/type dropdowns and IC fields; no error console entries.
- Browser preview uses isolated local fixture data and makes no production writes.

## Remaining work outside this pass

Structured result charts/plugins, complete version editing/recovery flows,
authenticated local execution acceptance and broker/session management remain
tracked by #445. The Research graph editor is still embedded from the existing
route; it has not been reimplemented or presented as fully migrated.

## Legacy parity pass

The subsequent inventory is in MIGRATION.md: 114 first-pass feature items and
all 40 legacy route-dispatch branches. Its status labels distinguish native
controls from embedded routes, generic JSON displays and absent functionality.

This pass adds cursor/account scopes to Jobs; shared table cursor controls;
mobile source summaries and a full-width scope selector; dedicated strategy
revision/source/edit/sharing controls; and the legacy trading status surface.
Desktop and 390 × 844 in-app browser interactions were checked using an isolated
HTTP fixture. Source requests before activation: zero. A historical source read
used its selected revision; a remote Job kept server_id and port. Browser error
logs were empty. Mobile viewport overrides were reset after testing.

Evidence: `/Users/maxdeux/.codex/visualizations/2026/10/27/tr-parity/desktop-jobs.png`
and `mobile-jobs.png`. These are fixture UI checks, not actual production Jobs,
source inspection, authorization or broker execution acceptance. UI scope is
passed; the whole migration remains incomplete per MIGRATION.md.

## Execution topology / #448 (2026-10-28)

User correction: preserve the existing app design system and introduce three
ordered top-level tabs: Execution → Configuration → Results. Execution inputs
must not remain as a global panel above both Configuration and Results. A
manually selected node supplies test types; automatic matching uses compatible
online candidates in the selected Manager and freezes the actual selection at
preview/submission. Switching tabs preserves inputs; switching Manager makes old
preview invalid. Results carry Manager/node identity and read through control
APIs, without requiring an execution business-port listener.

Applied frontend-app-builder's existing-design-system exception: no new visual
concept or generated marketing assets. Existing AntD tabs/selects, app typography,
white surfaces, 14px controls, blue accent and responsive setting rows remain the
reference. Compared copy, tab order/container hierarchy, text scale, spacing,
control/border treatment and 390px stacking against the existing app surface.
No new card grid or alternative design tokens. The JSON editor is configuration
JSON, not the frozen RunSpec or the resolved ExecutionPlan.

Browser plugin not available. GTHT Playwright with installed Chrome checked the
actual React components using isolated HTTP catalog/config fixtures derived from
the real native Job; both 1440×1000 Chinese and 390×844 English render, Manager
switch, automatic product/Bar input selection, tab switching/preserved dates,
and node-limited test types passed, no page errors or picker horizontal overflow.
`view_image` inspected both final captures. Fixtures exercise UI, not browser→
production submission. Real Keycloak/peer HTTP→native Celery execution and report
acceptance are separately recorded in ADR188 and verify_remote_node_job receipts.
The compiled native RunSpec fixture has no authoring strategy bindings and its
Decimal initial balance differs from editor input schema: it is deliberately not
claimed as a valid editable strategy draft or browser submission acceptance.

Captures: `/Users/maxdeux/.codex/visualizations/2026/10/28/execution-topology/zh-CN-1440.png`
and `en-US-390.png`. No temporary QA entrypoint is shipped. Local/public deployment,
complete Keycloak administration UI and removal of embedded legacy routes remain
separate work; this pass does not declare the whole frontend migration complete.
