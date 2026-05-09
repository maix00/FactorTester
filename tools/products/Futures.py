"""
期货产品模块

提供 FuturesContract（具体合约）和 Futures（主办合约／主指数合约）两层结构。
Futures 通过 roller_info 表维护「历史交易日 → 对应主办合约」的映射关系。

roller_info 的闲置释放由 tools.base.IdleResourceManager 统一管理。
"""
import pandas as pd
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from datetime import datetime

from tools.products.Product import Product
from tools.base.IdleResourceManager import IdleResourceManager
from tools.products.FuturesTermStructure import (
    FuturesContractTermStructureMixin,
    FuturesTermStructureMixin,
)


class FuturesContract(FuturesContractTermStructureMixin, Product):
    """具体期货合约。一个 FuturesContract 对应一个具体到期日的合约代码，如 'IF2412.CFE'。"""
    def __init__(self, name: str, point_value: Optional[int] = None, currency: Optional[str] = None, *args, **kwargs):
        super().__init__(name, point_value, currency, *args, **kwargs)


class Futures(FuturesTermStructureMixin, Product):
    """
    期货品种类（主力合约）。

    一个 Futures 对应一个品种代码（如 'IF.CFE'），它在不同时间对应不同的
    FuturesContract。

    全量 roller_info 由 IdleResourceManager 按 path 缓存、按 idle 释放。
    self.roller_info 是缓存的切片（PRODUCT == self.name），缓存释放后自动失效。

    实例属性：
        roller_info      (DataFrame|None) : 当前品种的合约映射切片（从全局缓存筛选），闲置后随缓存释放
        FuturesContractClass (type)       : 用于创建具体合约对象的类
    """
    _ROLLER_INFO_IDLE_TTL = 10  # 全局缓存闲置多少秒后释放

    def __init__(self, name: str, point_value: Optional[int] = None, currency: Optional[str] = None,
                 roller_info_path: Optional[str] = None,
                 term_structure_path: Optional[str] = None,
                 FuturesContractClass: type = FuturesContract, *args, **kwargs):
        if not hasattr(self, '_initialized'):
            super().__init__(name, point_value, currency, *args, **kwargs)
            self.roller_info_path = roller_info_path
            self.term_structure_path = term_structure_path
            self.roller_info: Optional[pd.DataFrame] = None
            self.FuturesContractClass = FuturesContractClass

    def _ensure_roller_info(self):
        """
        确保 self.roller_info 可用。
        从 IdleResourceManager 的全局缓存中拿全量数据（按 path 去重），
        筛出当前品种的切片赋给 self.roller_info。
        全局缓存释放后 self.roller_info 即为失效视图，下次调用会重新加载。
        """
        manager = IdleResourceManager.get_instance()
        path = self.get_roller_info_path()
        if not path:
            raise ValueError(f"roller_info_path not set for {self.name}")

        # 先 touch（无论是否已有缓存，更新该 path 的 last_access）
        manager.touch('roller_info', path)

        # 如果 self.roller_info 仍有效（底层缓存未被释放），直接返回
        if self.roller_info is not None:
            return

        # 从全局缓存加载全量 roller_info（多个品种共享同一个 path）
        ri = manager.load('roller_info', path, ttl=self._ROLLER_INFO_IDLE_TTL)
        assert ri is not None
        ri['STARTDATE'] = pd.to_datetime(ri['STARTDATE'])
        ri['ENDDATE'] = pd.to_datetime(ri['ENDDATE'])

        # 切片：只保留当前品种
        subset = ri[ri['PRODUCT'] == self.name].sort_values(by='STARTDATE')
        self.roller_info = subset if not subset.empty else None

    def get_contract_row_from_trading_day(self, trading_day: datetime | str) -> Optional[pd.Series]:
        """
        根据交易日返回对应主力合约的 roller_info 行。

        若交易日早于映射表第一行或超出最后一行 ENDDATE，返回 None；
        否则用 searchsorted 二分查找定位合约行。
        """
        self._ensure_roller_info()
        if self.roller_info is None or self.roller_info.empty:
            return None

        trading_day = pd.to_datetime(trading_day)
        if trading_day < self.roller_info['STARTDATE'].iloc[0] or trading_day > self.roller_info['ENDDATE'].iloc[-1]:
            return None

        starts = self.roller_info['STARTDATE'].values
        idx = starts.searchsorted(trading_day.to_datetime64(), side='right') - 1
        if idx < 0:
            return None
        if self.roller_info['ENDDATE'].iloc[idx] >= trading_day:
            return self.roller_info.iloc[idx]
        return None

    def get_contract_id_from_trading_day(self, trading_day: datetime | str) -> Optional[str]:
        """返回交易日对应的合约唯一 id，优先使用 CONTRACT_UID。"""
        row = self.get_contract_row_from_trading_day(trading_day)
        if row is None:
            return None
        return str(row.get('CONTRACT_UID') or row.get('CONTRACT') or '')

    def get_contract_label_from_trading_day(self, trading_day: datetime | str) -> Optional[str]:
        """返回交易日对应的可读合约名，优先使用 CONTRACT。"""
        row = self.get_contract_row_from_trading_day(trading_day)
        if row is None:
            return None
        return str(row.get('CONTRACT') or row.get('CONTRACT_UID') or '')

    def get_contract_from_trading_day(self, trading_day: datetime | str) -> Optional[FuturesContract]:
        """根据交易日返回对应主力合约对象。

        注意：这里优先用 CONTRACT_UID 构造对象，因为合约级 DataSource 通常以
        唯一 id 命名数据文件；旧逻辑使用短合约名会导致后续找不到合约数据。
        """
        contract_id = self.get_contract_id_from_trading_day(trading_day)
        if not contract_id:
            return None
        return self.FuturesContractClass(contract_id)

    def iter_roller_contract_rows(self) -> Iterable[pd.Series]:
        """按 STARTDATE 顺序遍历当前 Futures 的主力切换行。"""
        self._ensure_roller_info()
        if self.roller_info is None or self.roller_info.empty:
            return iter(())
        return (row for _, row in self.roller_info.iterrows())

    def list_roller_contracts(self) -> List[FuturesContract]:
        """返回 roller_info 中出现过的合约对象列表。"""
        contracts = []
        for row in self.iter_roller_contract_rows():
            contract_id = str(row.get('CONTRACT_UID') or row.get('CONTRACT') or '')
            if contract_id:
                contracts.append(self.FuturesContractClass(contract_id))
        return contracts

    def get_roller_contracts_from_trading_day(self, trading_day: datetime | str, n: int = 1) -> List[FuturesContract]:
        """返回从某交易日所在主力段开始的后续 n 个主力合约。

        这不是完整期限结构截面，而是基于主力展期表的“主力链”视角；
        完整期限结构需要交易所全部可交易合约清单及到期日元数据。
        """
        row = self.get_contract_row_from_trading_day(trading_day)
        if row is None:
            return []
        self._ensure_roller_info()
        if self.roller_info is None:
            return []
        idx = int(self.roller_info.index.get_loc(row.name))
        rows = self.roller_info.iloc[idx:idx + max(1, int(n))]
        contracts = []
        for _, r in rows.iterrows():
            contract_id = str(r.get('CONTRACT_UID') or r.get('CONTRACT') or '')
            if contract_id:
                contracts.append(self.FuturesContractClass(contract_id))
        return contracts

    def get_nth_roller_contract_from_trading_day(self, trading_day: datetime | str, n: int = 0) -> Optional[FuturesContract]:
        """返回交易日所在主力段之后第 n 个主力链合约，n=0 为当期主力。"""
        contracts = self.get_roller_contracts_from_trading_day(trading_day, n=int(n) + 1)
        return contracts[int(n)] if len(contracts) > int(n) else None

    def get_term_structure_contracts_from_trading_day(self, trading_day: datetime | str, depth: int = 2) -> List[FuturesContract]:
        """返回用于期限结构计算的合约链。

        当前实现基于主力展期链，适合计算“当期主力 vs 后续主力”的近似期限结构；
        若需要完整期限结构，应由数据源提供某日全部可交易合约与到期日排序。
        """
        return self.get_roller_contracts_from_trading_day(trading_day, n=depth)

    def get_roller_info_path(self) -> str | None:
        """返回此品种对应的 roller_info 文件路径。子类可重写以支持按品种分流。"""
        return self.roller_info_path


