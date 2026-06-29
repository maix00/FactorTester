# FieldHistory Agent Instructions

This file is the shared instruction entrypoint for agents that clean historical
field-change events. Keep the workflow centered on `sources.FieldHistory`:
agents append cleaned events, FieldHistory views deduplicate them, and
MarketDataModule reads those views.

Field-group/data-source-specific instructions live in `AgentInstructions/` and
must be named `<FieldGroup>_<DataSource>.md`.

Current instruction files:

- `AgentInstructions/LimitOrderVolume_DCE.md`
- `AgentInstructions/LimitOrderVolume_Guosen.md`

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
- Contract-specific phrases such as `BZ2604、BZ2605、BZ2606合约` must create
  one event per contract: one row with `contract_codes = ["2604"]`, one row
  with `["2605"]`, and one row with `["2606"]`. Do not create a single row
  containing multiple contract codes. Not every product has a term structure,
  and consumers may query a directly traded contract, so each contract-specific
  field-change event must be atomic.
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
