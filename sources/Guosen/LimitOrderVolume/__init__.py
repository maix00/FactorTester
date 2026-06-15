"""国信期货 — 限价单/最小开仓下单量 历史调整事件（含期货和期权）。

数据来源：国信期货《各交易所各品种每笔下单数量限制》
https://www.guosenqh.com.cn/main/a/20260519/12800.shtml?id=1391

使用示例：
    from sources.Guosen.LimitOrderVolume import (
        list_all_events,
        list_events_by_exchange,
        list_events_by_product,
        to_dataframe,
    )

    events = list_all_events()
    df = to_dataframe(events)

    # 按交易所筛选
    czce_events = list_events_by_exchange("CZCE")

    # 按品种筛选
    meoh_events = list_events_by_product("甲醇")
"""

from __future__ import annotations

from ._source import SOURCE_DATE, SOURCE_NAME, SOURCE_URL, discover_source_url, fetch_table
from .access import (
    iter_all_events,
    list_all_events,
    list_events_by_exchange,
    list_events_by_product,
    list_events_effective_between,
    list_events_effective_on_or_before,
    list_events_effective_after,
    to_dataframe,
)
from .alter import AlterEvent, Exchange, KNOWN_ALTER_EVENTS, parse_alter_events_from_note

__all__ = [
    # 数据源元信息
    "SOURCE_URL",
    "SOURCE_NAME",
    "SOURCE_DATE",
    # 数据采集
    "discover_source_url",
    "fetch_table",
    # 模型
    "AlterEvent",
    "Exchange",
    "KNOWN_ALTER_EVENTS",
    "parse_alter_events_from_note",
    # 查询
    "list_all_events",
    "list_events_by_exchange",
    "list_events_by_product",
    "list_events_effective_on_or_before",
    "list_events_effective_after",
    "list_events_effective_between",
    "to_dataframe",
    "iter_all_events",
]
