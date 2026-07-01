from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MarketDataStore:
    load_plan: list[Any] = field(default_factory=list)
    excluded_out_of_range: tuple[Any, ...] = ()
    series_by_product: dict[Any, Any] = field(default_factory=dict)
    raw_prices_table: Any = None
    current_prices_table: Any = None
    market_price_tables: dict[str, Any] = field(default_factory=dict)
    volume_table: Any = None
    included_products: frozenset[Any] | None = None
    historical_field_provider: Any = None
    trading_day_resolver: Any = None
    historical_field_policy: str | None = None
    historical_field_names: tuple[Any, ...] = ()
    historical_field_frames: Any = None
    runtime_info_excluded_product_sets: list[tuple[Any, ...]] = field(default_factory=list)

    def publish_raw(self, raw: dict[str, Any]) -> None:
        self.raw_prices_table = raw.get("raw_prices")
        self.market_price_tables = raw.get("price_tables") or {"close": raw.get("raw_prices")}
        self.historical_field_provider = raw.get("historical_field_provider")
        included_products = raw.get("included_products")
        self.included_products = frozenset(included_products) if included_products is not None else None
        self.excluded_out_of_range = tuple(raw.get("excluded_out_of_range_products", ()))
        self.historical_field_names = tuple(raw.get("historical_field_names", ()))
        self.volume_table = raw.get("volume")
