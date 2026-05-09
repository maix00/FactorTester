"""Term-structure infrastructure for futures products.

The storage model is a normalized snapshot table:

    PRODUCT, TRADING_DAY, CONTRACT_UID, CONTRACT,
    MATURITY_DATE, DAYS_TO_MATURITY, TERM_RANK,
    OPEN, HIGH, LOW, CLOSE, VOLUME, OPEN_INTEREST,
    IS_MAIN

Each row represents one tradable contract for one product on one trading day.
`TERM_RANK` is ordered by maturity within (PRODUCT, TRADING_DAY).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, List, Optional, cast

import pandas as pd


TERM_PRODUCT_COL = 'PRODUCT'
TERM_TRADING_DAY_COL = 'TRADING_DAY'
TERM_CONTRACT_UID_COL = 'CONTRACT_UID'
TERM_CONTRACT_COL = 'CONTRACT'
TERM_MATURITY_COL = 'MATURITY_DATE'
TERM_DAYS_TO_MATURITY_COL = 'DAYS_TO_MATURITY'
TERM_RANK_COL = 'TERM_RANK'
TERM_IS_MAIN_COL = 'IS_MAIN'


@dataclass(frozen=True)
class FuturesTermStructureStore:
    """Reader for a futures term-structure snapshot table."""

    path: str

    def load(
        self,
        product: Optional[str] = None,
        trading_day: Optional[Any] = None,
        columns: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        filters = []
        if product:
            filters.append((TERM_PRODUCT_COL, '==', product))
        if trading_day is not None:
            day = cast(pd.Timestamp, pd.Timestamp(trading_day)).normalize()
            filters.append((TERM_TRADING_DAY_COL, '==', day))
        kwargs = {}
        if filters:
            kwargs['filters'] = filters
        if columns:
            kwargs['columns'] = columns
        return pd.read_parquet(self.path, **kwargs)

    def contract_pool(self, product: str, trading_day: Any, depth: Optional[int] = None) -> pd.DataFrame:
        df = self.load(product=product, trading_day=trading_day)
        if df.empty:
            return df
        df = df.sort_values(TERM_RANK_COL)
        if depth is not None:
            df = df.head(int(depth))
        return df


class FuturesContractTermStructureMixin:
    """Marker/base mixin for contracts that can appear in a term structure."""


class FuturesTermStructureMixin:
    """Mixin for futures products with term-structure snapshot support."""

    term_structure_path: Optional[str] = None

    def get_term_structure_path(self) -> Optional[str]:
        return getattr(self, 'term_structure_path', None)

    def get_term_structure_store(self) -> FuturesTermStructureStore:
        path = self.get_term_structure_path()
        if not path:
            raise ValueError(f"term_structure_path not set for {getattr(self, 'name', type(self).__name__)}")
        return FuturesTermStructureStore(path)

    def get_term_structure(self, trading_day: Any, depth: Optional[int] = None) -> pd.DataFrame:
        """Return contracts for this product/date ordered by maturity."""
        return self.get_term_structure_store().contract_pool(getattr(self, 'name'), trading_day, depth=depth)

    def get_term_structure_contracts(self, trading_day: Any, depth: Optional[int] = None) -> List[Any]:
        """Return contract objects for this product/date ordered by maturity."""
        df = self.get_term_structure(trading_day, depth=depth)
        if df.empty:
            return []
        contract_cls = getattr(self, 'FuturesContractClass')
        return [contract_cls(uid) for uid in df[TERM_CONTRACT_UID_COL].dropna().astype(str)]

    def get_nth_term_contract(self, trading_day: Any, n: int = 0) -> Optional[Any]:
        contracts = self.get_term_structure_contracts(trading_day, depth=int(n) + 1)
        return contracts[int(n)] if len(contracts) > int(n) else None

    def term_spread(self, trading_day: Any, near_rank: int = 0, far_rank: int = 1, column: str = 'CLOSE') -> float:
        """Return near - far for one product/date from the snapshot table."""
        df = self.get_term_structure(trading_day, depth=max(int(near_rank), int(far_rank)) + 1)
        if df.empty or len(df) <= max(int(near_rank), int(far_rank)):
            return float('nan')
        near = df.iloc[int(near_rank)][column]
        far = df.iloc[int(far_rank)][column]
        return float(near - far)

    def term_ratio(self, trading_day: Any, near_rank: int = 0, far_rank: int = 1, column: str = 'CLOSE') -> float:
        """Return near / far - 1 for one product/date from the snapshot table."""
        df = self.get_term_structure(trading_day, depth=max(int(near_rank), int(far_rank)) + 1)
        if df.empty or len(df) <= max(int(near_rank), int(far_rank)):
            return float('nan')
        near = df.iloc[int(near_rank)][column]
        far = df.iloc[int(far_rank)][column]
        return float(near / far - 1) if far else float('nan')

    def term_slope(self, trading_day: Any, depth: int = 4, column: str = 'CLOSE') -> float:
        """Linear slope of value against days-to-maturity."""
        import numpy as np

        df = self.get_term_structure(trading_day, depth=depth)
        df = df[[TERM_DAYS_TO_MATURITY_COL, column]].dropna()
        if len(df) < 2:
            return float('nan')
        x = pd.Series(df[TERM_DAYS_TO_MATURITY_COL]).to_numpy(dtype=float)
        y = pd.Series(df[column]).to_numpy(dtype=float)
        return float(np.polyfit(x, y, 1)[0])
