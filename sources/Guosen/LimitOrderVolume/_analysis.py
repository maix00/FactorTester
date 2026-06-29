"""清洗国信期货限价单手数页面表格，输出结构化 AlterEvent。

数据流程：
  fetch_table()                    → 原始 DataFrame (脏)
  _analysis.parse_events(df)      → list[dict] (干净、结构化)
  _store.save_events(events)      → SQLite guosen_limit_order_events
  access.py                       → 从 SQLite / 内存读取事件

脏数据的主要挑战：
  1. 一行多品种（"铜期权、橡胶期权、黄金期权"）
  2. "除XX外"反向排除（需查 SQLite catalog 列出交易所全部品种再排除）
  3. 合约级 vs 品种级（"甲醇期货2606合约"  vs "红枣"）
  4. product_label → product_code 映射（查 SQLite catalog）
  5. note 中嵌入的历史调整事件（正则提取 date + new_value）
"""

from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

logger = logging.getLogger(__name__)

from .alter import (
    Exchange,
    _MIN_OPEN_PATTERN,
    _MIN_OPEN_PATTERN_FALLBACK,
    _CONTRACT_CODE_PATTERN,
    _EXCLUSION_PATTERN,
)

# 品种代码映射：优先 SQLite catalog（CNFutures.desc_to_code），其次国信别名
from sources.LocalCNFutures.CNFutures import CNFutures
from sources.Guosen.mapping import GUOSEN_PRODUCT_ALIAS

# 合并两个正则，优先 primary，fallback 其次
_MIN_OPEN_PATTERNS = [_MIN_OPEN_PATTERN, _MIN_OPEN_PATTERN_FALLBACK]

# ---------------------------------------------------------------------------
# 解析 product 列：品种中文名 + 合约代码
# ---------------------------------------------------------------------------

# 匹配「XX期货2605-2606合约」或「XX期货2606合约」
# group 1: 品种名（不含「期货」后缀）
# group 2: 合约范围（如 2605-2606 或 2606）
_PRODUCT_FUTURES_CONTRACT_PATTERN = re.compile(
    r"^(?P<product>.+?)期货(?P<contract_range>\d{4}(?:[-—]\d{4})?(?:\s*[-至及,\s]\s*\d{4})*)\s*合约$"
)

# 匹配「XX期货」或「XX期权」（无合约代码）
_PRODUCT_SUFFIX_PATTERN = re.compile(r"^(.+?)(期货|期权)$")

# 匹配「XX期货合约」（无具体合约代码，如「多晶硅期货合约」）
_PRODUCT_GENERIC_CONTRACT_PATTERN = re.compile(r"^(.+?)(?:期货|期权)合约$")

# 匹配纯品种名 + 合约后缀（如「甲醇2606」）
_PRODUCT_CONTRACT_SHORT_PATTERN = re.compile(
    r"^(?P<product>.+?)\s*(?P<contract_range>\d{4}(?:[-—]\d{4})?)$"
)
_MIN_ORDER_BASELINE_PATTERN = re.compile(r"每笔最小下单数量均为\s*(?P<qty>[\d.]+)\s*手")
_ALL_FUTURES_EXCLUSION_PATTERN = re.compile(r"所有\s*期货\s*品种\s*[（(]\s*除(?P<excluded>.+?)外\s*[）)]")

INSTRUMENT_TYPE_FUTURE = "future"
INSTRUMENT_TYPE_OPTION = "option"
INSTRUMENT_TYPE_UNKNOWN = "unknown"

MATCH_STATUS_MATCHED = "matched"
MATCH_STATUS_UNMATCHED = "unmatched"

_ALL_FUTURES_PRODUCT_LABEL = "所有期货品种"
_OPEN_ENDED_START_DAY = "1900-01-01"


# ---------------------------------------------------------------------------
# 品种中文名 → 品种代码（product_code）的映射
# ---------------------------------------------------------------------------
# 主映射：通过 CNFutures.desc_to_code() 查询 SQLite catalog 的「合约标的→品种代码」
# 补充别名：国信页面用名  ≠ catalog 合约标的 时的兜底映射


