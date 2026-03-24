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
    
    def __init__(self, name: str, *args, **kwargs):
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

    def _get_attr_nested(self, attr_str: str):
        attr_list = attr_str.split('.')
        attr_value = self
        for attr in attr_list:
            attr_value = getattr(attr_value, attr)
        return attr_value
    
    def _has_attr_nested(self, attr_str: str) -> bool:
        attr_list = attr_str.split('.')
        attr_value = self
        for attr in attr_list:
            if hasattr(attr_value, attr):
                attr_value = getattr(attr_value, attr)
            else:
                return False
        return True
    
class SerialObject(UniqueObject):
    _single_use_count = -1
    _instance_count_dict: Dict[str, int] = {}
    _serial_map_dict: Dict[str, Dict[int, 'SerialObject']] = {}
    _type_alias_owners: Dict[str, type] = {}
    _type_alias: str = 'SO'

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

    def __new__(cls, type_alias: str, alias: Optional[str] = None, search: bool = False, single_use: bool = False, *args, **kwargs):

        if type_alias in cls._type_alias_owners:
            owner = cls._type_alias_owners[type_alias]
            if not issubclass(cls, owner):
                raise ValueError(f"type_alias '{type_alias}' is already used by {owner.__name__} family")
        else:
            cls._type_alias_owners[type_alias] = cls._get_family_root()
        
        cls._type_alias = type_alias

        if search and type_alias in cls._serial_map_dict:
            for instance in cls._serial_map_dict[type_alias].values():
                if instance.alias == alias and instance.__class__ is cls:
                    assert isinstance(instance, cls)
                    return instance
        
        if single_use:
            cls._single_use_count += 1
            name = f"{type_alias}@SU@{cls._single_use_count}"
        else:
            if type_alias in cls._instance_count_dict:
                cls._instance_count_dict[type_alias] += 1
            else:
                cls._instance_count_dict[type_alias] = 0
            name = f"{type_alias}@{cls._instance_count_dict[type_alias]}"
            name = name if alias is None else f"{name}:{alias}"
        instance = super().__new__(cls, name=name)
        return instance

    def __init__(self, type_alias: str, alias: Optional[str] = None, single_use: bool = False, *args, **kwargs):
        if not hasattr(self, '_initialized'):
            if single_use:
                name = f"{type_alias}@SU@{self._single_use_count}"
            else:
                self.serial_number = self._instance_count_dict[type_alias]
                name = f"{type_alias}@{self.serial_number}"
            self.alias = alias or name
            name = name if alias is None else f"{name}:{alias}"
            super().__init__(name=name)
            if not single_use:
                self._set_serial_map_dict(type_alias, self.serial_number, self)

    def __reduce__(self):
        return (self.__class__, (self.alias,))
    
    @classmethod
    def _set_serial_map_dict(cls, type_alias: str, serial_number: int, instance: 'SerialObject'):
        if type_alias not in cls._serial_map_dict:
            cls._serial_map_dict[type_alias] = {}
        cls._serial_map_dict[type_alias][serial_number] = instance
    
    @classmethod
    def _get_by_serial(cls, type_alias: str, serial_number: int) -> Optional['SerialObject']:
        if type_alias in cls._serial_map_dict and serial_number in cls._serial_map_dict[type_alias]:
            return cls._serial_map_dict[type_alias][serial_number]
        return None
    
    def __class_getitem__(cls, key):
        if isinstance(key, int):
            item = cls._get_by_serial(cls._type_alias, key)
            if item is not None:
                assert isinstance(item, cls)
                return item
            else:
                raise KeyError(f"No instance with serial number {key} found in {cls.__name__} family")
        raise TypeError(f"Invalid key type: {type(key).__name__}. Expected int for serial number lookup.")

    def delete(self):
        type_alias = self._type_alias
        serial_number = getattr(self, 'serial_number', None)
        if serial_number is not None and type_alias in self._serial_map_dict and serial_number in self._serial_map_dict[type_alias]:
            del self._serial_map_dict[type_alias][serial_number]
        key = (self.name, self.__class__.__name__)
        if key in self._instances:
            del self._instances[key]

class DataFreq(Enum):
    MIN1 = pd.Timedelta('1min')
    MIN2 = pd.Timedelta('2min')
    MIN5 = pd.Timedelta('5min')
    MIN10 = pd.Timedelta('10min')
    MIN15 = pd.Timedelta('15min')
    MIN20 = pd.Timedelta('20min')
    MIN30 = pd.Timedelta('30min')
    HOUR1 = pd.Timedelta('1h')
    HOUR2 = pd.Timedelta('2h')
    DAY1 = pd.Timedelta('1day')
    DAY2 = pd.Timedelta('2day')
    DAY3 = pd.Timedelta('3day')
    DAY5 = pd.Timedelta('5day')
    DAY10 = pd.Timedelta('10day')
    WEEK1 = pd.Timedelta('7day')

def _process_data_freq(data_freq: Optional[Any] = None) -> DataFreq:
    if isinstance(data_freq, DataFreq):
        return data_freq
    if isinstance(data_freq, str):
        try:
            return DataFreq[data_freq]
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
    TIMESTAMP = 'T'
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
    ADJUST_SUFFIX = 'ADJ'
    PRODUCT_NAME = 'PN'

