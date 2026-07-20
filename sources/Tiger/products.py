"""First-class Osaka Exchange futures products known without a network call."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tools.products.Futures import Futures, FuturesContract
from tools.products.Product import Product
from tools.products.categories.Category import Category, CategoryTree


@dataclass(frozen=True, slots=True)
class OSEProductSpec:
    code: str
    description: str
    tiger_identifier: str
    multiplier: float
    min_tick: float


_CORE_PRODUCTS = (
    OSEProductSpec(
        code="JNI",
        description="OSE Nikkei 225",
        tiger_identifier="JNImain",
        multiplier=1000.0,
        min_tick=10.0,
    ),
    OSEProductSpec(
        code="JMI",
        description="OSE Mini Nikkei 225",
        tiger_identifier="JMImain",
        multiplier=100.0,
        min_tick=5.0,
    ),
    OSEProductSpec(
        code="JTM",
        description="OSE Mini TOPIX",
        tiger_identifier="JTMmain",
        multiplier=1000.0,
        min_tick=0.25,
    ),
    OSEProductSpec(
        code="JTI",
        description="OSE TOPIX",
        tiger_identifier="JTImain",
        multiplier=10000.0,
        min_tick=0.5,
    ),
    OSEProductSpec(
        code="NK225MC",
        description="OSE Micro Nikkei 225",
        tiger_identifier="NK225MCmain",
        multiplier=10.0,
        min_tick=5.0,
    ),
)


class JPFuturesContract(FuturesContract):
    """One Osaka Exchange futures contract identified by Tiger contract code."""

    def __init__(self, name: str, **fields: Any):
        super().__init__(
            name,
            point_value=fields.get("multiplier"),
            currency="JPY",
            timezone="Asia/Tokyo",
            multiplier=fields.get("multiplier"),
            min_tick=fields.get("min_tick"),
        )
        self.exchange_id = "OSE"
        self.tiger_identifier = fields.get("tiger_identifier") or name.split(".")[0]
        self.desc = fields.get("description") or name


class JPFutures(Futures):
    """OSE main-series product exposed through Tiger's futures identifiers."""

    def __init__(self, name: str, spec: OSEProductSpec):
        super().__init__(
            name,
            point_value=spec.multiplier,
            currency="JPY",
            contract_class=JPFuturesContract,
            timezone="Asia/Tokyo",
            multiplier=spec.multiplier,
            min_tick=spec.min_tick,
        )
        self.code = spec.code
        self.exchange_id = "OSE"
        self.desc = spec.description
        self.tiger_identifier = spec.tiger_identifier

    def supports_adjusted_price(self) -> bool:
        return False

    def supports_term_structure(self) -> bool:
        return False


JP_FUTURES = tuple(
    JPFutures(f"{spec.code}.OSE", spec)
    for spec in _CORE_PRODUCTS
)

JPFuturesExchangeCategory = Category(
    alias="交易所",
    type=JPFutures,
    categories=["OSE"],
)
JPFuturesExchangeCategory.whether_is_in_category = (
    lambda category, product, *_args, **_kwargs:
    category == "OSE" and isinstance(product, JPFutures)
)
JPFuturesExchangeCategory.objs = list(JP_FUTURES)


def get_all_jp_futures() -> list[JPFutures]:
    return list(JP_FUTURES)


def get_jp_futures_tree() -> CategoryTree:
    return JPFuturesExchangeCategory.get_tree_with_parents(
        all_objects=list(JP_FUTURES),
        ancester=Product,
    )
