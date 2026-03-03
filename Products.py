from enum import Enum
import os
import sys
from typing import List, Optional, Dict
import pandas as pd
from datetime import datetime
from abc import ABC  # Add this import
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from tqdm import tqdm

mappings_path = '../data/rollover_adjustments.csv'

from weakref import WeakValueDictionary  # Using weak references to avoid memory issues
# 定义一个金融产品的基类，包括它的产品名字、类别、币种、产业类别等信息
class ProductBase(ABC):
    _instances = WeakValueDictionary()  # Class-level dictionary to store instances by name
    _default_category_attr_name = '__class__.__name__'  # Default attribute name for category

    def __new__(cls, name: str, *args, **kwargs):
        # Create a unique key that includes the class type
        key = (name, cls.__name__)
        # Check if an instance with this name and class already exists
        if key in cls._instances:
            return cls._instances[key]
        
        # Create a new instance if it doesn't exist
        instance = super().__new__(cls)
        cls._instances[key] = instance
        return instance

    def __init__(self, name: str,
                 point_value: Optional[int] = None,
                 currency: Optional[str] = None,
                 category_attr_name: Optional[str] = None,):
        # Only initialize if this is a new instance (not already initialized)
        if not hasattr(self, 'initialized'):
            self.name = name
            self.point_value = point_value
            self.currency = currency
            self.category_attr_name = category_attr_name if category_attr_name else self._default_category_attr_name
            self.initialized = True
            self.data: Optional[pd.DataFrame] = None
            self.data_path: Optional[str] = None
        
        # Always set security_type to the actual class
        self.security_type = type(self)

    def __str__(self):
        return self.name
    
    def __repr__(self):
        return self.name
    
    def load_data(self, data_path: Optional[str] = None, reload_falg: bool = False):
        if self.data is None or reload_falg:
            data_path = self.data_path if data_path is None else data_path
            assert data_path is not None, "data_path must be provided if data is not loaded"
            self.data_path = data_path
            if data_path.endswith('.csv'):
                df = pd.read_csv(data_path)
            elif data_path.endswith('.xlsx'):
                df = pd.read_excel(data_path)
            elif data_path.endswith('.parquet'):
                df = pd.read_parquet(data_path)
            else:
                raise ValueError("Unsupported file type")
            if df.empty:
                raise ValueError("DataFrame is empty")
            self.data = df

    def get_data(self, data_path: Optional[str] = None) -> pd.DataFrame:
        if self.data is None:
            if self.data_path is None:
                assert data_path is not None, "data_path must be provided if data is not loaded"
                self.data_path = data_path
            self.load_data(self.data_path)
            assert self.data is not None, "Data not loaded"
        return self.data
    
    def get_price(self, price_col: str, date_col: str, date: str|datetime, data_path: Optional[str] = None) -> float:
        self.load_data(data_path)  # Ensure data is loaded
        assert self.data is not None, "Data is not loaded"
        date = pd.to_datetime(date)
        df_filtered = self.data[[price_col, date_col]].copy()
        df_filtered[date_col] = pd.to_datetime(df_filtered[date_col])
        return df_filtered[df_filtered[date_col] == date][price_col].values[0]
    
    def set_category_attr_name_as_default(self):
        self.category_attr_name = self._default_category_attr_name

    def _get_attr_nested(self, attr_str: str):
        attr_list = attr_str.split('.')
        attr_value = self
        for attr in attr_list:
            attr_value = getattr(attr_value, attr)
        return attr_value

    def get_category(self) -> str:
        return str(self._get_attr_nested(self.category_attr_name))
    
    def get_default_category(self) -> str:
        return str(self._get_attr_nested(self._default_category_attr_name))

class FuturesContract(ProductBase):
    def __init__(self, name: str, point_value: Optional[int] = None, currency: Optional[str] = None):
        super().__init__(name, point_value, currency)

