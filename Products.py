from enum import Enum
import os
import sys
from typing import Any, Callable, List, Optional, Dict, Tuple
import pandas as pd
from datetime import datetime
from Tools import UniqueObject, SerialObject
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from tqdm import tqdm
from weakref import WeakValueDictionary

mappings_path = '../data/rollover_adjustments.csv'

class DataFreq(Enum):
    MIN1 = pd.Timedelta('1min')
    DAY1 = pd.Timedelta('1day')

def _process_data_freq(data_freq: Optional[Any] = None) -> DataFreq:
    if isinstance(data_freq, DataFreq):
        return data_freq
    if isinstance(data_freq, str):
        try:
            data_freq = DataFreq[data_freq]
        except KeyError:
            data_freq = pd.Timedelta(data_freq)
    if isinstance(data_freq, pd.Timedelta):
        data_freq = DataFreq(data_freq)
        return DataFreq(data_freq)
    raise ValueError("Invalid data frequency")

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
    PRODUCT_NAME = 'PN'

def _process_data_col(col: Optional[Any] = None) -> DataColumn:
    if isinstance(col, DataColumn):
        return col
    if isinstance(col, str):
        col = DataColumn(col)
    raise ValueError("Invalid data column")

class DataSourceRegister(UniqueObject):
    _instances = WeakValueDictionary()
    _data_sources = WeakValueDictionary()

    def __new__(cls):
        return super().__new__(cls, name='DataSourceRegister')

    def __init__(self):
        if not hasattr(self, '_initialized'):
            super().__init__('DataSourceRegister')
            self.default_source: DataSource

    @staticmethod
    def _process_source(name: Any) -> DataSource:
        if isinstance(name, DataSource):
            return name
        elif isinstance(name, str):
            return DataSource(name)
        else:
            raise ValueError
    
    def register(self, source: Any) -> DataSource:
        source = self._process_source(source)
        if source.alias not in self._data_sources:
            self._data_sources[source.alias] = self._process_source(source)
        return source

    def set_default_source(self, source: Any) -> DataSource:
        self.default_source = self.register(source)
        return self.default_source
    
    def get_source(self, name: str) -> DataSource:
        return self._data_sources[name]
    
    def get_all_sources(self) -> List[DataSource]:
        return list(self._data_sources.values())

    def get_default_source(self) -> DataSource:
        return self.get('default_source')

class DataSource(SerialObject):
    _instances = WeakValueDictionary()
    _instance_count: int = -1
    _serial_map = {}

    def __new__(cls, alias: str, *args, **kwargs):
        return super().__new__(cls, type_alias='DS', alias=alias)

    def __init__(self, alias: str, data_freq: DataFreq,
                 if_product_is_in_source: Callable[[Product], bool],
                 get_product_path: Callable[[Product], Any]):
        if not hasattr(self, '_initialized'):
            super().__init__(type_alias='DS', alias=alias)
            self._register = DataSourceRegister() # Weak Value
            self._register.register(self)
            if len(self._register.get_all_sources()) == 1:
                self._register.set_default_source(self)
            self.alias = alias
            self.freq = data_freq
            self.time_cols_mapping: Dict[Any, str] = {}
            self.data_cols_mapping: Dict[Any, str] = {}
            self._is_product_in_source_func = if_product_is_in_source
            self._get_product_path_func = get_product_path

    def if_product_is_in_source(self, product: Product) -> bool:
        return self._is_product_in_source_func(product)

    def get_product_path(self, product: Product) -> Any:
        return self._get_product_path_func(product)
    
    def set_time_cols_mapping(self, mapping: Dict[Any, Any]) -> None:
        self.time_cols_mapping = {k: _process_data_freq(v).name for k, v in mapping.items()}

    def set_data_cols_mapping(self, mapping: Dict[Any, Any]) -> None:
        self.data_cols_mapping = {k: _process_data_col(v).name for k, v in mapping.items()}

if __name__ == '__main__':
    ds1 = DataSource('source1')
    print(ds1)
    ds = DataSourceRegister().get_default_source()
    print(ds)

