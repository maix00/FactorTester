"""Crawl official exchange announcement catalogs into SQLite.

The crawler stores every visible announcement row through
``append_exchange_announcements``. FieldHistory extraction is a later step; this
script only catalogs exchange-published notices and marks likely field-change
candidates.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import ssl
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sources.ExchangeAnnouncements.store import NOTICE_ID_PATTERN, append_exchange_announcements


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)
SHFE_SEARCH_URL = "https://www.shfe.com.cn/api/search/"
FIELD_KEYWORDS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("TransactionFee", "OpenRatioByMoney", ("手续费", "收费")),
    ("Margin", "LongMarginRatioByMoney", ("保证金", "风险管理")),
    ("LimitOrderVolume", "MaxLimitOrderVolume", ("下单数量", "限价单", "市价单", "每次最小")),
    ("TradingHours", "TradingSession", ("交易时间", "夜盘", "休市")),
    ("ContractSpec", "ContractMultiplier", ("合约乘数", "交易单位")),
    ("ContractSpec", "PriceTick", ("最小变动价位", "报价单位")),
    ("PriceLimit", "LimitUpDownRatio", ("涨跌停板",)),
)
PRODUCT_PATTERN = re.compile(r"\b[A-Z]{1,4}\d{3,4}\b|\b[A-Z]{1,4}\b")
NOTICE_ID_RE = re.compile(NOTICE_ID_PATTERN)


@dataclass(frozen=True)
class CrawlIssue:
    exchange: str
    source_url: str
    reason: str


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Crawl official exchange announcement catalogs into SQLite")
    parser.add_argument(
        "--exchange",
        action="append",
        choices=("SHFE", "INE", "GFEX", "CFFEX", "DCE", "CZCE", "ALL"),
        default=[],
        help="Exchange to crawl. Repeatable. ALL expands to supported exchanges.",
    )
    parser.add_argument("--store-key", default="openctp")
    parser.add_argument("--requester-key", default="")
    parser.add_argument("--requester-key-hash", default="")
    parser.add_argument("--agent-name", default="codex-exchange-announcement-crawler")
    parser.add_argument("--max-pages", type=int, default=0, help="Limit pages per exchange; 0 means crawl all known pages")
    parser.add_argument("--start-page", type=int, default=1, help="Start page for paginated crawlers")
    parser.add_argument("--end-page", type=int, default=0, help="Inclusive end page for paginated crawlers")
    parser.add_argument("--page-size", type=int, default=150)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--flush-each-page", action="store_true", help="Write each page immediately; useful for slow browser crawlers")
    args = parser.parse_args(argv)

    exchanges = _expand_exchanges(args.exchange or ["ALL"])
    accessed_at = _now_iso()
    rows: list[dict[str, Any]] = []
    issues: list[CrawlIssue] = []
    for exchange in exchanges:
        try:
            if exchange in {"SHFE", "INE"}:
                rows.extend(_crawl_shfe_like(exchange, accessed_at=accessed_at, max_pages=args.max_pages, page_size=args.page_size))
            elif exchange == "GFEX":
                if args.flush_each_page and not args.dry_run:
                    page_summary = asyncio.run(
                        _crawl_gfex_flush_each_page(
                            accessed_at=accessed_at,
                            max_pages=args.max_pages,
                            start_page=args.start_page,
                            end_page=args.end_page,
                            agent_name=args.agent_name,
                            store_key=args.store_key,
                            requester_key=args.requester_key,
                            requester_key_hash=args.requester_key_hash,
                        )
                    )
                    issues.extend(page_summary.pop("issues"))
                    rows.extend(page_summary.pop("rows"))
                else:
                    rows.extend(
                        asyncio.run(
                            _crawl_gfex(
                                accessed_at=accessed_at,
                                max_pages=args.max_pages,
                                start_page=args.start_page,
                                end_page=args.end_page,
                                agent_name=args.agent_name,
                            )
                        )
                    )
            elif exchange == "CFFEX":
                rows.extend(_crawl_cffex(accessed_at=accessed_at, max_pages=args.max_pages))
            else:
                issues.append(_blocked_issue(exchange))
        except Exception as exc:
            issues.append(CrawlIssue(exchange=exchange, source_url=_entry_url(exchange), reason=f"{type(exc).__name__}: {exc}"))

    for row in rows:
        row["agent_name"] = args.agent_name
    rows = _dedupe_rows(rows)
    summary: dict[str, Any] = {
        "candidate_announcements": len(rows),
        "by_exchange": _count_by_exchange(rows),
        "blocked_or_failed": [issue.__dict__ for issue in issues],
    }
    if not args.dry_run and rows:
        summary["storage"] = append_exchange_announcements(
            rows,
            store_key=args.store_key,
            requester_key=args.requester_key,
            requester_key_hash=args.requester_key_hash,
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not issues else 2


def _expand_exchanges(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value == "ALL":
            result.extend(["SHFE", "INE", "GFEX", "CFFEX", "DCE", "CZCE"])
        else:
            result.append(value)
    return list(dict.fromkeys(result))


def _crawl_shfe_like(exchange: str, *, accessed_at: str, max_pages: int, page_size: int) -> list[dict[str, Any]]:
    site_id = "ine" if exchange == "INE" else "shfe"
    rows: list[dict[str, Any]] = []
    page = 1
    total_pages = 1
    while page <= total_pages:
        payload = {
            "chlid": 1003,
            "cutsize": 1000,
            "dynexpr": [],
            "dynidx": 1,
            "extopt": [],
            "orderby": "-docreltime",
            "page": page,
            "searchword": "chnldesc=publicnotice",
            "size": page_size,
            "siteId": site_id,
        }
        data = _fetch_json(SHFE_SEARCH_URL, payload)
        page_data = data.get("data") or {}
        total_pages = int(page_data.get("totalPages") or 1)
        if max_pages:
            total_pages = min(total_pages, max_pages)
        for item in page_data.get("content") or []:
            if str(item.get("siteid") or "").lower() != site_id:
                continue
            row = _shfe_item_to_row(exchange, item, accessed_at=accessed_at)
            if row is not None:
                rows.append(row)
        page += 1
    return rows


def _shfe_item_to_row(exchange: str, item: dict[str, Any], *, accessed_at: str) -> dict[str, Any] | None:
    title = _clean_text(str(item.get("doctitle") or ""))
    raw_text = _clean_text(str(item.get("doccontent") or ""))
    source_url = urljoin("https://www.shfe.com.cn", str(item.get("docpuburl") or ""))
    notice_id = _notice_id(title + raw_text)
    if not notice_id:
        return None
    published_date = _normalise_date(str(item.get("docreltime") or item.get("docpubtime") or ""))
    return _build_row(
        exchange=exchange,
        source_url=source_url,
        accessed_at=accessed_at,
        published_date=published_date,
        notice_id=notice_id,
        title=title,
        category=str(item.get("chnldesc") or "publicnotice"),
        raw_text=raw_text,
    )


async def _crawl_gfex(
    *,
    accessed_at: str,
    max_pages: int,
    start_page: int,
    end_page: int,
    agent_name: str,
) -> list[dict[str, Any]]:
    from playwright.async_api import async_playwright

    rows: list[dict[str, Any]] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(ignore_https_errors=True, locale="zh-CN", user_agent=USER_AGENT)
        try:
            first_url = "https://www.gfex.com.cn/gfex/tzts/list_yw.shtml"
            await page.goto(first_url, wait_until="networkidle", timeout=30000)
            first_html = await page.content()
            for index in _page_range(_gfex_page_count(first_html), max_pages=max_pages, start_page=start_page, end_page=end_page):
                list_url = first_url if index == 1 else f"https://www.gfex.com.cn/gfex/tzts/list_yw_{index}.shtml"
                rows.extend(await _crawl_gfex_page(page, list_url, accessed_at=accessed_at, agent_name=agent_name))
        finally:
            await browser.close()
    return _dedupe_rows(rows)


async def _crawl_gfex_flush_each_page(
    *,
    accessed_at: str,
    max_pages: int,
    start_page: int,
    end_page: int,
    agent_name: str,
    store_key: str,
    requester_key: str,
    requester_key_hash: str,
) -> dict[str, Any]:
    from playwright.async_api import async_playwright

    rows: list[dict[str, Any]] = []
    issues: list[CrawlIssue] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(ignore_https_errors=True, locale="zh-CN", user_agent=USER_AGENT)
        try:
            first_url = "https://www.gfex.com.cn/gfex/tzts/list_yw.shtml"
            await page.goto(first_url, wait_until="networkidle", timeout=30000)
            first_html = await page.content()
            for index in _page_range(_gfex_page_count(first_html), max_pages=max_pages, start_page=start_page, end_page=end_page):
                list_url = first_url if index == 1 else f"https://www.gfex.com.cn/gfex/tzts/list_yw_{index}.shtml"
                try:
                    page_rows = _dedupe_rows(
                        await _crawl_gfex_page(page, list_url, accessed_at=accessed_at, agent_name=agent_name)
                    )
                    for row in page_rows:
                        row["agent_name"] = agent_name
                    if page_rows:
                        append_exchange_announcements(
                            page_rows,
                            store_key=store_key,
                            requester_key=requester_key,
                            requester_key_hash=requester_key_hash,
                        )
                    rows.extend(page_rows)
                except Exception as exc:
                    issues.append(CrawlIssue(exchange="GFEX", source_url=list_url, reason=f"{type(exc).__name__}: {exc}"))
        finally:
            await browser.close()
    return {"rows": rows, "issues": issues}


async def _crawl_gfex_page(page: Any, list_url: str, *, accessed_at: str, agent_name: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    await page.goto(list_url, wait_until="networkidle", timeout=30000)
    links = await page.eval_on_selector_all(
        "a[href]",
        """els => els.map(a => ({
            text: (a.innerText || a.textContent || '').trim(),
            href: a.href
        })).filter(x => x.href.includes('/gfex/tzts/') && x.href.endsWith('.shtml') && x.text)""",
    )
    for link in links:
        href = str(link["href"])
        title = _clean_text(str(link["text"]))
        if not title or title in {"通知公告"}:
            continue
        await page.goto(href, wait_until="networkidle", timeout=30000)
        detail_html = await page.content()
        detail_text = _html_text(detail_html)
        row = _build_row(
            exchange="GFEX",
            source_url=href,
            accessed_at=accessed_at,
            published_date=_date_from_text(detail_text) or _date_from_url(href),
            notice_id=_notice_id(title + detail_text),
            title=title,
            category="通知公告",
            raw_text=detail_text,
            parser_notes=f"browser crawl via Playwright by {agent_name}",
        )
        if row is not None:
            rows.append(row)
    return rows


def _crawl_cffex(*, accessed_at: str, max_pages: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for section, category in (("jysgg", "交易所公告"), ("jystz", "交易所通知")):
        first_url = f"http://www.cffex.com.cn/cn/{section}.html"
        first_html = _fetch_text(first_url)
        page_count = _cffex_page_count(first_html, section)
        if max_pages:
            page_count = min(page_count, max_pages)
        for page_num in range(1, page_count + 1):
            url = first_url if page_num == 1 else f"http://www.cffex.com.cn/cn/{section}_{page_num}.html"
            html = first_html if page_num == 1 else _fetch_text(url)
            for title, href in _list_links(html, base_url=url, href_contains=f"/cn/{section}/"):
                detail_text = _html_text(_fetch_text(href))
                row = _build_row(
                    exchange="CFFEX",
                    source_url=href,
                    accessed_at=accessed_at,
                    published_date=_date_from_url(href) or _date_from_text(detail_text),
                    notice_id=_notice_id(title + detail_text),
                    title=title,
                    category=category,
                    raw_text=detail_text,
                )
                if row is not None:
                    rows.append(row)
    return _dedupe_rows(rows)


def _build_row(
    *,
    exchange: str,
    source_url: str,
    accessed_at: str,
    published_date: str,
    notice_id: str,
    title: str,
    category: str,
    raw_text: str,
    parser_notes: str = "",
) -> dict[str, Any] | None:
    if not notice_id:
        return None
    text = title + "\n" + raw_text
    field_groups, field_names = _field_tags(text)
    products, contracts = _instrument_tags(text)
    return {
        "announcement_id": notice_id,
        "exchange": exchange,
        "source_url": source_url,
        "source_accessed_at": accessed_at,
        "published_date": published_date,
        "notice_id": notice_id,
        "title": title,
        "category": category,
        "summary": raw_text[:500],
        "raw_text": raw_text,
        "field_change_candidate": bool(field_groups),
        "field_groups": field_groups,
        "field_names": field_names,
        "products": products,
        "contracts": contracts,
        "parser_notes": parser_notes,
    }


def _blocked_issue(exchange: str) -> CrawlIssue:
    return CrawlIssue(
        exchange=exchange,
        source_url=_entry_url(exchange),
        reason="official site currently returns an anti-bot challenge/empty browser DOM from this environment; use a stateful browser fetcher and append_exchange_announcements when solved",
    )


def _entry_url(exchange: str) -> str:
    return {
        "DCE": "https://www.dce.com.cn/dce/channel/list/244.html",
        "CZCE": "https://www.czce.com.cn/cn/gyjys/jysdt/ggytz/H770301index_1.htm",
        "GFEX": "https://www.gfex.com.cn/gfex/tzts/list_yw.shtml",
        "CFFEX": "http://www.cffex.com.cn/cn/jysgg.html",
        "SHFE": SHFE_SEARCH_URL,
        "INE": SHFE_SEARCH_URL,
    }.get(exchange, "")


def _fetch_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    req = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urlopen(req, timeout=30) as response:
                text = response.read().decode("utf-8", "ignore")
            return json.loads(text)
        except Exception as exc:
            last_error = exc
            time.sleep(1 + attempt)
    assert last_error is not None
    raise last_error


def _fetch_text(url: str) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9"})
    context = ssl._create_unverified_context() if url.startswith("https://www.gfex.com.cn") else None
    with urlopen(req, timeout=30, context=context) as response:
        raw = response.read()
    return raw.decode("utf-8", "ignore")


def _list_links(html: str, *, base_url: str, href_contains: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    links: list[tuple[str, str]] = []
    for anchor in soup.select("a[href]"):
        title = _clean_text(anchor.get_text(" ", strip=True))
        href = urljoin(base_url, str(anchor.get("href")))
        if title and href_contains in href:
            links.append((title, href))
    return links


def _html_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    for selector in (
        ".article_content",
        ".article-content",
        ".detail_content",
        ".detail_cont",
        ".notice_details",
        ".TRS_Editor",
        ".content_main",
        ".main_content",
    ):
        node = soup.select_one(selector)
        if node is not None:
            return _trim_article_chrome(_clean_text(node.get_text("\n", strip=True)))
    return _trim_article_chrome(_clean_text(soup.get_text("\n", strip=True)))


def _trim_article_chrome(text: str) -> str:
    text = re.sub(r"^.*?分享：\s*(?:微信二维码)?", "", text)
    text = re.sub(r"上一篇：.*$", "", text)
    text = re.sub(r"下一篇：.*$", "", text)
    return text.strip()


def _field_tags(text: str) -> tuple[list[str], list[str]]:
    groups: list[str] = []
    names: list[str] = []
    for group, name, keywords in FIELD_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            groups.append(group)
            names.append(name)
    return sorted(set(groups)), sorted(set(names))


def _instrument_tags(text: str) -> tuple[list[str], list[str]]:
    tags = sorted(set(PRODUCT_PATTERN.findall(text)))
    contracts = [tag for tag in tags if re.search(r"\d", tag)]
    products = [tag for tag in tags if not re.search(r"\d", tag)]
    return products, contracts


def _notice_id(text: str) -> str:
    match = NOTICE_ID_RE.search(text)
    return match.group(0) if match else ""


def _normalise_date(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    text = text.replace(".", "-").replace("/", "-")
    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if not match:
        return ""
    return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"


def _date_from_text(text: str) -> str:
    patterns = (
        r"(\d{4})年(\d{1,2})月(\d{1,2})日",
        r"(\d{4})[.-](\d{1,2})[.-](\d{1,2})",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    return ""


def _date_from_url(url: str) -> str:
    match = re.search(r"/(20\d{2})(\d{2})(\d{2})/", url)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    match = re.search(r"/(20\d{2})(\d{2})/", url)
    if match:
        return f"{match.group(1)}-{match.group(2)}-01"
    return ""


def _gfex_page_count(html: str) -> int:
    matches = [int(value) for value in re.findall(r"list_yw_(\d+)\.shtml", html)]
    text_match = re.search(r"共(\d+)页", _html_text(html))
    if text_match:
        matches.append(int(text_match.group(1)))
    return max(matches or [1])


def _cffex_page_count(html: str, section: str) -> int:
    pattern = rf"{re.escape(section)}_(\d+)\.html"
    matches = [int(value) for value in re.findall(pattern, html)]
    text_match = re.search(r"共(\d+)页", _html_text(html))
    if text_match:
        matches.append(int(text_match.group(1)))
    total_match = re.search(r"jump\((\d+)\)", html)
    if total_match:
        matches.append(int(total_match.group(1)))
    next_match = re.search(r"nextPage\(\d+,\s*(\d+)\)", html)
    if next_match:
        matches.append(int(next_match.group(1)))
    return max(matches or [1])


def _page_range(page_count: int, *, max_pages: int, start_page: int, end_page: int) -> range:
    start = max(1, start_page)
    end = page_count
    if max_pages:
        end = min(end, max_pages)
    if end_page:
        end = min(end, end_page)
    if end < start:
        return range(0)
    return range(start, end + 1)


def _stable_url_id(url: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", url.strip("/")).strip("_")


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value)).strip()


def _dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row["announcement_id"])
        old = deduped.get(key)
        if old is None or len(str(row.get("raw_text") or "")) > len(str(old.get("raw_text") or "")):
            deduped[key] = row
    return list(deduped.values())


def _count_by_exchange(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        exchange = str(row["exchange"])
        counts[exchange] = counts.get(exchange, 0) + 1
    return counts


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


if __name__ == "__main__":
    raise SystemExit(main())