def map_contracts_to_futures(
    contracts: Iterable[FuturesContract],
    futures: Iterable[Futures],
    contract_key: Callable[[FuturesContract], Optional[Tuple[Any, ...]]],
    futures_key: Callable[[Futures], Optional[Tuple[Any, ...]]],
) -> Dict[FuturesContract, Futures]:
    """Map each FuturesContract to its underlying Futures using caller-defined keys."""
    futures_by_key: Dict[Tuple[Any, ...], Futures] = {}
    for future in futures:
        key = futures_key(future)
        if key is not None:
            futures_by_key.setdefault(tuple(key), future)

    mapping: Dict[FuturesContract, Futures] = {}
    for contract in contracts:
        key = contract_key(contract)
        if key is None:
            continue
        future = futures_by_key.get(tuple(key))
        if future is not None:
            mapping[contract] = future
    return mapping


def make_contract_category_from_futures_category(
    futures_category: Any,
    contract_type: type,
    contracts: List[FuturesContract],
    contract_to_future: Dict[FuturesContract, Futures],
):
    """Create a FuturesContract category that inherits labels from a Futures category."""
    from tools.products.categories.Category import Category

    category = Category(
        alias=futures_category.alias,
        type=contract_type,
        categories=list(futures_category.categories),
    )
    category.objs = contracts
    category.get_value_alias = futures_category.get_value_alias
    category.whether_is_in_category = lambda catname, obj, *args, **kwargs: (
        (future := contract_to_future.get(obj)) is not None
        and futures_category.whether_is_in_category(catname, future)
    )
    return category