class DataMeta(UniqueObject):
    _instances = WeakValueDictionary()

    def __init__(self, name: str, product: Product, data_freq: DataFreq):
        if not hasattr(self, '_initialized'):
            super().__init__(name=name)
            self.product = product
            self.freq = data_freq
            self.data: pd.DataFrame = pd.DataFrame()
            self.current_source: DataSource
            self.path: Any
            self.start_date: pd.Timestamp
            self.end_date: pd.Timestamp

    def list_available_sources(self) -> List[DataSource]:
        lst = []
        for source in DataSourceRegister().get_all_sources():
            if source.if_product_is_in_source(self.product) and source.freq == self.freq:
                lst.append(source)
        return lst
    
    def is_available(self) -> bool:
        return len(self.list_available_sources()) > 0
    
    def set_current_source(self, source: Any) -> DataSource:
        dsr = DataSourceRegister()
        source = dsr.register(source)
        if source in self.list_available_sources():
            self.current_source = source
            return source
        else:
            raise ValueError(f"Data source {source.alias} is not available for product {self.product.name}")
        
    def get_current_source(self) -> DataSource:
        if not hasattr(self, 'current_source'):
            available_sources = self.list_available_sources()
            if len(available_sources) == 0:
                raise ValueError(f"No data source available for product {self.product.name}")
            self.current_source = available_sources[0]
        return self.get('current_source')

    def _load_data(self, source: Optional[Any] = None) -> pd.DataFrame:
        source = self.set_current_source(source) if source is not None else self.get_current_source()
        assert source is not None
        self.path = source.get_product_path(self.product)
        if self.path.endswith('.csv'):
            self.data = pd.read_csv(self.path)
        elif self.path.endswith('.xlsx'):
            self.data = pd.read_excel(self.path)
        elif self.path.endswith('.parquet'):
            self.data = pd.read_parquet(self.path)
        else:
            raise ValueError("Unsupported file type")
        return self.data
    
    def load_data(self, source: Optional[Any] = None,
                  loaded_data: Optional[pd.DataFrame] = None,
                  data_cols_mapping: Optional[Dict[Any, Any]] = None,
                  time_cols_mapping: Optional[Dict[Any, Any]] = None,
                  time_index: Optional[Any] = None,
                  filter_product: bool = False,
                  filter_product_attr: str = 'name') -> pd.DataFrame:
        self.data = loaded_data if loaded_data is not None else self._load_data(source)
        self._map_time_cols(time_cols_mapping)
        self._map_data_cols(data_cols_mapping)
        if filter_product:
            filter_product_name = getattr(self.product, filter_product_attr)
            self.data = self.data[self.data[DataColumn.PRODUCT_NAME] == filter_product_name]
        self._set_time_index(time_index)
        return self.data
    
    def get_data(self, copy: bool = True) -> pd.DataFrame:
        if self.data.empty:
            self.load_data()
        return self.data.copy() if copy else self.data
    
    def _map_data_cols(self, mapping: Optional[Dict[Any, Any]] = None) -> pd.DataFrame:
        assert not self.data.empty
        ds = self.get_current_source()
        if mapping is not None:
            ds.set_data_cols_mapping(mapping)
        self.data.reset_index(inplace=True, drop=True)
        self.data.rename(columns=ds.data_cols_mapping, inplace=True)
        return self.data

    def _map_time_cols(self, mapping: Optional[Dict[Any, Any]] = None) -> pd.DataFrame:
        assert not self.data.empty
        ds = self.get_current_source()
        if mapping is not None:
            ds.set_time_cols_mapping(mapping)
        self.data.reset_index(inplace=True, drop=True)
        self.data.rename(columns=ds.time_cols_mapping, inplace=True)
        return self.data

    def _set_time_index(self, index: Optional[Any] = None) -> pd.DataFrame:
        assert not self.data.empty
        if index is None:
            ds = self.get_current_source()
            index = sorted(ds.time_cols_mapping.values(), key=lambda x: DataFreq[x].value, reverse=True)
        for col in index:
            if col not in self.data.columns:
                raise ValueError(f"Column {col} not found in data")
            self.data[col] = pd.to_datetime(self.data[col])
        self.data.set_index(index, inplace=True)
        return self.data
    
    @staticmethod
    def _get_adjusted_col_name(col: str) -> str:
        return f"{col}_ADJUSTED"
    
    @staticmethod
    def _get_nonadjusted_col_name(col: str) -> str:
        return col.replace("_ADJUSTED", "")
    
    @staticmethod
    def _check_is_adjusted(col: str) -> bool:
        return col.endswith("_ADJUSTED")

    def get_and_adjust_cols(self, cols: List[str]|str, copy: bool = True) -> pd.DataFrame:
        if not isinstance(self.product, Futures):
            return self.get_data(copy)
        if not isinstance(cols, list):
            cols = [cols]
        df = self.get_data(copy)
        cols = list(set(cols))
        adjust_cols = [col if self._check_is_adjusted(col) else self._get_adjusted_col_name(col) for col in cols]
        adjust_cols = [col for col in adjust_cols if col not in df.columns]
        if len(adjust_cols) > 0:
            assert DataColumn.ADJUSTMENT_MUL.name in df.columns
            assert DataColumn.ADJUSTMENT_ADD.name in df.columns
            cols = [self._get_nonadjusted_col_name(col) for col in adjust_cols]
            for col, col_adj in zip(cols, adjust_cols):
                df[col_adj] = df[col] * df[DataColumn.ADJUSTMENT_MUL.name] \
                    + df[DataColumn.ADJUSTMENT_ADD.name]
        return df