class Futures(ProductBase):
    def __init__(self, name: str, point_value: Optional[int] = None, currency: Optional[str] = None,
                 mappings_path: Optional[str] = None, data_path: Optional[str] = None,
                 FuturesContractClass: type = FuturesContract):
        super().__init__(name, point_value, currency)
        self.mappings_path = mappings_path
        self.mappings: Optional[pd.DataFrame] = None
        self.FuturesContractClass = FuturesContractClass

    def set_mappings(self, path: str):
        self.mappings_path = path
        # 根据mappings_path的文件类型，导入映射表
        if path.endswith('.csv'):
            self.mappings = pd.read_csv(path)
        elif path.endswith('.xlsx'):
            self.mappings = pd.read_excel(path)
        elif path.endswith('.parquet'):
            self.mappings = pd.read_parquet(path)
        else:
            raise ValueError("Unsupported file type")
        # 筛选self.mappings中'product_id'一列与self.name相同的行
        self.mappings = self.mappings[self.mappings['product_id'] == self.name]
        # 'old_contract_start_date'列是起始日期，'old_contract_end_date'列是终止日期，要进行数据类型的转化
        self.mappings['old_contract_start_date'] = pd.to_datetime(self.mappings['old_contract_start_date'])
        self.mappings['old_contract_end_date'] = pd.to_datetime(self.mappings['old_contract_end_date'])
        # 根据'old_contract_start_date'列排序
        self.mappings = self.mappings.sort_values(by='old_contract_start_date')
    
    def get_contract_from_trading_day(self, trading_day: datetime|str) -> Optional[FuturesContract]:
        if self.mappings is None:
            if self.mappings_path is not None:
                self.set_mappings(self.mappings_path)
            else:
                raise ValueError("Mappings path not set")
        # 先将trading_day转化为datetime
        trading_day = pd.to_datetime(trading_day)
        assert self.mappings is not None
        # 如果trading_day在第一行'old_contract_start_date'之前，返回None
        # 如果trading_day在最后一行'old_contract_end_date'之后，返回最后一行的'new_unique_instrument_id'
        # 如果trading_day在某个行'old_contract_start_date'和'old_contract_end_date'之间，返回该行的'old_unique_instrument_id'
        if trading_day < self.mappings['old_contract_start_date'].iloc[0]:
            return None
        elif trading_day > self.mappings['old_contract_end_date'].iloc[-1]:
            return self.FuturesContractClass(self.mappings['new_unique_instrument_id'].iloc[-1])
        else:
            for i in range(len(self.mappings)):
                if trading_day >= self.mappings['old_contract_start_date'].iloc[i] and trading_day <= self.mappings['old_contract_end_date'].iloc[i]:
                    return self.FuturesContractClass(self.mappings['new_unique_instrument_id'].iloc[i])
        
# class PortfolioBackTester:
#     def __init__(self, start_date: Optional[datetime|str] = None, end_date: Optional[datetime|str] = None,
#                  initial_capital: Optional[float] = None, risk_free_rate: Optional[float] = None,
#                  transaction_cost: Optional[float] = None, margin_rate: Optional[float] = None,
#                  weight_type: Optional[str] = None, holdings_history: Optional[Dict[str, Dict[str, List[ProductBase]]]] = None):
#         self.start_date: Optional[datetime] = None
#         self.end_date: Optional[datetime] = None
#         self.dates = []
#         if start_date is not None:
#             self.start_date = pd.to_datetime(start_date)
#         if end_date is not None:
#             self.end_date = pd.to_datetime(end_date)
#         self.initial_capital = initial_capital
#         self.risk_free_rate = risk_free_rate
#         self.transaction_cost = transaction_cost
#         self.margin_rate = margin_rate
#         self.weight_type = weight_type
#         self.holdings_history = holdings_history
#         self.portfolio_history: Dict[str, Dict[str, Dict[ProductBase, float]]] = {}
#         if self.holdings_history is not None:
#             self._calc_portfolio_history_from_holdings_history()
#         self.trade_history = []
    
#     def _calc_portfolio_history_from_holdings_history(self, holdings_history: Optional[Dict[str, Dict[str, List[ProductBase]]]] = None,
#                                                       weight_type: Optional[str] = None):
#         # 如果已经计算过，则直接返回
#         if self.portfolio_history and len(self.portfolio_history) > 0 and holdings_history is None:
#             return
#         # 如果传入了holdings_history，则更新
#         if holdings_history is not None:
#             self.holdings_history = holdings_history
#         assert self.holdings_history is not None
#         # 更新weight_type
#         if weight_type is not None:
#             self.weight_type = weight_type
#         # 计算
#         for holding_type, holding_type_history in self.holdings_history.items():
#             self.portfolio_history[holding_type] = {}
#             for date, holdings in holding_type_history.items():
#                 self.portfolio_history[holding_type][date] = {}
#                 num_holdings = len(holdings)
#                 if self.weight_type is None or self.weight_type == 'equal':
#                     for holding in holdings:
#                         if isinstance(holding, Futures):
#                             holding.mappings_path = mappings_path
#                             holding = holding.get_contract_from_trading_day(date)
#                             assert holding is not None
#                         self.portfolio_history[holding_type][date][holding] = 1 / num_holdings
#                 else:
#                     raise ValueError(f"Invalid weight type: {self.weight_type}")
#             new_dates = set(holding_type_history.keys()) - set(self.dates)
#             self.dates.extend(list(new_dates))
#         self.dates.sort()

