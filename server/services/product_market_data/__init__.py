"""Port-independent product market-data projections."""

from .contracts import contract_listing, contract_price_series
from .errors import ProductMarketDataError
from .products import product_price_series


def price_series(payload):
    """Dispatch a price-series request without selecting a service instance."""
    if payload.get("contract_uid"):
        return contract_price_series(payload)
    return product_price_series(payload)


__all__ = [
    "ProductMarketDataError",
    "contract_listing",
    "price_series",
]