def detect_instrument_type(product_label: str) -> str:
    """识别国信页面中的品种类型。

    国信页面多数期货品种只写中文品种名，不显式带「期货」后缀；在本数据源中
    裸品种默认按期货处理，只有明确出现「期权」时标记为 option。
    """
    label = str(product_label or "").strip()
    if "期权" in label:
        return INSTRUMENT_TYPE_OPTION
    if "期货" in label or "合约" in label or label:
        return INSTRUMENT_TYPE_FUTURE
    return INSTRUMENT_TYPE_UNKNOWN


def _clean_text(value: object) -> str:
    text = str(value or "").strip()
    if text.lower() in {"nan", "none", "nat"}:
        return ""
    return re.sub(r"\s+", "", text)

def lookup_product_code(product_label: str) -> str:
    """中文品种名 → 品种代码（如 '甲醇' → 'MA'）。未知时返回原字符串。"""
    # 1) CNFutures.desc_to_code 先查 GUOSEN_PRODUCT_ALIAS，再查 SQLite catalog
    code = CNFutures.desc_to_code(product_label, extra_map=GUOSEN_PRODUCT_ALIAS)
    if code != product_label:
        return code
    # 2) 去掉「期货」「期权」后缀再查
    stripped = _PRODUCT_SUFFIX_PATTERN.sub(r"\1", product_label)
    code = CNFutures.desc_to_code(stripped, extra_map=GUOSEN_PRODUCT_ALIAS)
    if code != stripped:
        return code
    return product_label


def lookup_product_identity(product_label: str) -> dict[str, str]:
    """返回品种代码和匹配状态，避免把未匹配的中文名误当作规范代码。"""
    code = lookup_product_code(product_label)
    status = MATCH_STATUS_MATCHED if code != product_label else MATCH_STATUS_UNMATCHED
    return {
        "product_code": code,
        "product_code_match_status": status,
    }


def _normalise_string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def event_to_historical_field_records(event: dict) -> list[dict]:
    """把 Guosen 事件归一化为公共 historical_field_values 记录。

    页面里的「所有期货品种」是交易所级聚合语义。事件表保留原行，同时
    historical_field_values 按解析出的 product_codes 展开，供 MarketDataModule
    以具体品种代码查询。
    """
    product_codes = _normalise_string_list(event.get("product_codes"))
    if not product_codes:
        product_code = str(event.get("product_code") or "").strip()
        if product_code:
            product_codes = [product_code]
    if not product_codes:
        return []
    value = event.get("new_value")
    if value is None:
        return []
    effective_day = event.get("effective_date") or _OPEN_ENDED_START_DAY
    if not effective_day:
        return []
    records = []
    for product_code in product_codes:
        records.append({
            "provider": "Guosen",
            "source_key": "Guosen/LimitOrderVolume",
            "instrument": product_code,
            "instrument_label": event.get("product_label") or "",
            "instrument_type": event.get("instrument_type") or "future",
            "field_name": event.get("field") or "",
            "effective_trading_day": effective_day,
            "effective_timestamp": event.get("effective_timestamp") or "",
            "value": value,
            "contract_codes": event.get("contract_codes") or [],
            "source_url": event.get("source_url") or "",
            "source_date": event.get("source_date") or "",
            "raw_note": event.get("raw_note") or "",
        })
    return records

def events_to_historical_field_records(events: list[dict]) -> list[dict]:
    records: list[dict] = []
    for event in events:
        records.extend(event_to_historical_field_records(event))
    return records


# ---------------------------------------------------------------------------
# 产品列表：按交易所获取全部品种（用于"除XX外"反向排除）
# ---------------------------------------------------------------------------

_EXCHANGE_PRODUCTS: dict[str, list[str]] | None = None  # lazy loaded


def _load_exchange_products() -> dict[str, list[str]]:
    """按交易所分组品种中文名，复用 CNFutures.products_by_exchange()。"""
    global _EXCHANGE_PRODUCTS
    if _EXCHANGE_PRODUCTS is not None:
        return _EXCHANGE_PRODUCTS
    _EXCHANGE_PRODUCTS = CNFutures.products_by_exchange()
    return _EXCHANGE_PRODUCTS


_EXCHANGE_PRODUCT_CODES: dict[str, list[str]] = {}


