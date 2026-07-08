# FieldHistory Agent Instructions

This file is the shared instruction entrypoint for agents that clean historical
field-change events. Keep the workflow centered on `sources.FieldHistory`:
agents append cleaned events, FieldHistory views deduplicate them, and
MarketDataModule reads those views.

Runtime consumers must read the materialized all-field view
`field_history_unified`. Field-group-specific tables such as
`field_history_transaction_fee_unified` and
`field_history_limit_order_volume_unified` may remain for audit and backward
compatibility, but they are not the runtime routing mechanism. When a new field
is added, rebuild `field_history_unified`; do not add another runtime provider
split.

Field-group/data-source-specific instructions live in `AgentInstructions/` and
must be named `<FieldGroup>_<DataSource>.md`.

Cleaned field-change events are data, not code. Store them as JSONL under
`events/<FieldGroup>/`. Python scripts in `scripts/` may validate, deduplicate,
append, materialize, and rebuild views, but must not hardcode source-specific
event payloads.

Current instruction files:

- `AgentInstructions/LimitOrderVolume_CFFEX.md`
- `AgentInstructions/LimitOrderVolume_CZCE.md`
- `AgentInstructions/LimitOrderVolume_DCE.md`
- `AgentInstructions/LimitOrderVolume_GFEX.md`
- `AgentInstructions/LimitOrderVolume_Guosen.md`
- `AgentInstructions/LimitOrderVolume_INE.md`
- `AgentInstructions/LimitOrderVolume_SHFE.md`
- `AgentInstructions/TransactionFee_CFFEX.md`
- `AgentInstructions/TransactionFee_CZCE.md`
- `AgentInstructions/TransactionFee_DCE.md`
- `AgentInstructions/TransactionFee_GFEX.md`
- `AgentInstructions/TransactionFee_Guosen.md`
- `AgentInstructions/TransactionFee_INE.md`
- `AgentInstructions/TransactionFee_OpenCTP.md`
- `AgentInstructions/TransactionFee_SHFE.md`

## Safety Model

- Agents may append rows to `agent_field_change_events`.
- Agents must not delete or update submitted rows.
- The raw requester key must never be stored. Use
  `requester_key_fingerprint(requester_key)` or pass `requester_key` only to the
  ingest helper, which stores a non-reversible hash.
- In production, set `GTHT_AGENT_INGEST_HMAC_SECRET`; without it local
  development uses a namespaced SHA-256 fingerprint.
- Materialization writes each agent event with source key
  `agent/<data_source>/<event_id>`, so it does not replace other source rows.

## Duplicate Check Before Append

Before appending events, agents must check whether the same semantic event is
already stored in `historical_field_values` or in the materialized unified view.
Do not append a duplicate just because the source was visited again.

Use this semantic key:

- `instrument`
- `instrument_type`
- `field_name`
- `effective_trading_day`
- `effective_timestamp` normalized so empty and null mean no timestamp
- normalized `contract_codes`
- decoded `value`

For Guosen current baselines, the semantic key is the same, with
`provider = Agent:Guosen`, `effective_trading_day = 1900-01-01`, empty
`effective_timestamp`, and empty `contract_codes`. If that baseline already
exists for a product/field/type, do not store it again. Only add a Guosen
baseline when a new product, new instrument type, or new field is missing.

For exchange-official dated events, skip the append when an existing row has
the same semantic key and the same `source_notice_id`. If the value or source
differs, treat it as a conflict for manual review instead of appending another
row silently.

Example preflight query:

```sql
SELECT provider, source_key, source_notice_id, value, contract_codes
FROM historical_field_values
WHERE instrument = :instrument
  AND instrument_type = :instrument_type
  AND field_name = :field_name
  AND effective_trading_day = :effective_trading_day
  AND COALESCE(effective_timestamp, '') = COALESCE(:effective_timestamp, '')
  AND contract_codes = :contract_codes_json;
```

## Required Input To The Agent

- Source URL and access time.
- Data source id, for example `DCE`.
- Field group, for example `LimitOrderVolume`.
- Field names requested, for example `MinLimitOrderVolume`.
- Expected database columns and JSON shape.
- Agent name.
- Requester key or requester key hash.

## Required Event JSON

```json
{
  "data_source": "DCE",
  "field_group": "LimitOrderVolume",
  "source_url": "http://www.dce.com.cn/dce/content/2026/ywggytz/18627837.html",
  "source_accessed_at": "2026-06-29T12:00:00+08:00",
  "agent_name": "codex",
  "requester_key": "<do-not-store-raw>",
  "instrument": "BZ",
  "instrument_label": "纯苯",
  "instrument_type": "future",
  "field_name": "MinLimitOrderVolume",
  "effective_trading_day": "2026-03-10",
  "effective_timestamp": "2026-03-09 21:00:00",
  "value": 4,
  "contract_codes": ["2604"],
  "source_notice_id": "大商所发〔2026〕74号",
  "raw_note": "原文中支持该事件的最小完整句子",
  "evidence_text": "原文摘录",
  "parser_notes": "简短说明如何解释原文"
}
```

