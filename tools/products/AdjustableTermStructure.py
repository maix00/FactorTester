"""Term-structure infrastructure for futures products.

The storage model is a normalized snapshot table:

    PRODUCT, TRADING_DAY, CONTRACT_UID, CONTRACT,
    MATURITY_DATE, DAYS_TO_MATURITY, TERM_RANK,
    OPEN, HIGH, LOW, CLOSE, VWAP, SETTLEMENT_PRICE, PRE_SETTLEMENT_PRICE,
    VOLUME, OPEN_INTEREST,
    IS_MAIN

Each row represents one tradable contract for one product on one trading day.
`TERM_RANK` is ordered by maturity within (PRODUCT, TRADING_DAY).
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
import os
from typing import Any, Dict, Iterable, List, Optional, TypeVar, cast

import numpy as np
import pandas as pd

_T = TypeVar("_T")


def tqdm(iterable: Iterable[_T], *args: Any, **kwargs: Any) -> Iterable[_T]:
    try:
        progress = getattr(import_module("tqdm"), "tqdm")
    except ModuleNotFoundError:  # pragma: no cover - exercised in slim worker envs
        return iterable
    return cast(Iterable[_T], progress(iterable, *args, **kwargs))


TERM_PRODUCT_COL = 'PRODUCT'
TERM_TRADING_DAY_COL = 'TRADING_DAY'
TERM_CONTRACT_UID_COL = 'CONTRACT_UID'
TERM_CONTRACT_COL = 'CONTRACT'
TERM_MATURITY_COL = 'MATURITY_DATE'
TERM_DAYS_TO_MATURITY_COL = 'DAYS_TO_MATURITY'
TERM_RANK_COL = 'TERM_RANK'
TERM_IS_MAIN_COL = 'IS_MAIN'
TERM_IS_SECONDARY_COL = 'IS_SECONDARY'


@dataclass(frozen=True)
class TermStructureStore:
    """通用期限结构快照表读取器。

    子类化后可针对特定品种类型（期货/期权等）添加专属方法。
    当前提供核心的 load() 和 contract_pool()。
    """

    path: str

    def load(
        self,
        product: Optional[str] = None,
        trading_day: Optional[Any] = None,
        columns: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        from tools.data.hub import DataHub

        frame = DataHub.get_instance().load("term_structure", self.path)
        mask = pd.Series(True, index=frame.index)
        if product:
            mask &= frame[TERM_PRODUCT_COL] == product
        if trading_day is not None:
            day = cast(pd.Timestamp, pd.Timestamp(trading_day)).normalize()
            mask &= pd.to_datetime(frame[TERM_TRADING_DAY_COL]).dt.normalize() == day
        selected = frame.loc[mask]
        if columns is not None:
            selected = selected.loc[:, columns]
        return selected.copy()

    def contract_pool(self, product: str, trading_day: Any, depth: Optional[int] = None) -> pd.DataFrame:
        df = self.load(product=product, trading_day=trading_day)
        if df.empty:
            return df
        df = df.sort_values(TERM_RANK_COL)
        if depth is not None:
            df = df.head(int(depth))
        return df





class AdjustableContractMixin:
    """Base mixin for contract-like products that can participate in adjustment chains."""

    # Product/category tree should skip technical base layers like this mixin.
    _is_hidden_product_tree_class = True

    def is_term_contract(self) -> bool:
        return True

    def get_parent_product(self, term_structure_paths: Optional[list[str]] = None):
        """Return the parent Futures product for this contract-like object, if resolvable."""
        if getattr(self, '_parent_product_loaded', False):
            return getattr(self, '_parent_product_cache', None)
        parent = resolve_term_structure_product(self, term_structure_paths=term_structure_paths)
        setattr(self, '_parent_product_cache', parent)
        setattr(self, '_parent_product_loaded', True)
        return parent

    @property
    def parent_product(self):
        """Lazy parent Futures product resolved from the term-structure registry."""
        return self.get_parent_product()


class AdjustableProductMixin:
    """Base mixin for products that support adjustment/term-structure style helpers."""

    # Product/category tree should skip technical base layers like this mixin.
    _is_hidden_product_tree_class = True

    term_structure_path: Optional[str] = None

    def supports_adjusted_price(self) -> bool:
        return True

    def supports_term_structure(self) -> bool:
        return True

    def get_term_structure_path(self, curve_variant: str = "listed_contracts") -> Optional[str]:
        return getattr(self, 'term_structure_path', None)

    def get_term_structure_store(self, curve_variant: str = "listed_contracts") -> TermStructureStore:
        path = self.get_term_structure_path(curve_variant)
        if not path:
            raise ValueError(f"term_structure_path not set for {getattr(self, 'name', type(self).__name__)}")
        return TermStructureStore(path)

    def get_term_structure(
        self,
        trading_day: Any,
        depth: Optional[int] = None,
        curve_variant: str = "listed_contracts",
    ) -> pd.DataFrame:
        """Return contracts for this product/date ordered by maturity."""
        return self.get_term_structure_store(curve_variant).contract_pool(getattr(self, 'name'), trading_day, depth=depth)

    def get_term_structures(
        self,
        trading_days: Iterable[Any],
        depth: Optional[int] = None,
        curve_variant: str = "listed_contracts",
    ) -> Dict[pd.Timestamp, pd.DataFrame]:
        """Return one maturity-ranked curve per requested trading day."""
        days = self._normalize_trading_days(trading_days)
        if len(days) == 0:
            return {}
        df = self._load_term_structure_days(
            days,
            depth=depth,
            curve_variant=curve_variant,
        )
        if df.empty:
            return {}
        return {
            cast(pd.Timestamp, pd.Timestamp(day).normalize()): cast(
                pd.DataFrame,
                curve.reset_index(drop=True),
            )
            for day, curve in df.groupby(TERM_TRADING_DAY_COL, sort=False)
        }

    def get_term_structure_contracts(
        self,
        trading_day: Any,
        depth: Optional[int] = None,
        curve_variant: str = "listed_contracts",
    ) -> List[Any]:
        """Return contract objects for this product/date ordered by maturity."""
        df = self.get_term_structure(trading_day, depth=depth, curve_variant=curve_variant)
        if df.empty:
            return []
        contract_cls = getattr(self, 'contract_class')
        return [contract_cls(uid) for uid in df[TERM_CONTRACT_UID_COL].dropna().astype(str)]

    def get_nth_term_contract(self, trading_day: Any, n: int = 0) -> Optional[Any]:
        contracts = self.get_term_structure_contracts(trading_day, depth=int(n) + 1)
        return contracts[int(n)] if len(contracts) > int(n) else None

    def get_contract_list(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        获取品种的全部合约列表（去重，按开始日期排序）。

        默认实现：从 TermStructureStore 按 (CONTRACT_UID, min/max TRADING_DAY) 聚合。
        子类（如 Futures）可覆写以使用 roller_info 等更精确的数据源。

        返回：
            [{contract, uid, desc, start, end, start_ts, end_ts}, ...]
        """
        import pandas as _pd

        store = self.get_term_structure_store()
        df = store.load(
            product=getattr(self, 'name', ''),
            columns=[TERM_CONTRACT_UID_COL, TERM_CONTRACT_COL, TERM_TRADING_DAY_COL],
        )
        if df.empty:
            return []

        grouped = df.groupby(TERM_CONTRACT_UID_COL).agg({
            TERM_CONTRACT_COL: 'first',
            TERM_TRADING_DAY_COL: ['min', 'max'],
        })
        grouped.columns = [c[-1] for c in grouped.columns]
        grouped = cast(pd.DataFrame, grouped)
        grouped = cast(pd.DataFrame, grouped.sort_values(by='min'))

        req_start: pd.Timestamp | None = cast(pd.Timestamp, pd.Timestamp(start_date)).normalize() if start_date else None
        req_end: pd.Timestamp | None = cast(pd.Timestamp, pd.Timestamp(end_date)).normalize() if end_date else None

        min_days = pd.to_datetime(grouped['min']).dt.normalize()
        max_days = pd.to_datetime(grouped['max']).dt.normalize()
        mask = pd.Series(True, index=grouped.index)
        if req_start is not None:
            mask &= max_days >= req_start
        if req_end is not None:
            mask &= min_days <= req_end
        filtered = grouped.loc[mask].copy()
        filtered['min'] = pd.to_datetime(filtered['min'])
        filtered['max'] = pd.to_datetime(filtered['max'])

        contracts: list[dict[str, Any]] = []
        for row in tqdm(
            filtered.itertuples(index=True),
            total=len(filtered),
            desc=f"Build contract list {getattr(self, 'name', 'product')}",
        ):
            start = pd.Timestamp(cast(Any, row.min))
            end = pd.Timestamp(cast(Any, row.max))
            contracts.append({
                'contract': str(row.first),
                'uid': str(row.Index),
                'start': start.strftime('%Y-%m-%d'),
                'end': end.strftime('%Y-%m-%d'),
                'start_ts': int(start.timestamp() * 1000),
                'end_ts': int(end.timestamp() * 1000),
            })

        return contracts

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

    @staticmethod
    def _normalize_trading_days(index: Iterable[Any]) -> pd.DatetimeIndex:
        idx = pd.DatetimeIndex(pd.to_datetime(list(index)))
        if len(idx) == 0:
            return idx
        # Parquet trading_day is stored as tz-naive midnight; align incoming
        # timestamps (often tz-aware from market data) to the same representation.
        if idx.tz is not None:
            idx = idx.tz_localize(None)
        normalized = getattr(idx, 'normalize')()
        return cast(pd.DatetimeIndex, normalized).unique().sort_values()

    def _load_term_structure_days(
        self,
        trading_days: Iterable[Any],
        *,
        depth: Optional[int] = None,
        curve_variant: str = "listed_contracts",
    ) -> pd.DataFrame:
        days = self._normalize_trading_days(trading_days)
        if len(days) == 0:
            return pd.DataFrame()
        df = self.get_term_structure_store(curve_variant).load(
            product=getattr(self, 'name'),
        )
        if df.empty:
            return df
        day_set: set[pd.Timestamp] = set(days)
        df = cast(pd.DataFrame, df[df[TERM_TRADING_DAY_COL].isin(list(day_set))])
        if df.empty:
            return df
        df = cast(pd.DataFrame, df.sort_values(by=[TERM_TRADING_DAY_COL, TERM_RANK_COL]))
        if depth is not None:
            df = cast(pd.DataFrame, df[df[TERM_RANK_COL] < int(depth)])
        return df

    def term_spread_series(
        self,
        trading_days: Iterable[Any],
        near_rank: int = 0,
        far_rank: int = 1,
        column: str = 'CLOSE',
    ) -> pd.Series:
        days = self._normalize_trading_days(trading_days)
        out = pd.Series(np.nan, index=days, dtype=float)
        if len(days) == 0:
            return out

        near_rank = int(near_rank)
        far_rank = int(far_rank)
        depth = max(near_rank, far_rank) + 1
        df = self._load_term_structure_days(days, depth=depth)
        if df.empty:
            return out

        near = cast(pd.DataFrame, df[df[TERM_RANK_COL] == near_rank][[TERM_TRADING_DAY_COL, column]]).set_index(TERM_TRADING_DAY_COL)[column]
        far = cast(pd.DataFrame, df[df[TERM_RANK_COL] == far_rank][[TERM_TRADING_DAY_COL, column]]).set_index(TERM_TRADING_DAY_COL)[column]
        out.loc[near.index.intersection(out.index)] = (near - far).reindex(near.index.intersection(out.index)).astype(float)
        return out

    def term_ratio_series(
        self,
        trading_days: Iterable[Any],
        near_rank: int = 0,
        far_rank: int = 1,
        column: str = 'CLOSE',
    ) -> pd.Series:
        days = self._normalize_trading_days(trading_days)
        out = pd.Series(np.nan, index=days, dtype=float)
        if len(days) == 0:
            return out

        near_rank = int(near_rank)
        far_rank = int(far_rank)
        depth = max(near_rank, far_rank) + 1
        df = self._load_term_structure_days(days, depth=depth)
        if df.empty:
            return out

        near = cast(pd.DataFrame, df[df[TERM_RANK_COL] == near_rank][[TERM_TRADING_DAY_COL, column]]).set_index(TERM_TRADING_DAY_COL)[column]
        far = cast(pd.DataFrame, df[df[TERM_RANK_COL] == far_rank][[TERM_TRADING_DAY_COL, column]]).set_index(TERM_TRADING_DAY_COL)[column]
        ratio = (near / far) - 1.0
        ratio = ratio.where(far != 0)
        out.loc[ratio.index.intersection(out.index)] = ratio.reindex(ratio.index.intersection(out.index)).astype(float)
        return out

    def term_slope_series(
        self,
        trading_days: Iterable[Any],
        depth: int = 4,
        column: str = 'CLOSE',
    ) -> pd.Series:
        days = self._normalize_trading_days(trading_days)
        out = pd.Series(np.nan, index=days, dtype=float)
        if len(days) == 0:
            return out

        depth = int(depth)
        if depth < 2:
            return out

        df = self._load_term_structure_days(days, depth=depth)
        if df.empty:
            return out
        df = df[[TERM_TRADING_DAY_COL, TERM_DAYS_TO_MATURITY_COL, column]].dropna()
        if df.empty:
            return out

        def _slope(g: pd.DataFrame) -> float:
            if len(g) < 2:
                return float('nan')
            x = pd.Series(g[TERM_DAYS_TO_MATURITY_COL]).to_numpy(dtype=float)
            y = pd.Series(g[column]).to_numpy(dtype=float)
            return float(np.polyfit(x, y, 1)[0])

        slopes = df.groupby(TERM_TRADING_DAY_COL, sort=False).apply(_slope)
        slopes = cast(pd.Series, slopes)
        out.loc[slopes.index.intersection(out.index)] = slopes.reindex(slopes.index.intersection(out.index)).astype(float)
        return out