def _load_exchange_product_codes(exchange_code: str) -> list[str]:
    """返回某交易所全部期货品种代码，用于解析「所有期货品种」。"""
    if exchange_code in _EXCHANGE_PRODUCT_CODES:
        return _EXCHANGE_PRODUCT_CODES[exchange_code]
    codes: list[str] = []
    seen: set[str] = set()
    for product_label in _load_exchange_products().get(exchange_code, []):
        identity = lookup_product_identity(product_label)
        if identity["product_code_match_status"] != MATCH_STATUS_MATCHED:
            continue
        code = identity["product_code"]
        if code in seen:
            continue
        seen.add(code)
        codes.append(code)
    _EXCHANGE_PRODUCT_CODES[exchange_code] = codes
    return codes


def _product_identity_for_event(clean_product: str, exchange_code: str) -> tuple[str, str, list[str]]:
    if _is_all_futures_label(clean_product):
        product_codes = _load_exchange_product_codes(exchange_code)
        status = MATCH_STATUS_MATCHED if product_codes else MATCH_STATUS_UNMATCHED
        return "", status, product_codes
    identity = lookup_product_identity(clean_product)
    product_code = identity["product_code"]
    match_status = identity["product_code_match_status"]
    product_codes = [product_code] if match_status == MATCH_STATUS_MATCHED else []
    return product_code, match_status, product_codes


def _normalise_product_for_event(product_label: str) -> tuple[str, str, list[str]]:
    product_label = _clean_text(product_label)
    instrument_type = detect_instrument_type(product_label)
    contract_codes: list[str] = []
    clean_product = product_label

    contract_match = _PRODUCT_FUTURES_CONTRACT_PATTERN.match(product_label)
    if contract_match:
        clean_product = contract_match.group("product").strip()
        raw_range = contract_match.group("contract_range")
        contract_codes = [
            c.strip()
            for c in re.split(r"[-至及,\s]+", raw_range)
            if c.strip()
        ]

    generic_match = _PRODUCT_GENERIC_CONTRACT_PATTERN.match(clean_product)
    if generic_match:
        clean_product = generic_match.group(1).strip()

    suffix_match = _PRODUCT_SUFFIX_PATTERN.match(clean_product)
    if suffix_match:
        clean_product = suffix_match.group(1).strip()

    return clean_product, instrument_type, contract_codes


# ---------------------------------------------------------------------------
# 字符串工具
# ---------------------------------------------------------------------------

def _parse_hand(value: str) -> float | None:
    """从「500手」等字符串中提取数值。"""
    if not value:
        return None
    value = str(value).strip()
    m = re.search(r"([\d.]+)\s*手", value)
    if m:
        return float(m.group(1))
    # 尝试直接解析数字
    try:
        return float(value)
    except ValueError:
        return None


def _is_partial_exclusion(label: str) -> bool:
    return "部分" in _clean_text(label)


def _is_all_futures_label(label: str) -> bool:
    return _clean_text(label) in {"所有期货品种", "全部期货", "所有期货"}


def _split_products(product_str: str) -> list[str]:
    """把「甲醇、PTA、短纤」拆成单个品种名列表。

    正则中不直接用 \1 替代（保持纯 split 逻辑）。
    """
    if not product_str:
        return []
    # 先用中文顿号/逗号 split
    parts = re.split(r"[、，,]", _clean_text(product_str))
    result: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # 处理「XXX及XXX」模式
        sub_parts = re.split(r"及|和", part)
        for sp in sub_parts:
            sp = sp.strip()
            if sp:
                result.append(sp)
    return result


def _split_exclusion_items(excluded_raw: str) -> list[str]:
    items = _split_products(excluded_raw)
    if not items:
        return []
    suffix = ""
    tail = items[-1]
    if "期权" in tail:
        suffix = "期权"
    elif "期货" in tail:
        suffix = "期货"
    normalised: list[str] = []
    for item in items:
        clean = _clean_text(item)
        if suffix and "期货" not in clean and "期权" not in clean:
            clean = f"{clean}{suffix}"
        normalised.append(clean)
    return normalised


def _propagate_list_instrument_suffix(products: list[str], product_text: str) -> list[str]:
    clean_text = _clean_text(product_text)
    suffix = ""
    if "期权" in clean_text and "期货" not in clean_text:
        suffix = "期权"
    elif "期货" in clean_text and "期权" not in clean_text:
        suffix = "期货"
    if not suffix:
        return products
    propagated: list[str] = []
    for product in products:
        clean = _clean_text(product)
        if clean and "期货" not in clean and "期权" not in clean and not _is_all_futures_label(clean):
            clean = f"{clean}{suffix}"
        propagated.append(clean)
    return propagated


