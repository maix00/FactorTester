# Web test module infrastructure

Every web test type is assembled by the shared test workbench. New test
modules must extend these contracts instead of rebuilding configuration tabs,
chip summaries, run submission, or result loading inside the module.

Start by adding the test type once to `core/test-type-registry.js`. Its
application key, route, title, aliases, and result viewer lazy group are then
shared by the configuration page, templates, Job restore actions, inline
results, and the dedicated Job page. Do not add a new chain of `if (kind ===
...)` checks in those callers.

## Configuration tabs and chips

- Declare settings tabs in the backend test-authoring manifest. The page shell
  is `workbench/test-settings.js`; individual test pages do not render a second
  tab bar.
- `workbench/tab-chip-content.js` owns the invariant that every mounted tab has
  a group in the chip row. Callers may provide richer value chips through
  `workbench/test-setting-chips.js`, but must not register fallback chips per
  page. Tabs backed only by a content adapter (for example product groups,
  categories, data sources, or factors) are still represented automatically.
- Add reusable tab bodies through `workbench/test-content-adapters.js` and the
  manifest's `content_adapter` / lazy-group declaration. Do not put catalog
  fetching or picker implementations in a test-type page.
- `+ 设置` controls which optional tabs are mounted. Persist mounted keys through
  the common `ui.<test-kind>.mounted_tabs` contract.

## Run and result surfaces

- Submission and inline task state are shared by `workbench/test-run-batch.js`,
  `workbench/test-run-progress.js`, and `workbench/test-run-results.js`.
- Register a domain result viewer in the `resultViewers` registry in
  `test-run-results.js`. The entry declares its lazy module group, expected
  global, and section factory. This makes completed results appear both on the
  configuration page and on the dedicated job page.
- The dedicated job page chooses the same lazy group through
  `jobs/result-viewers.js`. Keep both routes pointed at one domain viewer; do
  not create separate implementations.
- Domain viewers belong under `test-modules/<test-kind>/results/`, parallel to
  `backtest/results/` and `factor-evaluation/results/`.

## Lazy module dependencies

- Declare every runtime global in `module-manifest.json` through a group or
  group dependency. A script being present in the production bundle does not
  make its global available to a lazy route.
- Result viewers that request prices, contracts, artifact previews, or
  Highcharts should depend on `job-detail-previews`; this transitively supplies
  the common job shell, chart runtime, market-data client, and preview helpers.
- Never rely on another page having loaded a group earlier. Test a new browser
  session and a direct route to the target page.

## Async terminal states

Every loading surface must settle into exactly one of:

1. rendered content;
2. an explicit empty state; or
3. an error state containing the actionable reason.

Catch the outer async call as well as individual network requests. A missing
global or synchronous request-construction error can otherwise leave a loading
placeholder on screen forever.

## Required regression coverage

When adding a test type or a settings tab, verify:

- every mounted tab appears in the shared chip row, including adapter-only tabs;
- opening a chip activates the matching tab;
- the inline configuration-page result surface lazy-loads the domain viewer;
- the dedicated job page selects the same result viewer group;
- the result group includes all preview/runtime dependencies;
- success, empty result, request failure, and missing-runtime states terminate;
- a direct fresh-page load has no relevant console errors.

The fast JavaScript fixtures live in `tests/scripts/fixtures/`; manifest and
integration assertions live in `tests/scripts/test_worktree_manager_web_manifest.py`.
