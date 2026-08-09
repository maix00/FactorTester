# Web renderer architecture

The renderer is a static, browser-compatible application. It currently uses
small IIFE modules instead of ES modules so the same files can be served by
the manager and embedded by the macOS client. `module-manifest.json` is the
single source of truth for the script order and semantic module groups.

## Module groups

- `core/`: translation, symbols, shared DOM controls, and JSON/table helpers
- `report/`: report parsing, component presentation, chapter navigation, and
  the shared lazy-loading runtime
- `research/`: research references, graph browsing, and research lists
- `jobs/`: job lists, progress, detail fields, artifacts, and viewers
- `catalog/`: products, factors, product groups, and catalog details
- `workbench/`: test settings, factor selection, templates, and submission
- `profile/` and `settings/`: profile and account/server settings pages
- `app/`: routing, authentication, tab sessions, shell lifecycle, and the
  final application coordinator (`research.js`)

The groups are architectural boundaries, not separate pages. A module should
export one narrow `window.FT*` seam and consume shared behavior through
`FTUI` or an explicitly named group seam. New files must be added to the
manifest and to the matching group exactly once.

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
helpers should not be copied into component views. The lazy observer belongs
to `report/lazy-runtime.js` and is reused by all report components. Likewise,
tables and JSON code blocks belong to `FTUI`/the shared report helpers rather
than individual job or catalog pages.

The manifest enforces a 400-line production-script limit and a 500-line
stylesheet limit. These are split points, not a reason to create shallow
one-function files. When a module approaches its limit, extract a cohesive
responsibility with a small interface (for example a viewer adapter, parser,
or navigation seam), then add a contract test for that interface.

## Verification

Run the manifest, shell, report-lazy, and client-app tests after changing the
tree. The test checks that every production asset is present, listed once,
loaded in the declared order, and within the size budget.
