# Web renderer architecture

The renderer is a static, browser-compatible application. It currently uses
small IIFE modules instead of ES modules so the same files can be served by
the manager and embedded by the macOS client. `module-manifest.json` is the
single source of truth for the script order and semantic module groups.

## Module groups

- `core/`: translation, symbols, shared DOM controls, and JSON/table helpers
- `report/`: report parsing, component presentation, chapter navigation, and
  the shared lazy-loading runtime
- `research/`: research references, graph browsing, and research lists; the
  list coordinator stays in `research/workspaces.js`, while
  `research/local.js` owns the client-download/local projection page and
  `research/shared.js` owns publication visibility and owned-report source
  resolution
- `jobs/`: job lists, progress, detail fields, artifacts, and viewers
- `catalog/`: source catalog, products, factors, product groups, and catalog
  details; `catalog/source-list.js` owns the data-source page and receives the
  shared catalog loading seam from `catalog/products.js`
- `workbench/`: test settings, factor selection state, templates, and
  submission; `workbench/factor-selection.js` owns candidate identity and
  selection projection so the UI builder does not duplicate state logic
- `profile/` and `settings/`: profile and account/server settings pages
- `app/`: routing, authentication, tab sessions, shell lifecycle, and the
  final application coordinator (`app/coordinator.js`)
- `styles/`: global shell and domain stylesheets; `styles/app.css` is the
  current shared shell stylesheet, while `styles/report.css` contains report
  presentation rules

The groups are architectural boundaries, not separate pages. A module should
export one narrow `window.FT*` seam and consume shared behavior through
`FTUI` or an explicitly named group seam. New files must be added to the
manifest and to the matching group exactly once.

The app group has one deliberate orchestration seam: `app/route-dispatch.js`
owns route-to-handler dispatch, while `app/coordinator.js` owns lifecycle, context
construction, and the handler closures. Route guards stay in the dispatch
seam, so adding a page does not grow another protected-route branch inside
the shell. The route-dispatch fixture is the contract for this split.

## Loading contract

The current IIFE order is intentional:

```text
core → report → research/jobs/catalog/workbench/profile/settings → app
```

The manager renders `research.html` from this manifest. Do not change a script
path or load order without running the manifest and static-shell tests. A
future ES-module loader may replace this contract, but until then an implicit
global must not be read before the group that defines it has loaded.

## Boundaries and file size

Report parsing and report presentation share a rich-text seam, but parsing
helpers should not be copied into component views. The data-only component
index and chapter-root projection live in `report/tree.js`; DOM code must use
that seam instead of rebuilding parent maps. The bounded chapter LRU lives in
`report/chapter-cache.js`, while `report/lazy-runtime.js` owns the shared
intersection observer. Tables and JSON code blocks belong to `FTUI`/the shared
report helpers rather than individual job or catalog pages.

`report/source.js` is the report-source seam. It owns the distinction between
the local authoring source and the published shared source: index loading,
the explicit 404-only full-projection fallback, chapter metadata merging, and
asset/resource indexes and URLs. `report/report-entry.js` only coordinates the
source with the renderer; it must not recreate local/remote paths or merge
chapter metadata itself. A new source adapter belongs behind this seam and
must preserve the same `load`, `loadChapter`, `localResourcePath`, and
`reportAssetPath` interface.

`report/component-view.js` is the single component-to-DOM seam. A visible
title on a content component creates the same default-open disclosure used by
ordinary sections; structural labels such as “正文” or “表格” never become
headings. Disclosure toggles capture the summary's viewport anchor and clamp
the corrected scroll position to the new document height. This is generic and
handles a bottom-of-report collapse without a chapter-specific scroll fix.
The lazy-renderer fixture covers deferred bodies, nested children, anchor
compensation, and the bottom-boundary clamp.

The manifest enforces a 400-line production-script limit and a 500-line
stylesheet limit. These are split points, not a reason to create shallow
one-function files. When a module approaches its limit, extract a cohesive
responsibility with a small interface (for example a viewer adapter, parser,
or navigation seam), then add a contract test for that interface.

## Embedded Swift navigation

The Web research shell remains the owner of the `local/shared/graph` switcher.
When embedded, a section click emits only `/research?section=<id>` through the
`researchNavigation` bridge; Swift stores that key in the lightweight tab
session without remounting the WebView. A report path (`/research/<ref>`) is a
different contract and opens a dedicated Swift-owned Web tab. Typed report
references use the same Web tab template, with the route selected by the
reference catalog; the old native reference-tab fallback is intentionally not
part of the production route.

The generic `/reference` page also consumes that catalog seam. It renders a
semantic header with the same symbol and tone for evidence, factor/factor-set,
Profile, product/contract, and uncategorized references. The page may show a
stable reference when its detail endpoint is unavailable; it must not infer a
different object kind from the label or target text. RunSpec references accept
the canonical `runspec:` form and the two serialized aliases used by existing
report records, all resolving to the same owner-scoped JSON endpoint.

Local report resources are selected only when the server marks a publication
as owned by the current client and the local report index has the same
`report_id`. Titles or matching strings never select a local snapshot.

Link routing is deliberately split by source semantics. In an embedded Web
report, typed `factortester://...` references and ordinary `http(s)` references
call the native `researchReference` seam; Swift turns them into its own tab and
uses the same Web tab template for the detail page. Standalone Web keeps
ordinary `http(s)` links as external browser links. `factortester-local://`,
`file://`, report attachments, and relative owned resources call
`openLocalResource` instead: they are file actions (download/default-app open),
not object references, so they must not be converted into object tabs. The
rich-text parser preserves nested square brackets in labels before this routing
decision; it must never infer a typed object from the visible label.

The report API has two independent data layers. `/index` is metadata only;
published reports persist a hash-checked chapter sidecar at upload time, and
`/chapters/<id>` reads that sidecar instead of decoding the complete mirror.
Local reports use the authoring tree's `load_report_index` and
`load_chapter_snapshot` for the same contract. The browser then defers body,
table, image, and nested-child DOM work through `lazy-runtime.js`. Do not add
full-projection reads to list or index routes; a sidecar rebuild is only an
interrupted-publication repair path and must be followed by an atomic write.

## Verification

Run the manifest, shell, report-lazy, and client-app tests after changing the
tree. The test checks that every production asset is present, listed once,
loaded in the declared order, and within the size budget. The current focused
regression command is:

```text
conda run --no-capture-output -n GTHT python -m pytest --confcutdir=tests/scripts -q \
  tests/scripts/test_worktree_manager_web_manifest.py \
  tests/scripts/test_report_lazy_rendering.py \
  tests/scripts/test_web_reference_page.py \
  tests/scripts/test_worktree_manager_client_app.py \
  tests/scripts/test_worktree_flask_manager.py
```

The macOS reader contract is tested separately with the `ClientTabSelection`
and `ResearchDocumentTextBlock` suites. Swift remains a tab/router host for
the Web report; it must not grow a second production report renderer.
