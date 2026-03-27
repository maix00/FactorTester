from enum import Enum
import os
import sys
from typing import TYPE_CHECKING, Any, Callable, List, Optional, Dict, Tuple
import pandas as pd
from datetime import datetime
from Tools import SerialObject, DataColumn, DataMeta, DataFreq, UniqueObject
from Tools import _process_data_col, _process_data_freq
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from tqdm import tqdm
from weakref import WeakValueDictionary

mappings_path = '../data/rollover_adjustments.csv'

class Product(UniqueObject):
    _default_category_attr_name = '__class__.__name__'  # Default attribute name for category
    desc: str
    MIN1: DataMeta
    DAY1: DataMeta

    def __init__(self, name: str,
                 point_value: Optional[int] = None,
                 currency: Optional[str] = None,
                 category_attr_name: Optional[str] = None, *args, **kwargs):
        if not hasattr(self, '_initialized'):
            super().__init__(name=name, *args, **kwargs)
            self.point_value = point_value
            self.currency = currency
            self.category_attr_name = category_attr_name if category_attr_name \
                else self._default_category_attr_name
            self.timezone = kwargs.get('timezone', '')
            for key, val in DataFreq.__members__.items():
                setattr(self, key, DataMeta(alias=f"{key}", object=self, data_freq=val, timezone=self.timezone))
            if TYPE_CHECKING:
                from Parameter import DateOrTimeParam
            self._StartCalcPointParam : DateOrTimeParam

    if TYPE_CHECKING:
        from Parameter import DateOrTimeParam
    def set_StartCalcPointParam(self, param: DateOrTimeParam, value: Optional[Any] = None):
        self._StartCalcPointParam = param
        param.register(self, value if value is not None else param.default_value)

    def get_StartCalcPointParam(self) -> DateOrTimeParam:
        return self._StartCalcPointParam
        
    def list_available_freqs(self) -> List[DataFreq]:
        return [freq for freq in DataFreq if getattr(self, freq.name).is_available()]
    
    def set_current_freq(self, freq: Any) -> DataFreq:
        if freq in self.list_available_freqs():
            self.current_freq = freq
            return freq
        else:
            raise ValueError(f"Data frequency {freq} is not available for product {self.name}")
        
    def get_current_freq(self) -> DataFreq:
        if not hasattr(self, 'current_freq'):
            available_freqs = self.list_available_freqs()
            if len(available_freqs) == 0:
                raise ValueError(f"No data frequency available for product {self.name}")
            self.current_freq = available_freqs[0]
        return self.get('current_freq')
    
    def get_some_data(self, data_freq: Optional[Any] = None, copy: bool = True) -> pd.DataFrame:
        try:
            data_freq = self.get_current_freq() if data_freq is None else _process_data_freq(data_freq)
            return getattr(self, data_freq.name).get_data(copy=copy)
        except:
            return pd.DataFrame()

    def get_time_cols(self, data_freq: Optional[Any] = None) -> List[str]:
        data_freq = self.get_current_freq() if data_freq is None else _process_data_freq(data_freq)
        return getattr(self, data_freq.name).get_current_source().time_cols_mapping.values()
    
    def get_slices(self, target_cols: Optional[Any] = None,
                   time_col: Optional[str] = None, time_range: Optional[Any] = None,
                   data_freq: Optional[Any] = None, copy: bool = True) -> pd.DataFrame:
        
        data = self.get_some_data(data_freq, copy=False)

        if isinstance(target_cols, DataColumn):
            target_cols = [target_cols]
        if target_cols is None:
            target_cols = list(data.columns)
        else:
            target_cols = [col.name if isinstance(col, DataColumn) else col for col in target_cols]
        if data.empty:
            return pd.DataFrame(columns=target_cols)

        time_cols = self.get_time_cols(data_freq)
        
        if time_cols is None:
            return pd.DataFrame(columns=target_cols)
        time_cols = sorted(time_cols, key=lambda x: DataFreq[str(x)].value, reverse=True)
        if time_col is None:
            time_col = time_cols[0] # Default time column
        if time_col not in time_cols:
            return pd.DataFrame(columns=target_cols)
        else:
            assert time_col in time_cols
            time_col_level = time_cols.index(time_col)
            if time_range is None:
                if copy:
                    return data[target_cols].copy()
                else:
                    return data[target_cols]
            if not isinstance(time_range, (list, tuple)):
                time_range = [time_range]
            assert len(time_range) <= 2 and len(time_range) > 0
            if any(isinstance(k, (list, tuple)) for k in time_range):
                time_range = [k[-1] if isinstance(k, (list, tuple)) else k for k in time_range]
            _tr = {}
            for i, time in enumerate(time_range):
                if time is not None:
                    time = pd.to_datetime(time)
                _tr[i] = time
            if len(_tr) == 1:
                _tr[1] = _tr[0]
            try:
                reverse = _tr[0] > _tr[1]
                reverse = reverse.all()
            except:
                reverse = False
            finally:
                if reverse:
                    _tr[1], _tr[0] = _tr[0], _tr[1]
            mask = (data.index.get_level_values(time_col_level) >= _tr[0]) \
                if _tr[0] is not None else pd.Series(True, index=data.index) \
                    & (data.index.get_level_values(time_col_level) <= _tr[1]) \
                        if _tr[1] is not None else pd.Series(True, index=data.index)
            if copy:
                return pd.DataFrame(data.loc[mask, target_cols]).copy()
            else:
                return pd.DataFrame(data.loc[mask, target_cols])
            
    def if_time_is_in_data(self, time: Any) -> bool:
        slice = self.get_slices(time_col=self.get_current_freq().name, time_range=time)
        return not slice.empty
        
    def set_category_attr_name_as_default(self):
        self.category_attr_name = self._default_category_attr_name

    def get_category(self) -> str:
        return str(self._get_attr_nested(self.category_attr_name))
    
    def get_default_category(self) -> str:
        return str(self._get_attr_nested(self._default_category_attr_name))

class FuturesContract(Product):
    def __init__(self, name: str, point_value: Optional[int] = None, currency: Optional[str] = None, *args, **kwargs):
        super().__init__(name, point_value, currency, *args, **kwargs)
    
class Futures(Product):
    def __init__(self, name: str, point_value: Optional[int] = None, currency: Optional[str] = None,
                 mappings_path: Optional[str] = None, data_path: Optional[str] = None,
                 FuturesContractClass: type = FuturesContract, *args, **kwargs):
        if not hasattr(self, '_initialized'):
            super().__init__(name, point_value, currency, *args, **kwargs)
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
                    