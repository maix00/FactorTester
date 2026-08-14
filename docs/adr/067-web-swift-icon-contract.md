# ADR 067: Share semantic module icons between Web and Swift

## Status

Accepted.

## Context

The FactorTester module registry is already shared by the legacy Web home and
the Swift client at `static/config/modules.json`. A module has both an
`icon` field and an `sfSymbol` field. The Swift client renders `sfSymbol` with
`Image(systemName:)`, while the legacy Web home currently renders `icon` as
plain text. This makes the server operations module appear as `OPS` on that
Web surface even though the Swift client and the Manager Web shell identify it
as `server.rack`.

The Manager Web shell cannot load the SF Symbols font or the Swift asset
catalog. It already keeps a small semantic-symbol-to-inline-SVG registry in
`server/manager/web/core/icons.js`. The native app icon in
`apple/Resources/Shared/Assets.xcassets` is a product/launcher identity, not a
module icon and must not become a server-side asset dependency.

## Decision

1. Reuse the semantic icon identity across clients, not the native image file.
   `sfSymbol` is the cross-client contract; `server.rack` is the canonical
   symbol for `server_operations`, the Manager server shortcut, and server
   settings. The contract promises semantic and optical parity, not identical
   pixels across SwiftUI and browser rendering.
2. Keep `static/config/modules.json` as the sole module registration source.
   New modules must provide a supported `sfSymbol`. The existing `icon` field
   remains a legacy text/emoji fallback for older Web clients and is not the
   preferred rendering path.
3. The Web renderer resolves a module's `sfSymbol` first and renders it from
   the shared semantic SVG registry. The legacy Web home must be migrated to
   this same resolver instead of adding a server-specific `OPS` glyph or a
   second hard-coded `server.rack` drawing. The Manager shell and the legacy
   home may have small DOM adapters, but they must consume the same registry.
4. Swift continues to render `Image(systemName: module.sfSymbol)` and uses
   `icon` only when a server sends no usable symbol. Hard-coded server shortcut
   icons should be replaced by the module's registry entry when that shortcut
   is represented as a module.
5. The FactorTester launcher/favicon remains a separate brand-asset contract.
   It must not be replaced with `server.rack`, and Web must not copy the Swift
   app icon or `Assets.xcassets` into its runtime. This preserves the asset
   boundary in ADR 054 and keeps a server-management symbol from being
   mistaken for the product identity.

## Contract and rollout

The implementation should proceed in this order:

1. Add a contract test that loads `static/config/modules.json` and verifies
   `server_operations.sfSymbol == "server.rack"`, plus a Web-renderer test
   proving `server.rack` is a registered SVG symbol rather than the generic
   fallback.
2. Move the Web-home icon rendering behind the shared resolver. It should
   prefer `sfSymbol`, use the legacy `icon` only for unsupported/missing
   symbols, and preserve the existing authentication and role filtering.
3. Keep the Manager `/api/modules` projection aligned with the same symbol
   contract and remove duplicated server icon literals from UI entry points as
   they are migrated.
4. After all supported clients consume `sfSymbol`, deprecate the Web-facing
   text/emoji interpretation of `icon`; remove it only in a separately
   versioned registry migration after older clients are no longer supported.

## Verification

- The shared manifest, Manager module projection, and Swift decoder all expose
  `server.rack` for the server module.
- The legacy Web home, Manager Web shell, and Swift home show the same server
  symbol for the same module.
- An unknown or unavailable symbol has a deterministic accessible fallback and
  does not break module navigation.
- The Web bundle does not load SF Symbols fonts, Swift asset-catalog files, or
  native launcher PNGs.
- Focused manifest, Web shell, server module API, and Swift module-decoding
  tests pass; visual review covers the card, sidebar, tab, and settings sizes.

## Consequences

- One semantic key keeps Web and Swift navigation consistent while allowing
  each platform to use its native rendering mechanism.
- Browser SVG paths need deliberate maintenance when a new symbol is added;
  an unknown symbol must not silently become a misleading server icon.
- The old Web `icon` field cannot be removed immediately because it is the
  compatibility path for older clients.
- Product identity and server-management semantics stay distinct, avoiding a
  favicon/app-icon change when only a module icon is being redesigned.
