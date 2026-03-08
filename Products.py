from enum import Enum
import os
import sys
from typing import Any, List, Optional, Dict, Tuple
import pandas as pd
from datetime import datetime
from abc import ABC  # Add this import
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from tqdm import tqdm

mappings_path = '../data/rollover_adjustments.csv'

from weakref import WeakValueDictionary  # Using weak references to avoid memory issues

class DataFreq(Enum):
    MIN1 = pd.Timedelta('1min')
    DAY1 = pd.Timedelta('1day')

class DataColumn(Enum):
    OPEN = 'O'
    HIGH = 'H'
    LOW = 'L'
    CLOSE = 'C'
    VOLUME = 'V'
    TURNOVER = 'TO'
    OPEN_INTEREST = 'OI'
    TIME_COL_DAY = 'TD'
    TIME_COL_MIN = 'TM'
    TWAP = 'TW'
    VWAP = 'VW'
    SETTLEMENT_PRICE = 'SP'
    ADJUSTMENT_MUL = 'AM'
    ADJUSTMENT_ADD = 'AA'
    UPPER_LIMIT_PRICE = 'ULP'
    LOWER_LIMIT_PRICE = 'LLP'
    PRE_SETTLEMENT_PRICE = 'PSP'
    OPEN_ADJUSTED = 'OA'
    HIGH_ADJUSTED = 'HA'
    LOW_ADJUSTED = 'LA'
    CLOSE_ADJUSTED = 'CA'
    TIME_COL = 'T'
    ADJUST_SUFFIX = 'ADJ'

class UniqueObject(ABC):
    _instances = WeakValueDictionary()

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
    
    def __init__(self, name: str):
        # Only initialize if this is a new instance (not already initialized)
        if not hasattr(self, '_initialized'):
            self.name = name
            self._initialized = True

    def __reduce__(self):
        return (self.__class__, (self.name,))

    def __str__(self):
        return self.name
        
    def __lt__(self, other):
        return self.name < other.name

    def __eq__(self, other):
        return self.name == other.name

    def __hash__(self):
        return hash(self.name)
    
    def __repr__(self):
        return self.name

class Product(UniqueObject):
    _default_category_attr_name = '__class__.__name__'  # Default attribute name for category

    def __init__(self, name: str,
                 point_value: Optional[int] = None,
                 currency: Optional[str] = None,
                 category_attr_name: Optional[str] = None):
        if not hasattr(self, '_initialized'):
            super().__init__(name)
            self.point_value = point_value
            self.currency = currency
            self.category_attr_name = category_attr_name if category_attr_name \
                else self._default_category_attr_name
            self.data: Dict[DataFreq, pd.DataFrame] = {}
            self.data_path: Dict[DataFreq, str] = {}
            self.time_cols_mapping: Dict[DataFreq, Dict[DataFreq, str]] = {}
            self.data_cols_mapping: Dict[DataFreq, Dict[DataColumn, str]] = {}
            self.sessions: Dict[str, List[Tuple[pd.Timestamp, pd.Timestamp]]] = {}
            self.recent_data_freq: Optional[DataFreq] = None
    
    def set_time_cols_mapping(self, data_freq: Any, mapping: Dict[Any, str]) -> None:
        data_freq = self._process_data_freq(data_freq)
        self.time_cols_mapping[data_freq] = {self._process_data_freq(k): v for k, v in mapping.items()}
    
    def set_data_cols_mapping(self, data_freq: Any, mapping: Dict[DataColumn, str]) -> None:
        data_freq = self._process_data_freq(data_freq)
        self.data_cols_mapping[data_freq] = {k: v for k, v in mapping.items()}
    
    def get_col_name(self, data_col: DataColumn, data_freq: Optional[Any] = None) -> str:
        if data_freq is None:
            data_freq = self.recent_data_freq
        data_freq = self._process_data_freq(data_freq)
        return self.data_cols_mapping[data_freq][data_col]

    @staticmethod
    def _process_data_freq(data_freq: Optional[Any] = None) -> DataFreq:
        if isinstance(data_freq, DataFreq):
            return data_freq
        if isinstance(data_freq, str):
            data_freq = pd.Timedelta(data_freq)
        if isinstance(data_freq, pd.Timedelta):
            data_freq = DataFreq(data_freq)
            return DataFreq(data_freq)
        raise ValueError("Invalid data frequency")
    
    def set_data_path(self, data_path: str, data_freq: Any) -> None:
        data_freq = self._process_data_freq(data_freq)
        self.data_path[data_freq] = data_path

    def load_all_data(self) -> None:
        for freq in self.data_path.keys():
            self.load_data(freq, reload=True)

    def load_data(self, data_freq: Any, data_path: Optional[str] = None, 
                  reload: bool = False, time_cols_mapping: Optional[Dict[Any, str]] = None) -> None:
        data_freq = self._process_data_freq(data_freq)
        if data_path is not None:
            self.set_data_path(data_path, data_freq)
        data_path = self.data_path.get(data_freq)
        if data_path is not None and (self.data.get(data_freq) is None or reload):
            if data_path.endswith('.csv'):
                df = pd.read_csv(data_path)
            elif data_path.endswith('.xlsx'):
                df = pd.read_excel(data_path)
            elif data_path.endswith('.parquet'):
                df = pd.read_parquet(data_path)
            else:
                return
            if not df.empty:
                if time_cols_mapping is not None:
                    self.set_time_cols_mapping(data_freq, time_cols_mapping)
                time_cols_mapping = self.time_cols_mapping.get(data_freq)
                if time_cols_mapping is not None:
                    time_cols = [time_cols_mapping[_f] for _f in sorted(time_cols_mapping.keys(), key=lambda x: x.value, reverse=True)]
                    for col in time_cols:
                        df[col] = pd.to_datetime(df[col])
                    df = df.reset_index().set_index(time_cols)
                self.data[data_freq] = df

    def get_data(self, data_freq: Any, copy: bool = True) -> pd.DataFrame:
        data_freq = self._process_data_freq(data_freq)
        data = self.data.get(data_freq)
        if data is None:
            self.load_data(data_freq)
            data = self.data.get(data_freq)
        data = pd.DataFrame() if data is None else data
        self.recent_data_freq = data_freq
        if copy:
            data = data.copy()
        return data
    
    def get_recent_data_freq(self) -> DataFreq:
        data_freq = self.get_some_data_freq()
        assert data_freq is not None, "No data frequency available"
        return data_freq
    
    def get_some_data_freq(self) -> Optional[DataFreq]:
        if self.recent_data_freq is not None:
            return self.recent_data_freq
        if self.data_path:
            data_freq = sorted(self.data_path.keys(), key=lambda x: x.value)[0]
            self.recent_data_freq = data_freq
            return data_freq
        else:
            return None
    
    def get_some_data(self, data_freq: Optional[Any] = None, copy: bool = True) -> pd.DataFrame:
        if data_freq is not None or self.recent_data_freq is not None:
            data_freq = data_freq if data_freq is not None else self.recent_data_freq
            df = self.get_data(data_freq, copy=copy)
            if df is not None:
                return df
        if self.data_path:
            freq = sorted(self.data_path.keys(), key=lambda x: x.value)[0]
            if not self.data:
                self.load_data(freq, reload=True)
            self.recent_data_freq = freq
            return self.get_data(freq, copy=copy)
        else:
            return pd.DataFrame()
        
    def get_available_freqs(self) -> List[DataFreq]:
        return list(self.data_path.keys())
    
    def get_loaded_freqs(self) -> List[DataFreq]:
        return list(self.data.keys())
    
    def get_slices(self, target_cols: Optional[DataColumn|List[DataColumn|str]] = None,
                   time_col: Optional[DataColumn|str] = None, time_range: Optional[Any] = None,
                   data_freq: Optional[Any] = None, copy: bool = True) -> pd.DataFrame:
        
        if data_freq is None:
            data_freq = self.get_some_data_freq()
            assert data_freq is not None
        data = self.get_some_data(data_freq, copy=False)

        if isinstance(target_cols, DataColumn):
            target_cols = [target_cols]
        if target_cols is None:
            target_cols = list(data.columns)
        else:
            target_cols = [self.get_col_name(col) if isinstance(col, DataColumn) else col for col in target_cols]
        if data.empty:
            return pd.DataFrame(columns=target_cols)

        time_cols_mapping = self.time_cols_mapping.get(data_freq)
        
        if time_cols_mapping is None:
            return pd.DataFrame(columns=target_cols)
        assert time_cols_mapping is not None
        time_cols = [time_cols_mapping[_f] for _f in sorted(time_cols_mapping.keys(), key=lambda x: x.value, reverse=True)]
        if time_col is None:
            time_col = time_cols[0]
        if isinstance(time_col, DataColumn):
            time_col = self.get_col_name(time_col)
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
        slice = self.get_slices(time_col=DataColumn.TIME_COL, time_range=time)
        return not slice.empty
        
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

