"""
期货产品模块

提供 FuturesContract（具体合约）和 Futures（主办合约／主指数合约）两层结构。
Futures 通过 roller_info 表维护「历史交易日 → 对应主办合约」的映射关系。

roller_info 的闲置释放由 tools.base.IdleResourceManager 统一管理。
"""
import pandas as pd
from typing import Optional
from datetime import datetime

from tools.products.Product import Product
from tools.base.IdleResourceManager import IdleResourceManager

class FuturesContract(Product):
    """具体期货合约。一个 FuturesContract 对应一个具体到期日的合约代码，如 'IF2412.CFE'。"""
    def __init__(self, name: str, point_value: Optional[int] = None, currency: Optional[str] = None, *args, **kwargs):
        super().__init__(name, point_value, currency, *args, **kwargs)


class Futures(Product):
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
                 FuturesContractClass: type = FuturesContract, *args, **kwargs):
        if not hasattr(self, '_initialized'):
            super().__init__(name, point_value, currency, *args, **kwargs)
            self.roller_info_path = roller_info_path
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

    def get_contract_from_trading_day(self, trading_day: datetime | str) -> Optional[FuturesContract]:
        """
        根据交易日返回对应的主力合约对象。
        若交易日早于映射表第一行或超出最后一行 ENDDATE，返回 None；
        否则用 searchsorted 二分查找定位合约。
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
            return self.FuturesContractClass(self.roller_info['CONTRACT'].iloc[idx])
        return None

    def get_roller_info_path(self) -> str | None:
        """返回此品种对应的 roller_info 文件路径。子类可重写以支持按品种分流。"""
        return self.roller_info_path