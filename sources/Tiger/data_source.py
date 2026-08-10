"""Tiger source-owned catalog declaration.

Tiger exposes a live OSE level-2 order-book connector.  It is deliberately
not registered as a historical MIN1/DAY1 execution provider.
"""

from __future__ import annotations

from typing import Any

from tools.data.source_catalog import (
    DataSourceDeclaration,
    DataSourceMember,
    DataSourceMode,
    register_data_source,
)

from .products import JPFutures


def _is_jp_futures(product: Any) -> bool:
    return isinstance(product, JPFutures)


TIGER_OSE_L2 = DataSourceMember(
    key="TigerOSEFuturesL2",
    label="Tiger OSE Futures L2",
    supports=_is_jp_futures,
    # Catalog reads never launch the connector.  Availability is established
    # by an explicit, frozen Tiger probe instead.
    available=lambda _product: False,
    mode=DataSourceMode(
        key="realtime_l2",
        title_zh="实时 L2 行情",
        sampling_mode="snapshot",
        frequency=None,
        data_kind="order_book",
        market_depth="l2",
        delivery_mode="live_stream",
    ),
    timezone="Asia/Tokyo",
)

TIGER = DataSourceDeclaration(
    key="Tiger",
    label="Tiger",
    origins=frozenset({"local"}),
    provider_kind="live_connector",
    member_loader=lambda: (TIGER_OSE_L2,),
    empty_status="not_probed",
    connector_key="Tiger",
)
register_data_source(TIGER)

__all__ = ["TIGER", "TIGER_OSE_L2"]
