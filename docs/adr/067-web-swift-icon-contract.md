# ADR 067: Share semantic module icons between Web and Swift

## Status

Accepted.

## Context

The module manifest at `static/config/modules.json` is consumed by the legacy
Web home, Manager Web, and the macOS client. It already carries both a legacy
`icon` value and the native semantic `sfSymbol` value. The legacy home was
still rendering the former directly, so the server operations module could
appear as `OPS` while Manager Web and Swift used `server.rack`.

Web browsers cannot render SF Symbols or load the Swift AppIcon asset catalog.
Manager Web therefore owns an inline SVG renderer in
`server/manager/web/core/icons.js`; the legacy home uses a small adapter in
`static/js/base.js`. Both adapters consume the same semantic key and provide a
deterministic link-shaped fallback for an unknown key.

## Decision

1. `sfSymbol` is the cross-client semantic identity for a module. The
   `server_operations` module uses `server.rack` everywhere.
2. Swift continues to render the semantic key with
   `Image(systemName:)`. Web clients render platform-specific inline SVG; they
   do not copy SF Symbols fonts, Swift images, or `Assets.xcassets`.
3. The legacy `icon` field remains only as a compatibility input when an old
   manifest entry has no `sfSymbol`. It is never the preferred renderer input.
4. Unknown or missing SVG shapes retain the semantic `data-symbol` and render
   the stable `link` shape with a fallback marker, so navigation remains
   visible and inspectable.
5. Product branding, favicon, and the Swift AppIcon remain separate from
   module navigation icons.

## Verification

The Web contract tests assert that the legacy home loads the adapter, prefers
`sfSymbol`, and emits a deterministic fallback. Manager tests continue to
verify the manifest/API symbol contract and the `server.rack` registry entry.
