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
The first slice does not yet generate dynamic factor/product/strategy reference
pickers or apply all `FieldRules` in the generic form. JSON preserves access to
the complete document; Run preview/submission stays on the existing server path.

Focused validation covers metadata, existing save/read, owner/revision scope,
draft preservation, React types and state/i18n tests. Local desktop/mobile
browser checks use fixture API data; they are not production/run acceptance.
