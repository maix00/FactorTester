# TransactionFee Ingestion Workflow

Transaction fee history is one exchange-rule dataset in FieldHistory.  The same
source-discovery loop should be applied to related exchange-rule fields found in
the same notice, especially margin ratios and order-volume limits.  Do not
create exchange baselines from broker fee tables, OpenCTP snapshots, or current
settlement parameter tables.  Those sources are audit evidence only; if they
imply a change, find the exchange notice, listing document, business rule, or
product manual before ingesting a FieldHistory event.

## Required Order

## Source-Granular Ingestion Invariant

Every official source must be parsed as one semantic unit.  Whether the source
is used for `asof_confirmed`, listing `baseline`, or dated `change`, ingest all
supported fields that the same source explicitly states for all products and
contract scopes it mentions.  Do not ingest only the field currently being
audited and leave margin, price limit, order-volume, contract-metadata, or fee
companion fields for a later pass when they are present in the same source.

Absence of a field in the source is not a default value.  If a notice says a
monthly-average future inherits margin or price-limit settings from the
corresponding physical-delivery contract, resolve the corresponding
product/contract's current FieldHistory value at the inherited product's
effective trading day and store a product-level listing baseline with evidence
pointing to both the inheritance notice and the resolved base field.  This is
not an exchange-default row.  If the base value cannot be resolved, leave a
missing-inheritance audit gap or fail the ingestion step; never synthesize the
number from a broker table or generic exchange default.

### Phase 1: 2024+ replay coverage

1. First make every exchange product replayable from the 2024 boundary.  Use
   `change_type = "asof_confirmed"` only for a state confirmed by a source that
   carries exchange rule semantics, such as a product rule page, listing
   document, business rule, or notice-preserving source at the 2024 boundary.
   Settlement-parameter snapshots can identify candidate values but are not
   themselves ingestible FieldHistory events.
2. `asof_confirmed` is only for products that already existed before the 2024
   boundary.  Products listed after the 2024 boundary must use normal listing
   `baseline` rows and later `change` rows; do not seed them from snapshots as
   as-of rows.
3. Prefer original exchange snapshots for bulk coverage of pre-2024 products.
   Do not ingest margin or fee values from AKShare, futures-company pages, or
   information-site fee tables as exchange rules.  Those sources can only be
   used to locate likely change dates, official notice ids, or cross-check
   values after an exchange source has been found.
4. If an original exchange snapshot is not available, fall back to exchange
   notices, product manuals, business rules, or notice-preserving reposts.
5. When a notice is encountered while filling 2024+ coverage, ingest it through
   the normal notice-event workflow below.  Do not discard notice evidence just
   because the immediate goal is an as-of state.
   Listing notices are normal baseline evidence: for example, GFEX listing
   notices that state "交易手续费为成交金额的万分之一" create product-level
   `OpenRatioByMoney`/`CloseRatioByMoney` baselines and inactive
   `*RatioByVolume = 0` baselines from the listing trading day.
6. After each batch, rebuild views and run the unified 2024 coverage audit:

```bash
PYTHONPATH=. python sources/FieldHistory/scripts/audit_field_history.py \
  --mode 2024-plus \
  --output-csv /tmp/field_history_2024_gaps.csv
```

The same entrypoint also runs shared event-chain checks.  It reports non-as-of
duplicate rows, same-day conflicts, missing effective timestamps, and suspicious
previous-value continuity rows.  If a current/as-of exchange snapshot value
differs from the latest prior `baseline`/`change`/`exception_unchanged` event,
treat that as a missing intermediate `change` notice.  Do not silently let the
newer snapshot overwrite the historical event chain; the snapshot is an audit
sentinel until the missing dated notice is found and ingested.

### Phase 2: full historical reconstruction

1. Find the listing notice, contract rule, contract specification, or product
   manual for the instrument.  Store all initial exchange-rule fields stated by
   that source as `change_type = "baseline"` with the listing effective trading
   day.  This includes TransactionFee, Margin, LimitOrderVolume, and contract
   metadata fields when the source states them.
2. Use official settlement parameter snapshots, if available, to infer possible
   value-change dates.  Snapshot rows are not listing baselines; store them as
   `asof_confirmed` only when Phase 1 coverage needs a confirmed state.
3. For each inferred change point, find the corresponding exchange notice.
   Prefer the original exchange URL.  If the original page is blocked or
   unavailable, a notice-preserving repost can be used temporarily only when it
   keeps the exchange notice id, publication date, issuer, and supporting text.
4. When a notice is found, ingest every supported field and every
   product/contract scope mentioned by that notice, not only the product
   currently being audited.  A fee notice can also change margin, price limits,
   or minimum order quantity.
5. If the closest prior applicable event already has the same value, do not
   insert another `change` event.  Use `exception_unchanged` only when the notice
   has semantic scope information that matters, such as "and subsequent
   contracts", but the value is intentionally unchanged.
6. After ingesting notices, rebuild views and run the unified full-history audit
   against settlement snapshots.  Remaining snapshot mismatches are a todo list
   for more source discovery, not permission to synthesize exchange events from
   snapshots:

```bash
PYTHONPATH=. python sources/FieldHistory/scripts/audit_field_history.py \
  --mode full-history \
  --settlement-snapshot-jsonl /tmp/field_history_fee_changes_20240102_20260709.jsonl \
  --output-csv /tmp/field_history_full_history_gaps.csv
```

## Field Groups

- `TransactionFee`: open, close-yesterday, and close-today fee fields.  Store
  active fee units carefully as described below.
- `Margin`: long/short margin ratio fields.  For Chinese futures, source text
  usually states margin as a percentage of contract value, so use
  `LongMarginRatioByMoney` and `ShortMarginRatioByMoney`; fixed-per-lot margin
  fields are zero unless explicitly stated.
  Product-level margin rows represent the exchange's normal/base margin value
  after listing notices, business rules, product manuals, or margin-adjustment
  notices.  They do not by themselves model lifecycle overlays.  For example,
  DCE product rules state that each product's margin standard and price limits
  follow the DCE Risk Management Measures, and those measures raise margin by
  contract lifecycle stage: most products use 10% from the 15th trading day of
  the month before delivery and 20% from the first trading day of delivery
  month, while L/PP/V skip the first step and use 20% from the first trading day
  of delivery month.  Single-sided limit moves, holidays, position-size risk,
  hedge margins, combination margins, and exchange announcements can also
  override base values, with the applicable margin chosen by the maximum of all
  active rules.  Store the base historical values in FieldHistory, and model
  the lifecycle/risk overlays in the TradingRule/Margin rule engine rather than
  as a single product-level baseline.
- `LimitOrderVolume`: `MinLimitOrderVolume`, `MaxLimitOrderVolume`, and
  `MaxMarketOrderVolume`.  Product business rules are acceptable sources from
  their own effective date.  Do not backdate a current business rule to listing
  day unless it is the listing rule or a historical rule with that effective
  date.

## Unit Semantics

- `*RatioByMoney` and `*RatioByVolume` are separate fields because an exchange
  can switch active fee units over time.
- For one exchange product at one effective scope, usually only money or volume
  is active.  Store both units as fields.  At listing or at an as-of confirmed
  boundary, the inactive unit must have an explicit zero value; if the active
  unit changes later, write a change for the new non-zero unit and a matching
  zero change for the old unit.
- Broker sources can have both money and volume components at the same time.
  That is broker add-on behavior and belongs to broker/counterparty data, not
  the exchange historical rule.
- SHFE/INE official settlement JSON fields `TTRADEFEERATIO` and
  `TTRADEFEEUNIT` match the hedge (`套保`) transaction-fee columns shown in
  official fee-change attachments, not the normal close-today (`平今`) fee
  columns.  `ISUNITODAY` is a feed flag, not a fee amount or rate.  Never map
  `TTRADE*` or `ISUNITODAY` into `CloseToday*`; close-today fields require an
  explicit close-today source or announcement.
- If a listing notice says only "交易手续费为成交金额的万分之一" and does not
  mention close-today exemption, the normal close-today fee is the same active
  unit and value as open/close.  If it explicitly says "免收日内平今仓交易手续
  费", set both close-today fee units to zero for that baseline.  Hedge
  (`套期保值`) fee text is a separate rule and must not be used as normal
  close-today fee.

## Scope Semantics

- Product-wide rules use `contract_scope_type = "all"` and an empty
  `contract_codes` list.
- Contract-specific rules store one event per contract code.
- Official settlement snapshots used for `asof_confirmed` are usually contract
  rows.  Always preserve both levels when contracts differ: write one
  product-level `contract_scope_type = "all"` row as the as-of anchor, and write
  `contract_scope_type = "explicit"` rows for contracts whose value differs from
  that product-level anchor.  Resolver priority is contract scope over product
  scope, so explicit rows override the product anchor.
- Notices such as "XXX合约及后续合约" use
  `contract_scope_type = "from_contract"` with `contract_code_start`.
- Notices with a bounded contract range use `contract_scope_type = "range"`.
- If a notice says a listed set of contracts is unchanged, store
  `change_type = "exception_unchanged"` rather than a fake value change.

## Repository Hygiene

- Generated snapshot/change jsonl files are staging artifacts.  Do not add new
  generated jsonl files to git unless they are deliberately curated source
  fixtures.
- Prefer direct database ingestion for cleaned events.  If a temporary jsonl is
  needed for review or replay, write it outside the repository or delete it
  before committing.
- Product audit reports should go to stdout or an explicit temporary CSV path.

## Product Audit Loop

Run the product audit before and after ingesting notices:

```bash
PYTHONPATH=. python sources/FieldHistory/scripts/audit_transaction_fee_product_workflow.py CY --exchange CZCE
```

This is a product-level drill-down helper, not the overall audit entrypoint.
The helper output is the checklist:

- listing baseline present before the first change;
- snapshot-implied changes aligned to a prior or exact notice;
- notice rows with no preceding baseline;
- source URLs and notice ids that need official originals.
