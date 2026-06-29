# LimitOrderVolume_Guosen

Use this file when cleaning Guosen web snapshots for order-volume fields.

## Source

- Data source id: `Guosen`
- Source type: current web snapshot / secondary evidence.
- Index page:
  `https://www.guosenqh.com.cn/main/kfzx/pzxx/gpzxxhz/index.shtml`
- Locate the latest source page by finding the link whose title contains
  `每笔下单数量限制`.
- The Guosen snapshot is not an exchange announcement and normally does not
  prove the original rule-change date by itself. Prefer exchange announcements
  for authoritative historical change points; use Guosen to add current-state
  evidence and to cross-check the unified view.

## Access Helper

Use this helper to locate and read the latest Guosen snapshot page. It is only
for obtaining source text/table rows for agent review. Do not make it write to
SQLite or materialize FieldHistory rows directly.

```python
from __future__ import annotations

import io
import re
from datetime import date
from urllib.parse import urljoin
from urllib.request import Request, urlopen

import pandas as pd
from bs4 import BeautifulSoup


INDEX_URL = "https://www.guosenqh.com.cn/main/kfzx/pzxx/gpzxxhz/index.shtml"
LINK_TITLE_KEYWORD = "每笔下单数量限制"
PAGE_DATE_PATTERN = re.compile(r"/a/(\\d{8})/")
TABLE_COLUMNS = ["exchange", "product", "limit_order", "market_order", "note"]


def parse_date_from_url(url: str) -> date | None:
    match = PAGE_DATE_PATTERN.search(url)
    if not match:
        return None
    text = match.group(1)
    return date(int(text[:4]), int(text[4:6]), int(text[6:8]))


def discover_source_url(index_url: str = INDEX_URL) -> tuple[str, date | None]:
    request = Request(index_url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=15) as response:
        html = response.read().decode("utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.find_all("a"):
        title = anchor.get_text(strip=True)
        if LINK_TITLE_KEYWORD not in title:
            continue
        href = str(anchor.get("href") or "").strip()
        if not href:
            continue
        source_url = urljoin(index_url, href)
        return source_url, parse_date_from_url(source_url)
    raise RuntimeError(f"cannot find link containing {LINK_TITLE_KEYWORD!r}")


def fetch_guosen_limit_order_table(
    source_url: str | None = None,
    source_date: str | None = None,
) -> pd.DataFrame:
    resolved_url = source_url
    resolved_date: str | None = source_date
    if not resolved_url:
        found_url, found_date = discover_source_url()
        resolved_url = found_url
        resolved_date = found_date.isoformat() if found_date else None

    request = Request(resolved_url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=15) as response:
        html = response.read().decode("utf-8", errors="replace")

    tables = pd.read_html(io.StringIO(html), flavor="html5lib")
    if not tables:
        raise RuntimeError(f"source page has no HTML table: {resolved_url}")

    frame = tables[0].iloc[2:].copy()
    frame.columns = TABLE_COLUMNS
    frame["exchange"] = frame["exchange"].astype(str).str.replace(r"\\s+", "", regex=True)
    for column in ["exchange", "limit_order", "market_order", "note"]:
        frame[column] = frame[column].replace("", float("nan")).ffill()
    frame["source_url"] = resolved_url
    frame["source_date"] = resolved_date or ""
    return frame


if __name__ == "__main__":
    pd.set_option("display.max_rows", None)
    pd.set_option("display.max_columns", None)
    pd.set_option("display.max_colwidth", None)
    print(fetch_guosen_limit_order_table().to_string(index=False))
```

## Field Group

`LimitOrderVolume`

Supported fields:

- `MinLimitOrderVolume`: each order's minimum opening order quantity.
- `MaxLimitOrderVolume`: maximum limit order quantity.
- `MaxMarketOrderVolume`: maximum market order quantity.

## Extraction Rules

- Only create events supported by the Guosen page text/table. Do not hard-code
  product, contract, or value lists in code.