def _process_data_col(col: Optional[Any] = None) -> DataColumn:
    if isinstance(col, DataColumn):
        return col
    if isinstance(col, str):
        try:
            return DataColumn(col)
        except:
            try:
                return DataColumn[col]
            except:
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
            try:
                return DataSource(name)
            except:
                pass
        else:
            try:
                return DataSource.__class_getitem__(name)
            except:
                pass
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
                 if_object_is_in_source: Callable[[UniqueObject], bool],
                 get_object_path: Callable[[UniqueObject], Any]):
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
            self._is_object_in_source_func = if_object_is_in_source
            self._get_object_path_func = get_object_path
            self.timezone: str = ''

    def if_object_is_in_source(self, object: UniqueObject) -> bool:
        if hasattr(object, 'timezone') \
            and getattr(object, 'timezone') is not None:
            if self.timezone and getattr(object, 'timezone') \
                and getattr(object, 'timezone') != self.timezone:
                return False
        return self._is_object_in_source_func(object)

    def get_object_path(self, object: UniqueObject) -> Any:
        return self._get_object_path_func(object)
    
    def set_timezone(self, timezone: str) -> None:
        self.timezone = timezone
    
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

    def __init__(self, name: str, object: UniqueObject, data_freq: DataFreq, *args, **kwargs):
        if not hasattr(self, '_initialized'):
            super().__init__(name=name)
            self.object = object
            self.freq = data_freq
            self.data: pd.DataFrame = pd.DataFrame()
            self.current_source: DataSource
            self.path: Any
            self.start_date: pd.Timestamp
            self.end_date: pd.Timestamp
            self.timezone: str = kwargs.get('timezone', '')

    def list_available_sources(self) -> List[DataSource]:
        lst = []
        for source in DataSourceRegister().get_all_sources():
            if source.if_object_is_in_source(self.object) and source.freq == self.freq:
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
            raise ValueError(f"Data source {source.alias} is not available for object {self.object.name}")
        
    def get_current_source(self) -> DataSource:
        if not hasattr(self, 'current_source'):
            available_sources = self.list_available_sources()
            if len(available_sources) == 0:
                raise ValueError(f"No data source available for object {self.object.name}")
            self.current_source = available_sources[0]
        return self.get('current_source')

    def _load_data(self, source: Optional[Any] = None) -> pd.DataFrame:
        source = self.set_current_source(source) if source is not None else self.get_current_source()
        assert source is not None
        self.path = source.get_object_path(self.object)
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
                  filter_object: bool = False,
                  filter_object_attr: str = 'name') -> pd.DataFrame:
        self.data = loaded_data if loaded_data is not None else self._load_data(source)
        self._map_time_cols(time_cols_mapping)
        self._map_data_cols(data_cols_mapping)
        if filter_object:
            filter_object_name = getattr(self.object, filter_object_attr)
            self.data = self.data[self.data[DataColumn.PRODUCT_NAME] == filter_object_name]
        self._set_time_index(time_index)
        return self.data
    
    if TYPE_CHECKING:
        from Factor import FactorFamily

    def get_data(self, factor_family: Optional[FactorFamily] = None, 
                 extra_time_col_freq: Optional[Any] = None,
                 extra_time_col_freq_session: bool = False,
                 extra_time_col_bfill: bool = True,
                 extra_time_col_stem: str = '_SIGNAL',
                 copy: bool = True, **kwargs) -> pd.DataFrame:
        data, _ = self._get_data(factor_family=factor_family,
            extra_time_col_freq=extra_time_col_freq,
            extra_time_col_freq_session=extra_time_col_freq_session,
            extra_time_col_bfill=extra_time_col_bfill,
            extra_time_col_stem=extra_time_col_stem,
            extra_time_col_group_by=False,
            copy=copy, **kwargs)
        return data
    
    def _get_data(self, factor_family: Optional[FactorFamily] = None, 
                 extra_time_col_freq: Optional[Any] = None,
                 extra_time_col_freq_session: bool = False,
                 extra_time_col_bfill: bool = True,
                 extra_time_col_stem: str = '_SIGNAL',
                 extra_time_col_groupby: bool = False,
                 copy: bool = True, **kwargs) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        
        if self.data.empty:
            self.load_data()
        data = self.data.copy() if copy else self.data
        if factor_family is not None:
            start_calc_time = factor_family.current_start_calc_time
        else:
            start_calc_time = kwargs.get('start_calc_time', None)
        if start_calc_time is not None:
            col, time = start_calc_time
            data = data[data.index.get_level_values(col) >= time]

        if extra_time_col_groupby:
            assert extra_time_col_freq is not None
            extra_time_col_bfill = True
        if extra_time_col_freq is not None or extra_time_col_freq_session:
            if extra_time_col_freq_session:
                extra_time_col_freq = _process_data_freq('1d')
                extra_time_col_name = extra_time_col_stem + '@SESSION'
            else:
                extra_time_col_freq = _process_data_freq(extra_time_col_freq)
                extra_time_col_name = extra_time_col_stem + '@' + extra_time_col_freq.name
            if extra_time_col_name not in data.columns:
                if extra_time_col_freq_session:
                    if DataFreq.DAY1.name in data.index.names and DataFreq.MIN1.name in data.index.names:
                        day1name = DataFreq.DAY1.name
                        min1name = DataFreq.MIN1.name
                        day1series = data.index.get_level_values(day1name).to_series().reset_index(drop=True)
                        min1series = data.index.get_level_values(min1name).to_series().reset_index(drop=True)
                        time_part = min1series.dt.time
                        cond = (time_part >= pd.Timestamp('09:00').time()) & (time_part <= pd.Timestamp('15:00').time())
                        signal_time = day1series + pd.Timedelta('9 hours')
                        signal_time[cond] = day1series[cond] + pd.Timedelta('15 hours')
                        data.index = pd.MultiIndex.from_arrays([day1series, signal_time], names=[day1name, extra_time_col_name])
                        info = {}
                        if extra_time_col_groupby:
                            groupby_index = [day1name, extra_time_col_name]
                            info['groupby_index'] = groupby_index
                            info['grouped'] = data.groupby(groupby_index)
                        return data, info
                    else:
                        return data, {'success': False}
                if extra_time_col_freq.name in data.index.names:
                    if extra_time_col_groupby:
                        data_grouped = data.groupby(extra_time_col_freq.name)
                        return data, {'grouped': data_grouped, 'groupby_index': [extra_time_col_freq.name]}
                    return data, {}
                elif extra_time_col_freq.value > pd.Timedelta('1day') \
                    and extra_time_col_freq.value.total_seconds() % pd.Timedelta('1day').total_seconds() == 0 \
                    and DataFreq.DAY1.name in data.index.names:
                    day1series = data.index.get_level_values(DataFreq.DAY1.name).to_series().reset_index(drop=True)
                    period = int(extra_time_col_freq.value.total_seconds() / pd.Timedelta('1d').total_seconds())
                    pos = day1series != day1series.shift(-1)
                    pos = pos[pos==True][period-1::period]
                    series = day1series.where(pos)
                    series = series.bfill() if extra_time_col_bfill else series
                    data[extra_time_col_name] = series.values
                    if DataFreq.MIN1.name in data.index.names:
                        index_names = [extra_time_col_name, DataFreq.DAY1.name, DataFreq.MIN1.name]
                    else:
                        index_names = [extra_time_col_name, DataFreq.DAY1.name]
                    if extra_time_col_groupby:
                        data_grouped = data.groupby([extra_time_col_name])
                        return data, {'grouped': data_grouped, 'groupby_index': [extra_time_col_name]}
                    else:
                        return data.reset_index().set_index(index_names), {}
                elif extra_time_col_freq.value < pd.Timedelta('1day') \
                    and extra_time_col_freq.value.total_seconds() % pd.Timedelta('1min').total_seconds() == 0 \
                    and DataFreq.MIN1.name in data.index.names:
                    min1series = data.index.get_level_values(DataFreq.MIN1.name).to_series().reset_index(drop=True)
                    period = int(extra_time_col_freq.value.total_seconds() / pd.Timedelta('1min').total_seconds())
                    pos = min1series.index % period == period - 1
                    series = min1series.where(pos)
                    series = series.bfill() if extra_time_col_bfill else series
                    data[extra_time_col_name] = series.values
                    data = data.reset_index().set_index([extra_time_col_name] + data.index.names)
                    info = {}
                    if DataFreq.DAY1.name in data.index.names:
                        extra_time_col_name_day1 = extra_time_col_stem + '@' + DataFreq.DAY1.name
                        info['extra_time_col_name_day1'] = extra_time_col_name_day1
                        day1series = data.index.get_level_values(DataFreq.DAY1.name).to_series().reset_index(drop=True)
                        day1series = day1series.where(pos)
                        day1series = day1series.bfill() if extra_time_col_bfill else day1series
                        data[extra_time_col_name_day1] = day1series.values
                        groupby_index = [extra_time_col_name_day1, extra_time_col_name]
                        index_names = [DataFreq.DAY1.name, extra_time_col_name_day1, extra_time_col_name, DataFreq.MIN1.name] 
                    else:
                        groupby_index = [extra_time_col_name]
                        index_names = [extra_time_col_name, DataFreq.MIN1.name] 
                    if extra_time_col_groupby:
                        info['groupby_index'] = groupby_index
                        info['grouped'] = data.groupby(groupby_index)
                        return data, info
                    else:
                        return data.reset_index().set_index(index_names), info
                else:
                    raise ValueError(f"Cannot generate extra time column with frequency {extra_time_col_freq} from existing data")
            else:
                raise ValueError(f"Extra time column name {extra_time_col_name} already exists in data")
        else:  
            return data, {}
    
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

        if not isinstance(self.object, Futures):
            return self.get_data(copy=copy)
        if not isinstance(cols, list):
            cols = [cols]
        df = self.get_data(copy=copy)
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