class FuturesContract(Product):
    def __init__(self, name: str, point_value: Optional[int] = None, currency: Optional[str] = None):
        super().__init__(name, point_value, currency)

class Futures(Product):
    def __init__(self, name: str, point_value: Optional[int] = None, currency: Optional[str] = None,
                 mappings_path: Optional[str] = None, data_path: Optional[str] = None,
                 FuturesContractClass: type = FuturesContract):
        if not hasattr(self, '_initialized'):
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
    
    def get_col_name_adjusted(self, data_col: DataColumn|str) -> str:
        preffix = self.get_col_name(data_col) if isinstance(data_col, DataColumn) else data_col
        return preffix + self.get_col_name(DataColumn.ADJUST_SUFFIX)
    
    def get_col_name_nonadjusted(self, data_col: DataColumn|str) -> str:
        col_name = self.get_col_name(data_col) if isinstance(data_col, DataColumn) else data_col
        return col_name.removesuffix(self.get_col_name(DataColumn.ADJUST_SUFFIX))

    def check_col_is_adjusted(self, col_name: DataColumn|str) -> bool:
        if isinstance(col_name, DataColumn):
            col_name = self.get_col_name(col_name)
        return col_name.endswith(self.get_col_name(DataColumn.ADJUST_SUFFIX))

    def adjust_cols(self, data_freq: Any, price_cols: List[DataColumn|str]|DataColumn|str, copy: bool = True) -> pd.DataFrame:
        if not isinstance(price_cols, list):
            price_cols = [price_cols]
        price_cols = list(set([self.get_col_name(col) if isinstance(col, DataColumn) else col for col in price_cols]))
        data_freq = self._process_data_freq(data_freq)
        adjust_cols = [self.get_col_name_adjusted(col) for col in price_cols]
        df = self.get_data(data_freq, copy=False)
        if any(col not in df.columns for col in adjust_cols):
            assert self.get_col_name(DataColumn.ADJUSTMENT_MUL) in df.columns
            assert self.get_col_name(DataColumn.ADJUSTMENT_ADD) in df.columns
            for col, col_adj in zip(price_cols, adjust_cols):
                df[col_adj] = df[col] * df[self.get_col_name(DataColumn.ADJUSTMENT_MUL)] \
                    + df[self.get_col_name(DataColumn.ADJUSTMENT_ADD)]
        if copy:
            df = df.copy()
        return df

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
                    