def _included_products_for_row(exchange_code: str, product_str: str) -> list[str]:
    product_text = _clean_text(product_str)
    if not product_text:
        return []

    all_products_for_exch = _load_exchange_products().get(exchange_code, [])
    all_futures_with_parenthesized_exclusion = _ALL_FUTURES_EXCLUSION_PATTERN.search(product_text)
    if all_futures_with_parenthesized_exclusion:
        excluded_items = _split_exclusion_items(all_futures_with_parenthesized_exclusion.group("excluded"))
        return _filter_excluded_products(all_products_for_exch, excluded_items)

    exclusion_match = _EXCLUSION_PATTERN.search(product_text)
    if exclusion_match and "期货" in product_text:
        excluded_items = _split_exclusion_items(exclusion_match.group("excluded"))
        return _filter_excluded_products(all_products_for_exch, excluded_items)

    return _propagate_list_instrument_suffix(_split_products(product_text), product_text)


def _filter_excluded_products(all_products: list[str], excluded_items: list[str]) -> list[str]:
    included: list[str] = []
    full_exclusions = [item for item in excluded_items if not _is_partial_exclusion(item)]
    for product in all_products:
        product_clean = _clean_text(product)
        is_excluded = False
        for excluded in full_exclusions:
            excluded_product = _PRODUCT_SUFFIX_PATTERN.sub(r"\1", excluded)
            if excluded_product and (excluded_product in product_clean or product_clean in excluded_product):
                is_excluded = True
                break
        if not is_excluded:
            included.append(product)
    return included


def _baseline_min_order_from_note(note: str) -> float | None:
    match = _MIN_ORDER_BASELINE_PATTERN.search(_clean_text(note))
    if not match:
        return None
    return float(match.group("qty"))


def _effective_metadata_from_match(match: re.Match[str], note: str) -> tuple[str, str]:
    """Parse the actual rule effective point from a Guosen note match."""
    groupdict = match.groupdict()
    month_text = groupdict.get("month") or groupdict.get("month2")
    day_text = groupdict.get("day") or groupdict.get("day2") or "1"
    if month_text is None:
        raise ValueError("missing month")
    event_date = date(int(match["year"]), int(month_text), int(day_text))
    if "夜盘" in _clean_text(note):
        effective_timestamp = datetime.combine(
            event_date,
            datetime.min.time(),
        ).replace(hour=21)
        return (event_date + timedelta(days=1)).isoformat(), effective_timestamp.isoformat(sep=" ")
    return event_date.isoformat(), ""


# ---------------------------------------------------------------------------
# 核心解析函数
# ---------------------------------------------------------------------------

def parse_row_to_baseline(
    exchange_name: str,
    product_str: str,
    note: str,
    source_url: str,
    source_date: str,
) -> list[dict]:
    """将一行表格数据解析为基线事件列表（每个品种一条，不含历史调整）。

    baseline 事件 = 当前生效的限价单/市价单限制（无 effective_date）。
    一行可能含多品种，拆分为多行。

    返回 list[dict]，每项含 exchange, product_label, product_code, contract_codes,
    field="MaxLimitOrderVolume", old_value/ new_value/ effective_date= None。
    """
    exchange_code = Exchange.from_label(exchange_name) or exchange_name
    products = _split_products(product_str)
    results: list[dict] = []
    for product_label in products:
        product_label = product_label.strip()
        if not product_label:
            continue
        product_code, match_status, product_codes = _product_identity_for_event(
            product_label,
            exchange_code,
        )
        results.append({
            "exchange": exchange_code,
            "product_label": product_label,
            "product_code": product_code,
            "product_codes": product_codes,
            "product_code_match_status": match_status,
            "instrument_type": detect_instrument_type(product_label),
            "contract_codes": [],
            "field": "MaxLimitOrderVolume",
            "old_value": None,
            "new_value": None,
            "effective_date": None,
            "source_url": source_url,
            "source_date": source_date,
            "raw_note": note.strip() if note else "",
            "is_product_level": True,
        })
    return results


