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
- `jobs/`: job lists, progress, detail fields, artifacts, and viewers;
  `jobs/list-format.js` is the pure list/detail formatting seam (status,
  identity, artifact cells, and shared scalar helpers), while `jobs/jobs.js`
  owns scope state, pagination, and navigation
- `catalog/`: source catalog, products, factors, product groups, and catalog
  details; `catalog/source-list.js` owns the data-source page and receives the
  shared catalog loading seam from `catalog/products.js`
- `workbench/`: test settings, factor selection state, templates, and
  submission; `workbench/factor-selection.js` owns candidate identity and
  selection projection so the UI builder does not duplicate state logic;
  `workbench/factor-family-picker.js` is the searchable public/local family
  catalog seam, with the public side sourced from the same Manager catalog as
  the factor-library page and the local side supplied only by the embedded
  client's frozen Git-revision bridge; `workbench/test-run-batch.js` is the single IC/backtest submission
  seam and retains each frozen RunSpec and Job link in the originating page;
  `workbench/tab-list-chip.js` is loaded only with the backtest strategy-list
  group, not with the shared settings shell
- `profile/` and `settings/`: profile and account/server settings pages
- `app/`: routing, authentication, tab sessions, shell lifecycle, and the
  final application coordinator (`app/coordinator.js`)
- `styles/`: global shell and domain stylesheets; `styles/app.css` is the
  current shared shell stylesheet, while `styles/report.css` contains report
  presentation rules. Output viewers are split under `styles/outputs/`:
  `artifacts.css` owns generic/IC artifact presentation and
  `backtest-results.css` owns backtest, snapshot, and factor-series results.

The workbench has four user-visible container contracts, and no additional
domain-specific top-level container is needed:

- `FTTabChipContent` is the scalar settings container. It owns tab buttons,
  hidden content panels, optional descriptions, and optional action buttons.
- `FTTabListChip` is optional and is used only when a surface contains a
  selectable/repeated list. Group strategies, Long-Short strategies, and a
  future custom-strategy list all reuse this shell; the rows and actions come
  from backend surface declarations.
- `runspec-run` is the common first settings tab for task identity, submitter,
  retention, output requests, and run diagnostics. It is a content adapter
  mounted inside `FTTabChipContent`, not another tab bar.
- `result` is the result/output container for summaries, tables, charts, and
  artifacts after a run. It is not a settings surface.

IC and factor-evaluation use one settings instance; backtest adds one optional
`FTTabListChip` instance for strategy surfaces. Group override tabs use the
same `FTTabChipContent` interface inside that editor rather than defining a
parallel tab bar. Field rows, overlays, tables, code blocks, and source
previews are internal adapters/primitives, not additional user-visible
container contracts. New test modules must provide manifest-backed items and
actions to these seams; they must not introduce another tab/chip/content DOM
contract or module-local tab CSS.

Backtest custom strategies remain Job inputs rather than group records:
`run_inputs` owns the registered source/spec/dependency upload controls, while
the inspection response supplies the entrypoint, callbacks, and requirements
shown in the preview and retained in Job detail. A future strategy-list view
must reuse this input adapter and state; it must not create a second source
store or silently turn uploaded code into a group.

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

Within every loaded group the IIFE order is intentional:

```text
core → report/research/jobs/catalog/workbench/profile/settings → app

The production shell does not eagerly execute that whole graph. It executes
only `initial_groups: ["core", "app"]`; `FTStaticLoader.ensureRoute()` loads
the route group after authentication, and a tester then requests
`workbench-settings` while its backend manifest and workspace projection are
being fetched. This distinction is important: a tab or container being
visible is not permission to download every implementation behind all other
tabs. The manifest group, not a DOM `display:none`/collapse state, is the code
loading boundary.
```

The manager renders `research.html` from this manifest. Do not change a script
path or load order without running the manifest and static-shell tests. A
future ES-module loader may replace this contract, but until then an implicit
global must not be read before the group that defines it has loaded.