# ═══════════════════════════════════════════════════════════════════
# 模块级工具：按 CONTRACT_UID 查找 PRODUCT（用于合约 → 品种 desc 继承）
# ═══════════════════════════════════════════════════════════════════

# {path: {contract_uid: product_name}}
_contract_product_cache: dict = {}
_registered_term_products_by_name: dict[str, Any] = {}
_registered_term_contracts_by_name: dict[str, Any] = {}
_registered_term_paths: list[str] = []


def invalidate_term_structure_path(path: str) -> None:
    """Drop process-local indexes after an artifact is atomically replaced."""
    _contract_product_cache.pop(str(path), None)


def register_term_structure_product(product: Any) -> None:
    """Register one term-structure product for fast contract -> product lookup."""
    product_name = getattr(product, 'name', None)
    if product_name:
        _registered_term_products_by_name[str(product_name)] = product
    getter = getattr(product, 'get_term_structure_path', None)
    if not callable(getter):
        return
    try:
        path = getter()
    except Exception:
        return
    if path and path not in _registered_term_paths:
        _registered_term_paths.append(path)


def register_term_structure_contract(contract: Any) -> None:
    """Register one term-structure contract for fast parent lookup."""
    contract_name = getattr(contract, 'name', None)
    if contract_name:
        _registered_term_contracts_by_name[str(contract_name)] = contract