## Shared Natural-Language Rules

- `期货`, `期货合约`: `instrument_type = future`.
- `期权`, `期权合约`: `instrument_type = option`.
- Product names must be mapped through the product catalog first. If the
  catalog lacks an alias, use source-specific mapping docs and mark the mapping
  in `parser_notes`.
- `全部期货`: expand to all futures products for that exchange at the effective
  time when a product catalog is available. If not available, create an
  exchange-level candidate only; do not guess product codes.
- `除 A、B 外的期货`: expand to all futures products minus A/B only when the
  product universe is known for the effective time. Later product-specific rows
  can override product-level rows in FieldHistory.
- `部分`: never infer scope from the word alone. Scope must come from the listed
  products/contracts/table rows.
- `contract_codes` is not a generic product identifier. Fill it only when the
  source explicitly restricts the field-change event to one contract. Leave it
  empty for product-level rules and for financial products that do not have a
  contract-code scope in the source. Do not synthesize contract codes from a
  term structure or main-contract mapping.
- Contract-specific phrases such as `BZ2604、BZ2605、BZ2606合约` must create
  one event per contract: one row with `contract_codes = ["2604"]`, one row
  with `["2605"]`, and one row with `["2606"]`. Do not create a single row
  containing multiple contract codes. Not every product has a term structure,
  and consumers may query a directly traded contract, so each contract-specific
  field-change event must be atomic.
- Transaction fee rows must distinguish product-level baseline rules from
  contract-specific special rules. A product-level baseline leaves
  `contract_codes` empty. A special contract fee from an exchange notice must
  fill exactly one contract code per row, and it overrides the product-level
  baseline through FieldHistory contract-scope priority.
- Transaction fee baselines do not have to come only from a current fee table.
  They may also come from an official product listing notice, contract
  specification, product technical manual, or exchange settlement-parameter
  table when that source defines the initial fee unit/value. Record the exact
  source type in `parser_notes`. Later fee notices are stored as dated field
  change events that override that baseline.
- Official daily settlement-parameter snapshots may be stored as contract-level
  dated audit events when product-level baselines cannot express close-today
  discounts, temporary special contracts, or contract-specific fee units. Use
  the exchange endpoint itself as `source_url`. Store only the fee field for
  the active fee unit (`*ByMoney` for notional-ratio fees, `*ByVolume` for
  per-lot fixed fees). Do not write the inactive unit as a zero exchange event
  unless the exchange notice explicitly changes the product or contract from
  one fee unit to the other. Do not label broker/OpenCTP snapshots as exchange
  settlement-parameter events.
- The active-unit-only rule above is for exchange-source events. Broker or
  OpenCTP counterparty fee snapshots may legitimately contain both `*ByMoney`
  and `*ByVolume` at the same time, because they can combine exchange fees with
  broker add-ons in different units. Preserve broker fields as observed and keep
  them in the broker/OpenCTP transaction-fee source.
- For TransactionFee, the fee unit is itself historical state. If a product or
  contract changes from fixed fee per lot to traded-notional ratio, or the
  reverse, store both fields at that effective point: the active unit field gets
  the exchange value and the inactive unit field gets `0`. Never leave an old
  inactive unit nonzero.
- Exchange TransactionFee events should use official exchange pages/notices as
  the preferred source. If the original site is blocked, removed, or hidden
  behind WAF, an exact mirror may be used only when it preserves the exchange
  notice id, publication date, exchange author, and the source sentence/table
  without broker markups. Ordinary broker fee pages, Sina-style snapshots, and
  fee aggregators remain audit/cross-check evidence only.
- Night session belongs to the next trading day. Example:
  `自2026年3月10日交易时（即3月9日夜盘交易小节时）起` means
  `effective_trading_day = 2026-03-10` and
  `effective_timestamp = 2026-03-09 21:00:00`.
- Empty lower/upper effective bounds mean open-ended, not unknown.

## Ingest API

```python
from tools.data.field_history_agent_ingest import (
    append_agent_field_change_events,
    materialize_agent_events_to_history,
)

append_agent_field_change_events([event_json])
materialize_agent_events_to_history(data_source="DCE", field_group="LimitOrderVolume")
```

After materialization, rebuild the relevant view, for example:

```python
from sources.FieldHistory.views.LimitOrderVolume import save_unified_table
save_unified_table()
```

For checked-in JSONL event files, use the generic importer:

```bash
PYTHONPATH=/path/to/repo python sources/FieldHistory/scripts/ingest_field_history_events.py \
  sources/FieldHistory/events/TransactionFee/official_seed_events.jsonl \
  --requester-key <runtime-secret-or-local-audit-key>
```