#     def run_backtest_simple_of_equal_holdings_change_daily_at_open(self, 
#                                                                    start_date: Optional[datetime|str] = None,
#                                                                    end_date: Optional[datetime|str] = None,
#                                                                    holdings_history: Optional[Dict[str, Dict[str, List[ProductBase]]]] = None):
        
#         # 更新start_date和end_date
#         if start_date is not None:
#             self.start_date = pd.to_datetime(start_date)
#         if end_date is not None:
#             self.end_date = pd.to_datetime(end_date)
#         backtest_dates = [date for date in self.dates if (self.start_date is None or date >= self.start_date) and (self.end_date is None or date <= self.end_date)]
        
#         # 更新holdings_history
#         if self.portfolio_history is not None and holdings_history is None:
#             pass
#         elif holdings_history is not None:
#             self.holdings_history = holdings_history
#             self._calc_portfolio_history_from_holdings_history(holdings_history, None)
#         else:
#             raise ValueError("Invalid holdings_history")
        
#         capital = self.initial_capital
#         assert self.holdings_history is not None, "holdings_history is not set"

#         prev_holdings = {}
#         for idx, current_date in tqdm(enumerate(backtest_dates), desc="Backtesting.."):
#             current_holdings = {holding_type: self.holdings_history[holding_type][current_date] for holding_type in self.portfolio_history}
            
            

#     def run_backtest(self, start_date: Optional[datetime|str] = None,
#                      end_date: Optional[datetime|str] = None,
#                      holdings_history: Optional[Dict[str, Dict[str, List[ProductBase]]]] = None,
#                      weight_type: Optional[str] = None):
       
#         # 更新start_date和end_date
#         if start_date is not None:
#             self.start_date = pd.to_datetime(start_date)
#         if end_date is not None:
#             self.end_date = pd.to_datetime(end_date)
        
#         # 更新holdings_history
#         if self.portfolio_history is not None and holdings_history is None:
#             pass
#         elif holdings_history is not None:
#             self.holdings_history = holdings_history
#             self._calc_portfolio_history_from_holdings_history(holdings_history, weight_type)
#         else:
#             raise ValueError("Invalid holdings_history")
#         assert self.portfolio_history is not None

#         # 初始化变量
#         capital = self.initial_capital
#         available_capital = capital
#         margin_used = 0

#         prev_portfolio = {}
#         for idx, current_date in tqdm(enumerate(self.dates), desc="Backtesting.."):
#             current_portfolio = {holding_type: self.portfolio_history[holding_type][current_date] for holding_type in self.portfolio_history}
            
#             if idx == 0:
#                 for holding_type, holding_type_portfolio in current_portfolio.items():
#                     if holding_type == 'LONG':
#                         for holding, weight in holding_type_portfolio.items():
#                             if isinstance(holding, FuturesContract):
#                                 assert holding is not None
#                                 self.trade_history.append((current_date, 'LONG', holding, weight))
#                                 capital -= holding.get_price() * weight
#                                 margin_used += holding.get_price() * weight * self.margin_rate
#                                 available_capital = capital - margin_used
#                     elif holding_type == 'SHORT':
#                         for holding, weight in holding_type_portfolio.items():
#                             if isinstance(holding, Futures):
#                                 holding.mappings_path = mappings_path
#                                 holding = holding.get_contract_from_trading_day(current_date)
#                                 assert holding is not None
#                                 self.trade_history.append((current_date, 'SHORT', holding, -weight))
#                                 capital += holding.get_price() * weight
#                                 margin_used += holding.get_price() * weight * self.margin_rate
#                                 available_capital = capital - margin_used
#                     else:
#                         raise ValueError(f"Invalid holding_type: {holding_type}")
                    