- The Guosen HTML table has this semantic layout after the two-row header:
  `交易所`, `品种`, `限价指令`, `市价指令`, `备注`.
- `MaxLimitOrderVolume` comes from the row's `限价指令` column. Extract the
  number before `手`. Example: `500手` -> `500`.
- `MaxMarketOrderVolume` comes from the row's `市价指令` column. Extract the
  number before `手`; `没有市价指令` means market orders are unavailable and
  should be recorded as `0` only when the downstream field explicitly models
  unavailable market orders as zero.
- `MinLimitOrderVolume` never comes from the `限价指令` or `市价指令` columns.
  It comes only from the row's `备注` column:
  - Baseline text such as `每笔最小下单数量均为1手` gives the current minimum
    quantity, but does not by itself prove the historical start date.
  - Adjustment text such as `自2026年3月9日夜盘起，每次最小开仓下单数量调整为8手`
    gives both the minimum value and the effective point.
- Do not infer `MinLimitOrderVolume` from a maximum-order column. If the
  `备注` column has no minimum-order sentence, skip `MinLimitOrderVolume` for
  that row.
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

- The date embedded in the Guosen URL or page title is `source_date`, not an
  effective start date.
- Empty lower/min bound means Guosen did not prove the start. Do not write a
  historical fact with a fake early date such as `1900-01-01`. If current-state
  evidence is explicitly requested, store it as an agent candidate with
  `parser_notes` explaining that the start date must be confirmed from the
  exchange source before materialization.
- Non-empty lower/min bound, or text like `自YYYY年M月D日...起`, gives
  `effective_trading_day`. If the text says `夜盘`, the night session belongs
  to the next trading day: `自2026年3月9日夜盘起` means
  `effective_timestamp = 2026-03-09 21:00:00` and
  `effective_trading_day = 2026-03-10`.
- Empty upper/max bound means the rule continues until replaced by a later
  FieldHistory event.
- Non-empty upper/max bound is only evidence for a bounded interval. The current
  `historical_field_values` table stores change events, not expiry rows; record
  the upper bound in `parser_notes` and do not invent a new value after expiry
  unless the source states one.
- If the Guosen page has no effective-time evidence at all, do not claim a
  historical change point. For `MaxLimitOrderVolume` and
  `MaxMarketOrderVolume`, use Guosen only to identify candidate current values
  and then find the corresponding exchange notice or product business rule
  before writing `historical_field_values`.

## Finding The Official Start/End Evidence

- For each Guosen row, first map `品种` to product code and exchange through the
  product catalog. Then switch to the exchange-specific instruction file, for
  example `LimitOrderVolume_DCE.md` or `LimitOrderVolume_SHFE.md`.
- Use the Guosen value as search evidence, not as final history. Search the
  official exchange site with:
  - `<品种名> 限价指令 每次最大下单数量 <value>手`
  - `<品种名> 市价指令 每次最大下单数量 <value>手`
  - `<品种名> 每次最小开仓下单数量 <value>手`
  - `自<日期> 夜盘 起 每次最小开仓下单数量 调整为 <value>手`
- For minimum-order adjustments, the start date should usually be in Guosen
  `备注`; confirm it against the official exchange announcement when possible.
- For maximum limit/market order quantities, Guosen usually supplies only the
  current value columns. The start date normally has to be found in exchange
  business rules or an adjustment notice; if not found, do not materialize the
  value into `historical_field_values`.
- Guosen does not provide an explicit end date for current rows. The effective
  end is implicit: it ends when a later official FieldHistory event for the
  same product/contract/field supersedes it.

## Evidence

- Store the source URL and access time in every event.
- Use `source_notice_id = ""` unless the Guosen page itself names an external
  notice id.
- Store the smallest supporting table row or sentence in `raw_note`.
- Store concise source text in `evidence_text`.
- Use `parser_notes` to explain product-name mapping, futures/options
  distinction, open-bound handling, and any universe expansion such as
  `全部期货` or `除...外`.
