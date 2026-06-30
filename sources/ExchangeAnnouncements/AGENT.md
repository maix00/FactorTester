# ExchangeAnnouncements Agent Instructions

`exchange_announcements` is the canonical catalog of numbered
exchange-published announcements. It is not limited to FieldHistory, but it is
limited to official notices with a formal notice number such as
`郑商函〔2021〕164号`.

FieldHistory may later consume rows where `field_change_candidate = true`, but
the announcement catalog itself is a broader data source.

## Storage Rules

- Store rows in SQLite table `exchange_announcements`.
- Only store pages with a formal exchange notice number.
- `announcement_id` is the formal notice number and must equal `notice_id`.
- Do not use URL hashes, source-site numeric IDs, page titles, or source URLs as
  `announcement_id`.
- Pages without a formal notice number must not be inserted into this table.
- Every row must include the source URL and the exact access time.
- Do not store raw requester keys. Use the importer with `--requester-key`; it
  stores only a non-reversible fingerprint.
- Do not silently overwrite an existing announcement. If the same
  `announcement_id` is found with different content, stop for manual review.
- `field_change_candidate = false` is a valid and important row. It means the
  announcement was crawled and judged not to contain supported field-value
  changes.

## Required Announcement Fields

Each announcement row passed to `append_exchange_announcements()` must contain:

```json
{
  "announcement_id": "大商所发〔2025〕243号",
  "exchange": "DCE",
  "source_url": "https://www.dce.com.cn/dce/content/2025/ywggytz/8637864.html",
  "source_accessed_at": "2026-06-30T00:00:00+08:00",
  "published_date": "2025-07-04",
  "notice_id": "大商所发〔2025〕243号",
  "title": "关于纯苯期货合约上市交易有关事项的通知",
  "category": "业务公告与通知",
  "summary": "纯苯期货上市交易事项，含交易手续费标准。",
  "raw_text": "可存正文全文；如果页面反爬或正文很长，至少存能支持标注的摘要与原文摘录。",
  "field_change_candidate": true,
  "field_groups": ["TransactionFee"],
  "field_names": ["OpenRatioByMoney"],
  "products": ["BZ"],
  "contracts": [],
  "parser_notes": "说明为什么判定为字段变更或非字段变更。"
}
```

## Crawling Workflow

For every exchange and announcement list page:

1. Crawl list pages by date/category, not only keyword search results.
2. For each visible announcement, fetch the detail page and first identify its
   formal notice number.
3. If the page has no formal notice number, skip database insertion.
4. For each numbered announcement, create one `exchange_announcements` row with
   `announcement_id = notice_id`.
5. Store:
   - `source_url`
   - `source_accessed_at`
   - `published_date`
   - `notice_id` if present
   - `title`
   - `category`
   - `raw_text` or the best available text/excerpt
6. Judge whether it may contain field-value changes:
   - transaction fee / 手续费
   - margin / 保证金
   - limit or market order size / 下单数量 / 限价单 / 市价单
   - trading hours / 交易时间
   - contract multiplier / 合约乘数
   - price tick / 最小变动价位
7. If yes, fill `field_groups`, `field_names`, `products`, and `contracts` as
   string lists. These are candidate strings, not final normalized events.
8. If no, leave those lists empty and set `field_change_candidate = false`.

## Direct Database Write

Do not write intermediate JSONL files for the announcement catalog. Crawlers and
agents should call the database helper directly:

```python
from sources.ExchangeAnnouncements.store import append_exchange_announcements

append_exchange_announcements(
    [announcement_row],
    requester_key="<runtime-secret-or-local-audit-key>",
)
```

For existing FieldHistory event data only, the bridge script can seed
announcement rows directly from `agent_field_change_events`:

```bash
PYTHONPATH=/path/to/repo python sources/ExchangeAnnouncements/scripts/sync_from_field_history_events.py \
  --field-group TransactionFee \
  --requester-key <runtime-secret-or-local-audit-key>
```

## Coverage Audit

After FieldHistory events are materialized, check whether candidate
announcements have corresponding field-change events:

```bash
PYTHONPATH=/path/to/repo python sources/ExchangeAnnouncements/scripts/audit_field_history_event_coverage.py
```
