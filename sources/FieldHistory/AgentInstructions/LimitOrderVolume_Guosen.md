# LimitOrderVolume_Guosen

Use this file when cleaning Guosen web snapshots for order-volume fields.

## Source

- Data source id: `Guosen`
- Source type: current web snapshot / secondary evidence.
- The Guosen snapshot is not an exchange announcement and normally does not
  prove the original rule-change date by itself. Prefer exchange announcements
  for authoritative historical change points; use Guosen to add current-state
  evidence and to cross-check the unified view.

## Field Group

`LimitOrderVolume`

Supported fields:

- `MinLimitOrderVolume`: each order's minimum opening order quantity.
- `MaxLimitOrderVolume`: maximum limit order quantity.
- `MaxMarketOrderVolume`: maximum market order quantity.

## Extraction Rules

- Only create events supported by the Guosen page text/table. Do not hard-code
  product, contract, or value lists in code.
- Distinguish futures and options before writing events:
  - Rows containing `期货` or futures contracts use `instrument_type = future`.
  - Rows containing `期权` or option contracts use `instrument_type = option`.
  - If one Guosen row mixes futures and options, split it into separate events.
- Map Chinese product names through the product catalog first. If the catalog
  lacks an alias, use a source-local mapping note in `parser_notes`; do not
  guess product codes silently.
- Guosen product phrases must be expanded deliberately:
  - `全部期货`: expand to every futures product for that exchange only when the
    effective-time product universe is known.
  - `XXX、YYY期货`: create product-level futures events for each listed product.
  - `XXX、YYY期权`: create option events, not futures events.
  - `除XXX、YYY外的期货`: expand to the known futures universe minus the listed
    products. Later product-specific events can override the product-level rule
    in FieldHistory.
  - `XXX2222期货合约`: create a contract-specific futures event.
- Contract-specific rows are atomic. If the source lists several contracts,
  create one event per contract. Example: `BZ2604、BZ2605、BZ2606合约` becomes
  three events with `contract_codes = ["2604"]`, `["2605"]`, and `["2606"]`.
  Never store `contract_codes = ["2604", "2605", "2606"]` in one
  agent-ingested event, because not every product has a term structure and
  consumers may query direct contracts.
- If a Guosen row covers a product-level rule, use `contract_codes = []`.
- Extract numeric values from remark columns when the value is described in
  prose, for example `每笔最小下单数量为4手` -> `value = 4`.

## Effective Bounds

Guosen rows may describe open-ended validity with lower/upper bound columns.
Interpret them as bounds, not as the web-query time range:

- Empty lower/min bound means the rule has applied since the past. If a product
  listing date is known, use that listing trading day as `effective_trading_day`;
  otherwise use `1900-01-01` as an explicit open-from-past sentinel and explain
  it in `parser_notes`.
- Non-empty lower/min bound means `effective_trading_day` is that trading day.
  If the source gives an actual session timestamp, also fill
  `effective_timestamp`.
- Empty upper/max bound means the rule continues until replaced by a later
  FieldHistory event.
- Non-empty upper/max bound is only evidence for a bounded interval. The current
  `historical_field_values` table stores change events, not expiry rows; record
  the upper bound in `parser_notes` and do not invent a new value after expiry
  unless the source states one.
- If the Guosen page has no effective-time evidence at all, do not claim a
  historical change point. Either skip the event or write a current-snapshot
  candidate only when the task explicitly asks for current-state evidence, with
  the uncertainty documented in `parser_notes`.

## Evidence

- Store the source URL and access time in every event.
- Use `source_notice_id = ""` unless the Guosen page itself names an external
  notice id.
- Store the smallest supporting table row or sentence in `raw_note`.
- Store concise source text in `evidence_text`.
- Use `parser_notes` to explain product-name mapping, futures/options
  distinction, open-bound handling, and any universe expansion such as
  `全部期货` or `除...外`.
