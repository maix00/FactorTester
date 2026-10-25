# ADR 176: Desktop Ant Design, mobile component boundary

Status: accepted for the React shell migration.

## Decision

Desktop data-heavy surfaces use Ant Design `Select`, `TreeSelect` and `Table`
through FactorTester adapters (`FTDataTable`, `FTMultiSelectFilter`). Adapters
own server pagination, sorting, filtering and theme tokens; pages do not call
Ant Design Table props directly.

Mobile keeps Ionic for the application shell and bottom navigation. Data lists
use compact cards/filter sheets; desktop tables are not rendered at phone width.
For a future mobile form/table package, evaluate Ant Design Mobile against the
existing Ionic components before adding a second runtime.

## Why not one component library everywhere

- Ant Design's desktop Table is not a mobile navigation or layout system.
- Ionic supplies tabs, safe-area handling and WebView semantics but not a
  server-paginated data table.
- Ant Design Mobile is a candidate for mobile forms/lists, but mixing it with
  Ionic without a page-level decision would duplicate styling and runtime.

## Rules

- One page uses one visual component family; do not nest desktop Ant Design
  tables inside an Ionic page at phone width.
- Server pagination is mandatory for Job/Run/report tables; never fetch the
  whole table merely to paginate in the browser.
- Research Report tables use the same `FTDataTable` adapter as Job tables when
  rendered in the React shell.
- Lightweight Charts remains independent of the form/table library.