class Product(SerialObject):
    _instances = WeakValueDictionary()
    _instance_count: int = -1
    _serial_map = {}
    _default_category_attr_name = '__class__.__name__'  # Default attribute name for category
    MIN1: DataMeta
    DAY1: DataMeta

    def __new__(cls, alias: Optional[str] = None, *args, **kwargs):
        return super().__new__(cls, type_alias='Pr', alias=alias)

    def __init__(self, alias: Optional[str] = None,
                 point_value: Optional[int] = None,
                 currency: Optional[str] = None,
                 category_attr_name: Optional[str] = None, *args, **kwargs):
        if not hasattr(self, '_initialized'):
            super().__init__(type_alias=kwargs.pop('type_alias', 'Pr'), alias=alias, *args, **kwargs)
            self.alias = alias
            self.point_value = point_value
            self.currency = currency
            self.category_attr_name = category_attr_name if category_attr_name \
                else self._default_category_attr_name
            for key, val in DataFreq.__members__.items():
                setattr(self, key, DataMeta(name=f"{self.name}_{key}", product=self, data_freq=val))
        
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
        slice = self.get_slices(time_col=DataColumn.TIME_COL.name, time_range=time)
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
    
class SessionProduct(Product):
    _instances = WeakValueDictionary()
    _override_family_root = True

    def __new__(cls, alias: Optional[str] = None, *args, **kwargs):
        return super().__new__(cls, type_alias='SPr', alias=alias)
    
    def __init__(self, product: Product, alias: Optional[str] = None, session_time_range: Any = None):
        if not hasattr(self, '_initialized'):
            super().__init__(type_alias='SPr', alias=alias)
            self.product = product
            self.session_time_range = session_time_range

class FuturesContract(Product):
    def __init__(self, alias: Optional[str] = None, point_value: Optional[int] = None, currency: Optional[str] = None):
        super().__init__(alias, point_value, currency)
    
class Futures(Product):
    def __init__(self, alias: Optional[str] = None, point_value: Optional[int] = None, currency: Optional[str] = None,
                 mappings_path: Optional[str] = None, data_path: Optional[str] = None,
                 FuturesContractClass: type = FuturesContract):
        if not hasattr(self, '_initialized'):
            super().__init__(alias, point_value, currency)
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
                    