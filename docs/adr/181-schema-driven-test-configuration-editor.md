# ADR 181: Schema-driven test configuration editing

The TradeResearch React `/app` configuration surface uses one JSON text draft with RJSF AntD
field editing and an independently loaded Monaco desktop JSON editor. Mobile
uses the same fields and a plain JSON input. No new configuration store or
payload version is introduced. Existing owner scoping, revision checks and
server RunSpec freezing remain authoritative.

`tools.testers.settings.json_schema` projects the application registry to
draft-07 JSON Schema and a searchable insertion catalog. The authenticated
Manager authoring dispatcher serves `GET /api/test-authoring/configuration-schema`.
Metadata reads do not load workspace data, execute factor source or contact an
execution service. English falls back to stable registered keys where no
English field label exists.

Optional defaults are suggestions inserted only by an explicit add action.
Form edits change one JSON path and preserve extension data. Invalid JSON stays
in the text draft. A save uses the existing `PUT .../configuration` with
`expected_revision`; acknowledgment does not erase edits made during saving.
409 responses preserve the draft and prevent automatic overwrite. Workspace
switch/reload with dirty text requires confirmation.

Client Schema validation covers projected types and bounds; domain/source and
permission validation stay on the server. Inheritance defaults (including null
and registered textual defaults) are retained. Extension fields remain open.
The UI exposes strategy selection rather than the storage sections `shared`,
`analyses` and `ui`. Public strategy form fields come from the existing strategy
catalog's configuration contract; factor and product-group pickers appear only
as parameters of that strategy. User strategies pin their current revision and
carry their registered factor dependencies. Selected factors are fetched as
server-validated frozen records and retained in the saved dependency graph.
There is no separate outer factor picker. Unknown configuration data remains
available through JSON. Informational page prose and storage-path controls are
not displayed.

Preview and Run use the existing `/api/runs/preview` and `/api/runs` paths with
the saved workspace revision. Running requires a preview matching the current
workspace, revision and exact draft; editing or switching workspaces invalidates
that preview. The server still owns freezing and domain validation. The current
Run action requests backtest; other analysis execution controls and complete
`FieldRules` projection remain follow-up work.

Focused validation covers metadata, existing save/read, owner/revision scope,
draft preservation, React types and state/i18n tests. Local desktop/mobile
browser checks use fixture API data; they are not production/run acceptance.

## Desktop and mobile navigation

The desktop configuration page is a navigation/detail workspace, without a
parameter dialog or nested cards. Its rail lists configured strategies and
three presentation groups for registered runtime settings: data/time,
venues/matching, and fees/margin. Unknown registered tabs remain in an Other
group. This grouping changes no field definition or execution policy. Public
strategy parameters are edited on their strategy rather than repeated in the
outer settings. Other saved analysis payloads remain intact in JSON; the Run
action in this slice is still backtest-only.

Mobile uses history-backed detail pages (`tr_config`, `tr_item`, `tr_path`) and
retains the same parent draft while navigating back. Only discard confirmation
uses a dialog. A strategy/field/JSON detail has one bottom Save action. The
configuration route retains its workspace id; desktop JSON navigation selects
the corresponding AST node through the lazy editor's `revealPath` interface.

An in-flight factor hydration is scoped to the workspace and reuses an
immutable-ref request cache. Saving is disabled while dependencies load or a
strategy is incomplete. Editing a binding preserves its identity and order.
The source/factor details come from existing permission-scoped catalogs; no
new source registry or configuration authority is introduced.

The shared React AppTheme sets the light palette, control sizes and AntD
locale for both shells. Branding is TradeResearch in both languages, per the
latest user decision. Existing module routes are preserved, and navigation
accessible names are translated along with visible labels. The single
Settings entry replaces its duplicate. Desktop notifications are placed below
the workspace toolbar so save notices cannot intercept Run interactions.

The UI uses 52px navigation rows, 72px desktop parameter rows and 84px mobile
parameter rows to match the concept's rhythm. Required validation remains in
the Schema while decorative required marks are omitted. Generated concepts
and local fixture screenshots are visual references, not live-server or
Nautilus execution acceptance.
