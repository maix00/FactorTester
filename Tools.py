from abc import ABC
from weakref import WeakValueDictionary
from typing import TYPE_CHECKING, Callable, List, Dict, Optional, Sequence, Set, Tuple, Any, Literal
import pandas as pd
from enum import Enum

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
            if not hasattr(self, 'alias'):
                self.alias = name
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
    
    def get(self, attr_name: str) -> Any:
        if hasattr(self, attr_name):
            attr_value = getattr(self, attr_name)
            if attr_value is not None:
                return attr_value
            else:
                raise AttributeError(f"{self.__class__.__name__} has no attribute {attr_name}")
        else:
            raise AttributeError(f"{self.__class__.__name__} has no attribute {attr_name}")
        
    def set(self, **kwargs) -> None:
        for attr_name, value in kwargs.items():
            setattr(self, attr_name, value)
    
class SerialObject(UniqueObject):
    _instance_count: int = -1
    _serial_map: Dict[int, SerialObject] = {}
    _type_alias_owners: Dict[str, type] = {}

    @classmethod
    def _get_family_root(cls):
        if getattr(cls, '_override_family_root', False):
            return cls
        for base in cls.__mro__:
            if SerialObject in base.__bases__:
                return base
            if base is SerialObject:
                break
        return SerialObject

    def __new__(cls, type_alias: str, alias: Optional[str] = None, *args, **kwargs):

        if type_alias in cls._type_alias_owners:
            owner = cls._type_alias_owners[type_alias]
            if not issubclass(cls, owner):
                raise ValueError(f"type_alias '{type_alias}' is already used by {owner.__name__} family")
        else:
            cls._type_alias_owners[type_alias] = cls._get_family_root()

        cls._instance_count += 1
        name = f"{type_alias}@{cls._instance_count}"
        name = name if alias is None else f"{name}:{alias}"
        instance = super().__new__(cls, name=name)
        return instance

    def __init__(self, type_alias: str, alias: Optional[str] = None, *args, **kwargs):
        if not hasattr(self, '_initialized'):
            self.serial_number = self._instance_count
            name = f"{type_alias}@{self.serial_number}"
            self.alias = alias or name
            name = name if alias is None else f"{name}:{alias}"
            super().__init__(name=name)
            self._set_serial_map(self.serial_number, self)

    @classmethod
    def _set_serial_map(cls, serial_number: int, instance: SerialObject):
        cls._serial_map[serial_number] = instance
    
    @classmethod
    def _get_by_serial(cls, serial_number: int) -> Optional[SerialObject]:
        return cls._serial_map.get(serial_number)
    
    def __class_getitem__(cls, key):
        if isinstance(key, int):
            item = cls._get_by_serial(key)
            if item is not None:
                return item
            else:
                raise KeyError(f"No instance with serial number {key} found in {cls.__name__} family")
        raise TypeError(f"Invalid key type: {type(key).__name__}. Expected int for serial number lookup.")


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
        try:
            return DataColumn(col)
        except ValueError:
            pass
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
    
    if TYPE_CHECKING:
        from Products import Product

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

    if TYPE_CHECKING:
        from Products import Product

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
        
        from Products import Futures

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