def get_contract_product_map(path: str) -> dict:
    """
    从 term structure parquet 构建 {contract_uid: product_name} 映射。

    结果按 path 缓存（term structure parquet 不常变），多次调用不重复 I/O。
    """
    if path not in _contract_product_cache:
        # A registered path may be an optional derived artifact that has not
        # been materialized on this machine yet.  Missing metadata means the
        # contract is unresolved; it must not turn a parent-product lookup
        # into an unrelated FileNotFoundError.
        if not os.path.isfile(path):
            _contract_product_cache[path] = {}
            return {}
        store = TermStructureStore(path)
        df = store.load(columns=[TERM_CONTRACT_UID_COL, TERM_PRODUCT_COL])
        if df.empty:
            _contract_product_cache[path] = {}
        else:
            # 去重：每个 contract_uid 只保留第一个 product
            dedup = df[[TERM_CONTRACT_UID_COL, TERM_PRODUCT_COL]].dropna()
            dedup = dedup.drop_duplicates(subset=[TERM_CONTRACT_UID_COL], keep='first')
            _contract_product_cache[path] = {
                str(uid): str(product)
                for uid, product in zip(dedup[TERM_CONTRACT_UID_COL], dedup[TERM_PRODUCT_COL])
            }
    return _contract_product_cache[path]