The manager also refuses to serve an unlisted Web-root `.js` or `.css` asset at
runtime. This is intentional: an old URL must fail visibly after a module is
moved, rather than silently reintroducing a stale copy beside the new module.
Package-owned KaTeX fonts and other non-code assets remain available through
their separate static-resource tree.

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
the explicit 404-only full-projection fallback, the active chapter metadata
window, and asset/resource indexes and URLs. Chapter sidecars replace that
window rather than accumulating metadata from every visited chapter; the
renderer separately keeps only a bounded content LRU and reselects the
metadata window on a cache hit. `report/report-entry.js` only coordinates the
source with the renderer; it must not recreate local/remote paths or merge
chapter metadata itself. A new source adapter belongs behind this seam and
must preserve the same `load`, `loadChapter`, `setChapterMetadata`,
`localResourcePath`, and `reportAssetPath` interface.

Local report chapters carry asset metadata and a content-addressed `asset_id`,
not image bytes. `reportAssetPath` resolves that id through the owner-scoped
`/api/client/research/<local_ref>/assets/<asset_id>` endpoint; the client reads
and hash-checks one asset only when the image becomes visible. Published reports
continue to use the mirrored public asset endpoint. This keeps local and shared
reports on the same renderer contract without putting every SVG or PNG into the
chapter JSON response.

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

The workbench loading groups are also semantic boundaries: `workbench-core`
contains only the route coordinator, compiler, state and generic lazy-code
seams. `workbench-settings` contains the shared tab/chip settings renderer and
is fetched when a tester route has authenticated and received its backend
manifest; it is not part of the initial shell and does not include any catalog,
strategy-list, chart, or run-submission implementation. `workbench-run`
contains run-spec/submit/result code and is requested only when the run surface
is materialized. The backtest `FTTabListChip` and strategy editors belong to
`workbench-backtest`, which is loaded only after the strategy-list tab is
opened, rather than being pulled into every IC or factor-evaluation page.
IC grid controls, factor-role bindings, and product override editors each live
in a separate control group and are loaded once when a field using that
registered control is first rendered; `test-control-loader.js` coalesces
multiple fields requesting the same group and batches their repaint callbacks.
Factor, product, and template code remain separate. A tab-specific group is
requested only when its registered adapter is opened. The same rule applies to
jobs: the `jobs` route loads only the list formatter, progress and list
controller (about 20 KiB); `job-detail` adds charts, artifact viewers, result
models and input/configuration pages only when a concrete task is opened. The
formatter is loaded before the list controller, so the detail page can reuse
the stable helper seam without recreating formatting logic.

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

The Swift host keeps only lightweight route, branch, and selection state for
each open tab. WebViews are retained in a bounded four-tab LRU cache so
switching between a small number of reports is instant without allowing an
unbounded WebContent process count. Eviction removes message handlers,
user-scripts, delegates, and the native view; returning to the tab recreates
the WebView from the same route and session state.

Link routing is deliberately split by source semantics. In an embedded Web
report, typed `factortester://...` references and ordinary `http(s)` references
call the native `researchReference` seam; Swift turns them into its own tab and
uses the same Web tab template for the detail page. Standalone Web keeps
ordinary `http(s)` links as external browser links. Published local resources
(`factortester-local://...`) are also offered to the native seam in an embedded
report as the typed `file` reference. The generic file detail page then uses
the owner-scoped local endpoint (or the public publication endpoint) to show
metadata and download the bounded resource. Standalone Web retains the direct
download action. Arbitrary `file://` paths and relative paths still use the
existing local-resource callback and are never converted into an object tab.
The rich-text parser preserves nested square brackets in labels before this
routing decision; it must never infer a typed object from the visible label.

The report API has three independent data layers. `/index` is metadata only;
`/chapters/<id>?metadata=1` returns the chapter hierarchy, bindings and
content/resource metadata but strips every body and payload; the full
`/chapters/<id>` form remains available for the compatibility boundary. A
visible component is then fetched through
`/chapters/<chapter-id>/components/<component-id>`. Published reports persist a
hash-checked chapter sidecar at upload time, while local reports use the
authoring tree's `load_report_index`, `load_chapter_snapshot` and
`load_component_snapshot` for the same contract. The browser then defers body,
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
