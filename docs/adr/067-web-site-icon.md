# ADR 067: Give Web surfaces one site icon

## Status

Accepted.

## Context

The Flask service and Manager Web shell are separate HTTP surfaces, and
neither exposed a FactorTester site identity to browsers. The module manifest
and its card icons describe navigation entries; they are not the site's
favicon contract. The native AppIcon is also a packaged application asset,
not a browser dependency.

## Decision

1. Keep one lightweight, standalone `static/favicon.svg` as the Web site
   identity. It uses the FactorTester brand palette and trend motif without
   loading native image assets, SF Symbols, fonts, or module metadata.
2. Both Flask and Manager expose the same bytes at `/favicon.svg` and the
   browser-default compatibility path `/favicon.ico`.
3. The legacy home and Manager shell declare the SVG explicitly with
   `rel="icon"`; other pages can still use the public compatibility path.
4. Module-card icons, `sfSymbol`, the module manifest, and Swift AppIcon
   ownership remain independent contracts.

## Verification

Contract tests compare both endpoints with the checked-in SVG and assert that
the two Web entry documents declare the site icon.
