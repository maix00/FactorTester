# ADR 017: Separate Product Classification from Series Variants

## Status

Accepted

## Decision

CategoryTree classifies financial Product identities only. Primary continuous,
secondary continuous, raw, adjusted/smoothed, index, and future curve choices are
represented by typed `ProductSeriesRef` values beneath a product in view-specific
trees.

The single-factor submission tree continues to return Products. The price-view
tree requests series children explicitly and sends `product_name` and
`series_variant` as separate API fields. A variant may resolve to a different
backing data series without creating another classified Product.

## Consequences

Adding a series no longer duplicates sector/session categories or changes factor
submission groups. Data sources can advertise only variants for which data exists,
and future index/month/curve variants can use the same reference contract.
