# =============================================================================
# tools/products/Futures.py
# 期货产品模块
#
# 提供 FuturesContract（具体合约）和 Futures（主办合约／主指数合约）两层结构。
# Futures 通过 mappings 表维护「历史交易日 → 对应主办合约」的映射关系。
# =============================================================================
import pandas as pd
from typing import Optional
from datetime import datetime

from tools.products.Product import Product

class FuturesContract(Product):
    """具体期货合约。一个 FuturesContract 对应一个具体到期日的合约代码，如 'IF2412.CFE'。"""
    def __init__(self, name: str, point_value: Optional[int] = None, currency: Optional[str] = None, *args, **kwargs):
        super().__init__(name, point_value, currency, *args, **kwargs)
    
class Futures(Product):
    """
    期货品种类（主办合约奕局）。

    一个 Futures 对应一个品种代码（如 'IF.CFE'），它在不同时间对应不同的
    FuturesContract。mappings 表存储了每个历史时间段对应的具体合约名。

    属性：
        mappings_path (str|None)   : 合约映射表文件路径
        mappings     (DataFrame)   : 合约映射表，列包括 old_contract_start_date/end_date 等
        FuturesContractClass (type): 用于创建具体合约对象的类
    """
    def __init__(self, name: str, point_value: Optional[int] = None, currency: Optional[str] = None,
                 mappings_path: Optional[str] = None, data_path: Optional[str] = None,
                 FuturesContractClass: type = FuturesContract, *args, **kwargs):
        if not hasattr(self, '_initialized'):
            super().__init__(name, point_value, currency, *args, **kwargs)
            self.mappings_path = mappings_path
            self.mappings: Optional[pd.DataFrame] = None  # 映射表，首次访问时才加载
            self.FuturesContractClass = FuturesContractClass  # 具体合约类引用

    def set_mappings(self, path: str):
        """
        加载并设置合约映射表。
        读取文件，筛选当前品种，转换日期列类型，按起始日期排序。
        """
        self.mappings_path = path
        # 根据 mappings_path 的文件类型，导入映射表
        if path.endswith('.csv'):
            self.mappings = pd.read_csv(path)
        elif path.endswith('.xlsx'):
            self.mappings = pd.read_excel(path)
        elif path.endswith('.parquet'):
            self.mappings = pd.read_parquet(path)
        else:
            raise ValueError("Unsupported file type")
        # 筛选 product_id 与当前品种相同的行
        self.mappings = self.mappings[self.mappings['product_id'] == self.name]
        # 转换日期列类型
        self.mappings['old_contract_start_date'] = pd.to_datetime(self.mappings['old_contract_start_date'])
        self.mappings['old_contract_end_date'] = pd.to_datetime(self.mappings['old_contract_end_date'])
        # 按起始日期排序
        self.mappings = self.mappings.sort_values(by='old_contract_start_date')
    
    def get_contract_from_trading_day(self, trading_day: datetime|str) -> Optional[FuturesContract]:
        """
        根据交易日返回对应的主办合约对象。
        若交易日如过早（表第一行安排前）返回 None；
        若超出表的最新日期返回最新一行的合约。
        """
        if self.mappings is None:
            if self.mappings_path is not None:
                self.set_mappings(self.mappings_path)
            else:
                raise ValueError("Mappings path not set")
        trading_day = pd.to_datetime(trading_day)
        assert self.mappings is not None
        # 交易日在最早安排日期之前，返回 None
        if trading_day < self.mappings['old_contract_start_date'].iloc[0]:
            return None
        # 交易日在最新安排日期之后，返回最新合约
        elif trading_day > self.mappings['old_contract_end_date'].iloc[-1]:
            return self.FuturesContractClass(self.mappings['new_unique_instrument_id'].iloc[-1])
        else:
            # 邍历映射表，查找包含 trading_day 的区间
            for i in range(len(self.mappings)):
                if trading_day >= self.mappings['old_contract_start_date'].iloc[i] and trading_day <= self.mappings['old_contract_end_date'].iloc[i]:
                    return self.FuturesContractClass(self.mappings['new_unique_instrument_id'].iloc[i])
                