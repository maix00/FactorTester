# React page migration ledger

Status is deliberately explicit. A native landing page with a legacy bridge is
not the same as a fully migrated detail/editor route.

## Top-level

| Route | Status |
| --- | --- |
| `/research` | native landing; detail editor bridge |
| `/jobs` | native list; native detail + run configuration drawer; input still legacy |
| `/backtest` | native strategy-family landing; workbench bridge |
| `/products` | native catalog with products/groups/factors/families/sets/strategies/sources/categories tabs; editors bridge |
| `/settings` | native overlay; language/workspace/account/server/control-database/federation/devices/quota/updates read natively |
| `/account` | native |

## Hidden/legacy routes still to migrate

```text
/researches/:id
/research reports
/reports/:id
/jobs/:port/:id/input/:name
/ic
/factor-series
/factor-families/:id, /factor-sets/:id
/product-category/:id
/products/:id, /product-reference/:kind/:id
/profiles, /profiles/:id
/mihomo
/docs/:slug
```

## Rule

Do not remove the legacy route until its native replacement covers read, write,
permissions, error/empty/loading states, and deep links. Once covered, remove
the bridge in the same change and update this ledger.