def parse_row_to_alter_events(
    exchange_name: str,
    product_str: str,
    limit_order: str,
    market_order: str,
    note: str,
    source_url: str,
    source_date: str,
) -> list[dict]:
    """将一行表格数据解析为 AlterEvent dict 列表。

    处理流程：
    1. 确定交易所代码
    2. 处理「除XX外」：反向排除 → 拆出多个单品种行
    3. 拆分多品种
    4. 从 product 列提取 contract_codes（如「甲醇期货2606合约」）
    5. 从 note 列提取历史调整事件（date + new_value）
    6. 若无可识别的调整事件，该行作为基线事件（无 effective_date）

    返回可直接传给 AlterEvent(**item) 的 dict 列表。
    """
    exchange_code = Exchange.from_label(exchange_name) or exchange_name
    source_url = source_url or ""
    source_date_str = source_date or ""
    limit_order_hand = _parse_hand(limit_order)
    market_order_hand = _parse_hand(market_order)
    note = _clean_text(note)
    included = _included_products_for_row(exchange_code, product_str)

    # --- 逐品种解析 ---
    events: list[dict] = []
    for product_label in included:
        product_label = _clean_text(product_label)
        if not product_label:
            continue
        clean_product, instrument_type, contract_codes = _normalise_product_for_event(product_label)

        product_code, product_code_match_status, product_codes = _product_identity_for_event(
            clean_product,
            exchange_code,
        )

        def append_event(
            field_name: str,
            value: float | None,
            *,
            effective_date: str | None = None,
            effective_timestamp: str | None = None,
            codes: list[str] | None = None,
        ) -> None:
            if value is None:
                return
            event_contract_codes = list(contract_codes if codes is None else codes)
            events.append({
                "exchange": exchange_code,
                "product_label": clean_product,
                "product_code": product_code,
                "product_codes": product_codes,
                "product_code_match_status": product_code_match_status,
                "instrument_type": instrument_type,
                "contract_codes": event_contract_codes,
                "field": field_name,
                "old_value": None,
                "new_value": value,
                "effective_date": effective_date,
                "effective_timestamp": effective_timestamp,
                "source_url": source_url,
                "source_date": source_date_str,
                "raw_note": note.strip(),
                "is_product_level": len(event_contract_codes) == 0,
            })

        # 提取历史调整事件（双正则，优先 primary）
        alter_events_from_note: list[re.Match] = []
        for pat in _MIN_OPEN_PATTERNS:
            found = list(pat.finditer(note))
            if found:
                alter_events_from_note = found
                break

        row_effective_date: str | None = None
        row_effective_timestamp: str | None = None
        if alter_events_from_note:
            try:
                row_effective_date, row_effective_timestamp = _effective_metadata_from_match(
                    alter_events_from_note[0],
                    note,
                )
            except (ValueError, KeyError, TypeError):
                row_effective_date = None
                row_effective_timestamp = None

        append_event(
            "MaxLimitOrderVolume",
            limit_order_hand,
            effective_date=row_effective_date,
            effective_timestamp=row_effective_timestamp,
        )
        append_event(
            "MaxMarketOrderVolume",
            market_order_hand,
            effective_date=row_effective_date,
            effective_timestamp=row_effective_timestamp,
        )

        baseline_min_order = _baseline_min_order_from_note(note)
        if baseline_min_order is not None:
            append_event("MinLimitOrderVolume", baseline_min_order)

        if alter_events_from_note:
            # note 中包含调整记录 → 生成带 effective_date 的事件
            for m in alter_events_from_note:
                try:
                    eff_date, eff_timestamp = _effective_metadata_from_match(m, note)
                except (ValueError, KeyError, TypeError):
                    continue
                new_qty = float(m["new_qty"])

                # 如果 note 中提到了合约代码，优先用 note 中的
                codes = contract_codes
                codes_match_note = _CONTRACT_CODE_PATTERN.search(note)
                if codes_match_note:
                    raw_codes = codes_match_note.group("code")
                    codes = [
                        c.strip()
                        for c in re.split(r"[-至及,\s]+", raw_codes)
                        if c.strip()
                    ]

                append_event(
                    "MinLimitOrderVolume",
                    new_qty,
                    effective_date=eff_date,
                    effective_timestamp=eff_timestamp,
                    codes=codes,
                )

    return events


