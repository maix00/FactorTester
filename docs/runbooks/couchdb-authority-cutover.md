# CouchDB authority cutover runbook

## Readiness

Run on both the intranet and public server:

```bash
python scripts/migrations/verify_couchdb_authority.py \
  --db /data/sqlite/unifieddata.sqlite \
  --couchdb-url http://admin:secret@factortester-couchdb:5984
```

Required:

```json
"ready": true
```

Current verified state:

```text
intranet: factors 89/89, heads 126/126, product_groups 11/11
public:   factors 126/126, heads 126/126, product_groups 15/15,
          research_reports 144
```

## Enable

```text
TRADERESEARCH_COUCHDB_AUTHORITY=1
FACTORTESTER_COUCHDB_URL=http://...
FACTORTESTER_COUCHDB_DB=ft_objects
```

This enables:

```text
product-group read/write
factor-family read/write
strategy entry/revision read/write
research-report read-through
```

## Monitor

```text
factor list count
product-group list count
strategy mine/public list
research report read
research report agent export
```

If any count drops, immediately unset the authority variable.

## Rollback

```text
TRADERESEARCH_COUCHDB_AUTHORITY=0
```

or remove it. SQLite/JSON/mirror remain intact during the window.

## Old path removal

Do not remove old paths until:

- 7 days of clean authority reads;
- no count mismatches;
- research report Agent export 144/144;
- strategy share/authorized lists are migrated;
- a verified backup exists;
- rollback has been tested.

Only then remove:

```text
account_product_groups
factor_family_catalog/heads/sources/metadata/params
strategy_library_* tables
publications.json
mirrors/
```

## Known gaps

- strategy `authorized` list still uses SQLite shares.
- research report edit API is implemented but Web/Swift clients do not use it yet.
- research report projection-aware edits were verified through batch operations.
