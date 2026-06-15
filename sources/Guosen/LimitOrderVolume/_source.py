"""数据源：国信期货 — 各交易所各品种每笔下单数量限制

自动发现最新链接：
- 汇总页：https://www.guosenqh.com.cn/main/kfzx/pzxx/gpzxxhz/index.shtml
- 从汇总页上通过 BeautifulSoup 解析含「每笔下单数量限制」的 <a> 链接
- 解析出页面日期（URL 格式 .../a/YYYYMMDD/...）

该页面由国信期货有限责任公司维护，汇总各期货交易所每笔下单数量限制信息，
包括限价指令最大下单数量、市价指令最大下单数量，以及历史上「每次最小开仓下单量」
的调整事件（含生效日期）。

页面结构：
- 通过 BeautifulSoup 解析 HTML 表格
- 表格按交易所分节：上海期货交易所、上海国际能源交易中心、大连商品交易所、
  郑州商品交易所、广州期货交易所、中国金融期货交易所
- 每行包含：品种名称、限价指令最大下单数量（手）、市价指令最大下单数量（手）、备注
- 备注列包含两类信息：
  1. 基准规则（如「每笔最小下单数量均为1手」）
  2. 历史调整事件（如「自2026年3月9日夜盘起，每次最小开仓下单数量调整为8手」）

注意：
- 该页面为品种/合约级别的静态汇总快照，不提供 API 接口
- 历史调整事件嵌入在备注文本中，需通过正则解析提取
- 部分调整是合约级别的（如「甲醇期货2606合约」），部分为品种级别的
- 页面内容以交易所官网最新通知为准
"""

from __future__ import annotations

import logging
import re
from datetime import date
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 汇总页 URL
# ---------------------------------------------------------------------------
INDEX_URL = "https://www.guosenqh.com.cn/main/kfzx/pzxx/gpzxxhz/index.shtml"
_STATIC_SOURCE_URL = "https://www.guosenqh.com.cn/main/a/20260519/12800.shtml?id=1391"

# 要查找的链接标题关键词
_LINK_TITLE_KEYWORD = "每笔下单数量限制"

# 页码日期正则：/a/YYYYMMDD/...
_PAGE_DATE_PATTERN = re.compile(r"/a/(\d{8})/")


# ---------------------------------------------------------------------------
# 自动发现来源 URL
# ---------------------------------------------------------------------------

def _parse_date_from_url(url: str) -> date | None:
    """从 /a/YYYYMMDD/ 格式的 URL 中解析日期。"""
    m = _PAGE_DATE_PATTERN.search(url)
    if not m:
        return None
    ds = m.group(1)
    try:
        return date(int(ds[:4]), int(ds[4:6]), int(ds[6:8]))
    except ValueError:
        return None


def _resolve_url(href: str, index_url: str = INDEX_URL) -> str:
    """将相对 href 转为完整 URL。"""
    return urljoin(index_url, href)