def lookup_contract_product(contract_uid: str, term_structure_paths: list) -> Optional[str]:
    """
    在所有 term structure path 中查找 contract_uid 所属的 PRODUCT。

    返回找到的第一个 PRODUCT 名，未找到返回 None。
    """
    for path in term_structure_paths:
        mapping = get_contract_product_map(path)
        if contract_uid in mapping:
            return mapping[contract_uid]
    return None


def _collect_term_structure_paths() -> list[str]:
    return list(_registered_term_paths)


def _get_registered_product(product_name: str):
    if not product_name:
        return None
    return _registered_term_products_by_name.get(str(product_name))


def _get_registered_contract(contract_name: str):
    if not contract_name:
        return None
    return _registered_term_contracts_by_name.get(str(contract_name))


def resolve_term_structure_product(contract_or_uid: Any, term_structure_paths: Optional[list[str]] = None):
    """Resolve a contract-like object or uid to its parent Futures product instance."""
    if contract_or_uid is None:
        return None

    contract_uid = getattr(contract_or_uid, 'name', None) or str(contract_or_uid)
    if not contract_uid:
        return None

    candidate = contract_or_uid if not isinstance(contract_or_uid, str) else None
    if candidate is None:
        candidate = _get_registered_contract(contract_uid) or _get_registered_product(contract_uid)
    if candidate is None:
        return None
    try:
        if candidate is not None and not bool(getattr(candidate, 'is_term_contract', lambda: False)()):
            return candidate
    except Exception:
        if candidate is not None:
            return candidate

    paths = list(term_structure_paths or [])
    if not paths:
        paths = _collect_term_structure_paths()
    if not paths:
        return None

    product_name = lookup_contract_product(str(contract_uid), paths)
    if not product_name:
        return None
    return _get_registered_product(product_name)
