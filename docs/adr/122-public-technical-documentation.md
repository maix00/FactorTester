# ADR 122: Public technical documentation is curated product content

## Status

Accepted.

## Context

FactorTester previously treated technical documentation as a set of Flask
templates plus a runtime AST browser over `tools/`. That mixed three different
concerns: teaching users how to operate the platform, explaining the system's
implementation architecture, and exposing source text. It also made document
availability depend on repository layout and runtime scanning.

## Decision

The public technical-documentation module has two equal responsibilities:

1. explain how to use FactorTester;
2. explain how a feature is implemented and where its canonical code entry
   points live, without displaying source code.

Published content lives under `product_docs/` and is explicitly listed in its
manifest. Internal engineering records under `docs/` are not implicitly
public. Implementation pages describe responsibility, flow, domain objects,
canonical paths, boundaries, lifecycle, permissions and extension points.

Manager 7998 owns the read API and renders the reader inside the existing Web
Shell. The macOS client embeds that same route; navigation ownership remains
with the surrounding client tab system. Documentation is readable without an
account.

`markdown-it-py` is used only as the restricted Markdown parser and `nh3`
applies the rendered-HTML tag, attribute and URL allowlist. Raw HTML is
disabled before sanitization, every heading requires an explicit stable
anchor, and source paths must remain inside the manifested public root. Search
and navigation are product-owned so a third-party documentation shell cannot
create a second routing or authentication system.

## Consequences

- Adding a page requires a manifest entry and stable heading anchors.
- Runtime source-tree traversal and source display are not documentation
  features.
- Code paths in implementation pages are navigation clues, not public API or
  permission to expose the files.
- User guides and implementation maps can cross-link and evolve together while
  remaining separate from internal ADRs and maintenance instructions.