def _discover_source_url_via_browser(index_url: str = INDEX_URL) -> tuple[str, date | None]:
    """用浏览器渲染后再从 DOM 中提取目标链接。"""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - optional dependency / env mismatch
        raise RuntimeError(f"浏览器自动发现不可用: {exc}") from exc

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(index_url, wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                # 某些站点会持续发起轻量请求，网络空闲不一定能等到；不阻塞。
                pass
            page.wait_for_timeout(1500)

            anchors = page.locator("a")
            for i in range(anchors.count()):
                anchor = anchors.nth(i)
                text = (anchor.inner_text(timeout=1000) or "").strip()
                if _LINK_TITLE_KEYWORD not in text:
                    continue
                href = (anchor.get_attribute("href") or "").strip()
                if not href:
                    continue
                source_url = _resolve_url(href, index_url)
                source_date = _parse_date_from_url(source_url)
                logger.info("通过浏览器发现最新页: %s (日期=%s)", source_url, source_date)
                return source_url, source_date

            rendered = page.content()
        finally:
            browser.close()

    soup = BeautifulSoup(rendered, "html.parser")
    for a in soup.find_all("a"):
        text = a.get_text(strip=True)
        if _LINK_TITLE_KEYWORD in text:
            href = a.get("href", "").strip()
            if not href:
                continue
            source_url = _resolve_url(href, index_url)
            source_date = _parse_date_from_url(source_url)
            logger.info("通过浏览器渲染 HTML 发现最新页: %s (日期=%s)", source_url, source_date)
            return source_url, source_date

    raise RuntimeError(f"浏览器渲染后仍未找到关键词「{_LINK_TITLE_KEYWORD}」的链接: {index_url}")


def discover_source_url(index_url: str = INDEX_URL) -> tuple[str, date | None]:
    """从国信期货汇总页自动发现最新「各交易所各品种每笔下单数量限制」链接。

    返回 (source_url, source_date)。
    抛出 OSError 若网络不可达或页面无匹配链接。
    """
    try:
        return _discover_source_url_via_browser(index_url)
    except Exception as browser_exc:
        logger.warning("浏览器自动发现失败，改用静态 HTML 解析: %s", browser_exc)

    req = Request(index_url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=15) as resp:
        content = resp.read().decode("utf-8", errors="replace")

    soup = BeautifulSoup(content, "html.parser")
    for a in soup.find_all("a"):
        text = a.get_text(strip=True)
        if _LINK_TITLE_KEYWORD in text:
            href = a.get("href", "").strip()
            if not href:
                continue
            source_url = _resolve_url(href, index_url)
            source_date = _parse_date_from_url(source_url)
            logger.info("发现最新页: %s (日期=%s)", source_url, source_date)
            return source_url, source_date

    raise RuntimeError(
        f"汇总页未找到关键词「{_LINK_TITLE_KEYWORD}」的链接: {index_url}"
    )


def _resolve_source_metadata() -> tuple[str, str]:
    """Resolve the latest source URL/date, falling back to the static snapshot."""
    try:
        source_url, source_date = discover_source_url()
        return source_url, source_date.isoformat() if source_date is not None else ""
    except Exception as exc:  # pragma: no cover - network fallback
        logger.warning("自动发现最新来源失败，回退到静态快照: %s", exc)
        return _STATIC_SOURCE_URL, "2026-05-19"


# ---------------------------------------------------------------------------
# 解析页面表格为 DataFrame
# ---------------------------------------------------------------------------

# 页面表格列名映射
_TABLE_COLUMNS = ["exchange", "product", "limit_order", "market_order", "note"]

# 「没有市价指令」可视为市场订单上限为 0
_NO_MARKET_FLAG = "没有市价指令"


def fetch_table(url: str | None = None) -> "pd.DataFrame":
    """从国信期货页面抓取限价单表格，返回 DataFrame。

    列：exchange, product, limit_order, market_order, note

    pd.read_html 配合 html5lib 可自动处理 rowspan/colspan 合并单元格，
    无需手工维护行状态。
    """
    import io

    import pandas as pd

    target_url = url or SOURCE_URL
    req = Request(target_url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=15) as resp:
        content = resp.read().decode("utf-8", errors="replace")

    tables = pd.read_html(io.StringIO(content), flavor="html5lib")
    if not tables:
        raise RuntimeError(f"页面未找到 <table> 标签: {target_url}")
    df = tables[0]

    # 去掉前两行 multilevel header（「交易所/品种/最大下单数量/备注」+
    # 「限价指令/市价指令」子标题）
    df = df.iloc[2:].copy()
    df.columns = _TABLE_COLUMNS

    # 清理：国信表格中「交易所」列用 colspan=2 渲染（如「上海期货 交易所」），
    # pd.read_html 会将拆分部分放在两行 —— 这里合并连接再清理空格
    df["exchange"] = (
        df["exchange"]
        .astype(str)
        .str.replace(r"\s+", "", regex=True)
    )

    # 前向填充由于 rowspan 产生的 NaN
    for col in ["exchange", "limit_order", "market_order", "note"]:
        df[col] = df[col].replace("", float("nan")).ffill()

    # 将「没有市价指令」映射为 0（方便数值比较），其他保持原样
    df["market_order"] = df["market_order"].replace(_NO_MARKET_FLAG, "0手")

    logger.info("从 %s 解析到 %d 行数据", target_url, len(df))
    return df


def _main() -> None:
    import pandas as pd

    pd.set_option("display.max_rows", None)
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 0)
    pd.set_option("display.max_colwidth", None)

    df = fetch_table()
    print(f"SOURCE_URL: {SOURCE_URL}")
    print(f"SOURCE_DATE: {SOURCE_DATE}")
    print(df.to_string(index=False))


# ---------------------------------------------------------------------------
# 模块级常量
# ---------------------------------------------------------------------------
SOURCE_URL, SOURCE_DATE = _resolve_source_metadata()
SOURCE_NAME: str = "国信期货 — 各品种每笔下单数量限制"


if __name__ == "__main__":
    _main()