def parse_events_from_df(df: "pd.DataFrame") -> list[dict]:
    """从 fetch_table() 产出的原始 DataFrame 解析所有 AlterEvent。

    参数：
        df: fetch_table() 返回的 DataFrame，
            columns = [exchange, product, limit_order, market_order, note, source_url, source_date]

    返回：
        list[dict]，可直接传入 AlterEvent(**item) 或写入 SQLite。
    """
    # 避免重名冲突
    _Exchange = Exchange

    all_events: list[dict] = []
    df_filtered = df[~df["product"].astype(str).str.contains("交易所", na=False)].copy()

    for _, row in df_filtered.iterrows():
        exchange_name = str(row.get("exchange", ""))
        product_str = str(row.get("product", ""))
        limit_order = str(row.get("limit_order", ""))
        market_order = str(row.get("market_order", ""))
        note = str(row.get("note", ""))
        source_url = str(row.get("source_url", ""))
        source_date = str(row.get("source_date", ""))

        # 跳过表头行（exchange列实际包含"交易所"字样）
        if "交易所" in exchange_name and not any(
            k in exchange_name for k in _Exchange._LABELS
        ):
            continue

        row_events = parse_row_to_alter_events(
            exchange_name=exchange_name,
            product_str=product_str,
            limit_order=limit_order,
            market_order=market_order,
            note=note,
            source_url=source_url,
            source_date=source_date,
        )
        all_events.extend(row_events)

    logger.info("从 %d 行解析出 %d 个事件", len(df), len(all_events))
    return all_events


# ---------------------------------------------------------------------------
# 导出为 alter.py 兼容的 KNOWN_ALTER_EVENTS 格式
# ---------------------------------------------------------------------------

def export_known_events_py(events: list[dict]) -> str:
    """将解析出的事件导出为 alter.py 风格 Python 代码。

    方便人工审阅后粘贴到 alter.KNOWN_ALTER_EVENTS。
    """
    import textwrap

    lines = ["KNOWN_ALTER_EVENTS: list[dict] = ["]
    # 按交易所分组
    by_exchange: dict[str, list[dict]] = {}
    for ev in events:
        by_exchange.setdefault(ev["exchange"], []).append(ev)

    exchange_comments = {
        "SHFE": "上海期货交易所",
        "INE": "上海国际能源交易中心",
        "DCE": "大连商品交易所",
        "CZCE": "郑州商品交易所",
        "GFEX": "广州期货交易所",
        "CFFEX": "中国金融期货交易所",
    }

    for exch_code in ["SHFE", "INE", "DCE", "CZCE", "GFEX", "CFFEX"]:
        exch_events = by_exchange.get(exch_code, [])
        if not exch_events:
            lines.append(f"    # ---- {exchange_comments.get(exch_code, exch_code)} ----")
            continue
        lines.append(f"    # ---- {exchange_comments.get(exch_code, exch_code)} ----")
        for ev in exch_events:
            contract_codes = repr(tuple(ev.get("contract_codes", [])))
            eff_date_str = (
                f'date({ev["effective_date"].split("-")[0]}, {ev["effective_date"].split("-")[1]}, {ev["effective_date"].split("-")[2]})'
                if ev.get("effective_date")
                else "None"
            )
            lines.append("    {")
            lines.append(f'        "exchange": Exchange.{exch_code},')
            lines.append(f'        "product_label": "{ev["product_label"]}",')
            lines.append(f'        "contract_codes": {contract_codes},')
            lines.append(f'        "field": "{ev["field"]}",')
            if ev.get("old_value") is not None:
                lines.append(f'        "old_value": {ev["old_value"]},')
            lines.append(f'        "new_value": {ev["new_value"]},')
            lines.append(f'        "effective_date": {eff_date_str},')
            lines.append(f'        "source_url": SOURCE_URL,')
            lines.append(f'        "raw_note": """{ev["raw_note"]}""",')
            lines.append("    },")
    lines.append("]")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI / 测试入口
# ---------------------------------------------------------------------------

def _main() -> None:
    """直接运行：抓取页面 → 解析事件 → 打印结果。"""
    import sys
    from pathlib import Path

    if __package__ in (None, ""):
        root = Path(__file__).resolve().parents[3]
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))

    from sources.Guosen.LimitOrderVolume import fetch_table

    df = fetch_table()
    events = parse_events_from_df(df)
    print(f"解析出 {len(events)} 个事件:\n")
    for i, ev in enumerate(events):
        print(
            f"  [{i}] {ev['exchange']} | {ev['product_label']}({ev['product_code']}) | "
            f"{ev['field']} | old={ev['old_value']} new={ev['new_value']} | "
            f"date={ev['effective_date']} | contracts={ev['contract_codes']}"
        )


if __name__ == "__main__":
    _main()
