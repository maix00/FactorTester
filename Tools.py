from abc import ABC
from weakref import WeakValueDictionary
from typing import TYPE_CHECKING, Callable, List, Dict, Optional, Sequence, Set, Tuple, Any, Literal, override
import pandas as pd
from pandas.core.groupby import DataFrameGroupBy
from enum import Enum

class UniqueObject(ABC):
    '''
        唯一对象基类：每个实例根据其 name 属性唯一标识，且同一类的实例之间 name 不重复。
        子类：SerialObject, Product, CNFutures, Factor, Parameter, DataSource, DataMeta 等。
    '''

    _instances = WeakValueDictionary()


    def __new__(cls, name: str, *args, **kwargs):
        key = (name, cls.__name__)
        if key in cls._instances:
            return cls._instances[key]
        
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
            owner = cls
        
        owner._type_alias = type_alias
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
    DAY20 = pd.Timedelta('20day')
    WEEK1 = pd.Timedelta('7day')

    def is_day_multiple(self) -> bool:
        return self.value >= pd.Timedelta('1day') and self.value.total_seconds() % pd.Timedelta('1day').total_seconds() == 0

def _process_data_freq(data_freq: Optional[Any] = None) -> DataFreq:
    if isinstance(data_freq, DataFreq):
        return data_freq
    if isinstance(data_freq, str):
        data_freq = data_freq.split('@')[-1].upper()
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
        col = col.removeprefix('DataColumn.').upper()
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
                 get_object_path: Callable[[UniqueObject], Any],
                 if_object_is_in_source: Optional[Callable[[UniqueObject], bool]] = None, *args, **kwargs):
        if not hasattr(self, '_initialized'):
            super().__init__(type_alias='DS', alias=alias)
            self._register = DataSourceRegister() # Weak Value
            self._register.register(self)
            if len(self._register.get_all_sources()) == 1:
                self._register.set_default_source(self)
            self.alias = alias
            self.freq = data_freq
            self._get_object_path_func = get_object_path
            if if_object_is_in_source is None:
                import os
                self._is_object_in_source_func = lambda object: os.path.isfile(get_object_path(object))
            else:
                self._is_object_in_source_func = if_object_is_in_source
            self.timezone = kwargs.get('timezone', None)
            self.set_time_cols_mapping(kwargs.get('time_cols_mapping', {}))
            self.set_data_cols_mapping(kwargs.get('data_cols_mapping', {}))

    def if_object_is_in_source(self, object: UniqueObject) -> bool:
        if hasattr(object, 'timezone') and getattr(object, 'timezone') != self.timezone:
            return False
        return self._is_object_in_source_func(object)

    def get_object_path(self, object: UniqueObject) -> Any:
        return self._get_object_path_func(object)
    
    def set_time_cols_mapping(self, mapping: Dict[Any, Any]) -> None:
        self.time_cols_mapping = {k: _process_data_freq(v).name for k, v in mapping.items()}

    def set_data_cols_mapping(self, mapping: Dict[Any, Any]) -> None:
        self.data_cols_mapping = {k: _process_data_col(v).name for k, v in mapping.items()}

if __name__ == '__main__':
    ds1 = DataSource('source1')
    print(ds1)
    ds = DataSourceRegister().get_default_source()
    print(ds)

class DataMeta(SerialObject):
    _instances = WeakValueDictionary()

    def __new__(cls, alias: Optional[str] = None, *args, **kwargs):
        return super().__new__(cls, type_alias='DM', alias=alias)

    def __init__(self, object: UniqueObject, data_freq: DataFreq, 
                 original_object: Optional[UniqueObject] = None,
                 alias: Optional[str] = None, *args, **kwargs):
        if not hasattr(self, '_initialized'):
            alias = '(' + object.alias + ')' + ('_' + alias if alias else '')
            super().__init__(type_alias='DM', alias=alias)
            self.object = object
            self.original_object = object if original_object is None else original_object
            self.freq = data_freq
            self.data: pd.DataFrame = pd.DataFrame() if 'data' not in kwargs else kwargs.pop('data')
            self.current_source: DataSource
            self.path: Any
            self.timezone = kwargs.get('timezone', None)

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
                  filter_object_attr: str = 'name', **kwargs) -> pd.DataFrame:
        self.data = loaded_data if loaded_data is not None else self._load_data(source)
        self._map_time_cols(time_cols_mapping)
        self._map_data_cols(data_cols_mapping)
        if filter_object:
            filter_object_name = getattr(self.object, filter_object_attr)
            self.data = self.data[self.data[DataColumn.PRODUCT_NAME] == filter_object_name]
        self._set_time_index(time_index)
        return self.data
    
    def get_data(self, copy: bool = False, **kwargs) -> pd.DataFrame:
        if 'data' in kwargs and kwargs['data'] is not None:
            data = kwargs['data']
        else:
            if self.data.empty or 'source' in kwargs:
                self.load_data(**kwargs)
            data = self.data
        return data.copy() if copy else data
    
    def get_level_index(self, level: Any, **kwargs) -> pd.Index:
        return self._get_level_index(self.get_data(**kwargs), level)

    def _get_level_index(self, index: Any, level: Any) -> pd.Index:
        if not isinstance(index, pd.Index):
            index = index.index
        assert isinstance(index, pd.Index)
        if isinstance(level, list):
            level = [next((lvl for lvl in index.names if str(lvl).split('@')[-1] == _process_data_freq(lvl_freq).name), None) for lvl_freq in level]
            return pd.MultiIndex.from_arrays([index.get_level_values(lvl) for lvl in level], names=level)
        else:
            level = next((lvl for lvl in index.names if str(lvl).split('@')[-1] == _process_data_freq(level).name), None)
            return index.get_level_values(level)

    def _process_start_calc_point(self, object: Optional[UniqueObject] = None, **kwargs) -> Tuple[Optional[Any], Optional[bool]]:
        from Parameter import DateOrTimeParam
        if object is not None and isinstance(object, DataMeta) \
            and callable(get_param := getattr(object.original_object, 'get_StartCalcPointParam', None)):
            StartCalcPointParam = get_param()
            assert isinstance(StartCalcPointParam, DateOrTimeParam)
            time = StartCalcPointParam.get_value(object.original_object)
            time_is_date = StartCalcPointParam.is_date(object.original_object)
        else:
            StartCalcPointParam = kwargs.get('StartCalcPointParam', None)
            if StartCalcPointParam is not None:
                assert isinstance(StartCalcPointParam, DateOrTimeParam)
                time = StartCalcPointParam.default_value
                time_is_date = StartCalcPointParam.is_date(value=time)
            else:
                time = None
                time_is_date = None
        return time, time_is_date
    
    def _filter_data_by_start_calc_point(self, data: pd.DataFrame, time_col: Optional[str] = None,
                                        time: Optional[Any] = None, time_is_date: Optional[bool] = None,
                                        copy: bool = False, **kwargs) -> pd.DataFrame:
        if time is None or time_is_date is None:
            time, time_is_date = self._process_start_calc_point(object=self, **kwargs)
        if time is not None and time_is_date is not None:
            if time_col is None:
                data_day_col = [str(level) for level in data.index.names if _process_data_freq(str(level).split('@')[-1]).value >= pd.Timedelta('1day')][-1]
                data_min_col = [str(level) for level in data.index.names if _process_data_freq(str(level).split('@')[-1]).value >= pd.Timedelta('1min')][-1]
                if self.freq.value >= pd.Timedelta('1day') and time_is_date:
                    time_col = data_day_col
                else:
                    time_col = data_day_col if time_is_date else data_min_col
            data = data[self._get_level_index(data, time_col) >= pd.Timestamp(time)]
        if copy:
            data = data.copy()
        return data

    def _get_signal_index(self, freq: Any,  bfill: Optional[int] = None, min_periods: Optional[Any] = None,
                          end_session_skip: bool = False, end_session_gap: pd.Timedelta = pd.Timedelta('3hour'),
                          copy: bool = False, _offset: int = 0, _copy_index_name: bool = False, 
                          day_basepoint: str|Callable = 'last', # 'last', 'first', '09:01:00'
                          **kwargs) -> Dict[str, Any]:

        index_name_stem: str = '_SIGNAL'
        assert freq is not None, "Frequency must be provided"
        freq = _process_data_freq(freq)
        copy = True if _offset != 0 else copy
        data = self.get_data(copy=copy, data=kwargs.pop('data', None), **kwargs)
        data = self._filter_data_by_start_calc_point(data, **kwargs)
        index_data_freq = [_process_data_freq(level) for level in data.index.names]
        
        index_map_of_multiple = [freq.value.total_seconds() % idx_freq.value.total_seconds() == 0 for idx_freq in index_data_freq]
        first_true_idx = next((i for i, is_multiple in enumerate(index_map_of_multiple) if is_multiple), None)
        assert first_true_idx is not None, f"Frequency {freq} is not a multiple of any existing index frequency"
        first_true_freq = index_data_freq[first_true_idx]
        multiple = int(freq.value.total_seconds() / first_true_freq.value.total_seconds())
        
        min_periods_freq = _process_data_freq(min_periods) if min_periods is not None else None
        min_multiple = int(min_periods_freq.value.total_seconds() / first_true_freq.value.total_seconds()) if min_periods_freq is not None else None
        
        signal_index_name = next((str(level) for level in data.index.names if str(level).startswith(index_name_stem)), None)
        data_freq = _process_data_freq(signal_index_name) if signal_index_name is not None else index_data_freq[-1]
        data_multiple = int(freq.value.total_seconds() / data_freq.value.total_seconds())
        
        first_true_series = self._get_level_index(data, data.index.names[first_true_idx]).to_series().reset_index(drop=True)
        
        if isinstance(day_basepoint, str):
            day_basepoint = day_basepoint.lower()
            if day_basepoint == 'last':
                series = data.groupby(str(data.index.names[first_true_idx])).cumcount(ascending=False) == 0
            elif day_basepoint == 'first':
                series = data.groupby(str(data.index.names[first_true_idx])).cumcount() == 0
            else:
                try:
                    base_time = pd.Timestamp(day_basepoint).time()
                    series = data.groupby(str(data.index.names[first_true_idx])).transform(lambda x: pd.DatetimeIndex(x.index.get_level_values(-1)).time == base_time)
                except:
                    raise ValueError("Invalid day_basepoint value. Must be 'last', 'first', or a valid time string like '09:01:00'")
        else:
            series = day_basepoint(data.groupby(str(data.index.names[first_true_idx])))
        
        if not any(series):
            # If no True values are found, we can default to using the first position of each group as the base point
            series = data.groupby(str(data.index.names[first_true_idx])).cumcount() == 0

        assert isinstance(series, pd.Series) and series.dtype == bool, "day_basepoint function must return a boolean Series"
        first_true_change_pos = series.reset_index(drop=True).index[series]

        if end_session_skip and freq.value < pd.Timedelta('1day'):
            last_col_series = self._get_level_index(data, data.index.names[-1]).to_series().reset_index(drop=True)
            end_session_pos = last_col_series[last_col_series.shift(-1) - last_col_series >= end_session_gap].index
            signal_map_within_first_true_change_mask = first_true_change_pos.isin({i for start, end in zip([0] + (end_session_pos[:-1].values + 1).tolist(), end_session_pos) for i in range(start + multiple - 1, end + 1, multiple) if start + multiple - 1 <= end})
        else:
            assert 0 <= _offset < multiple, f"Offset must be between 0 and {multiple - 1}"
            index = first_true_change_pos.to_series().reset_index(drop=True).index
            signal_map_within_first_true_change_mask = (index % multiple == multiple - 1 - _offset)

        signal_pos_within_first_true_series = first_true_change_pos[signal_map_within_first_true_change_mask]
        signal_map_within_first_true_series = first_true_series.index.isin(signal_pos_within_first_true_series)
        signal_series_within_first_true_series = first_true_series.where(signal_map_within_first_true_series)

        def _bfill(obj, bfill: Optional[int] = None) -> pd.Series:
            return obj if bfill is None else obj.bfill(limit=bfill)
        
        def _get_extended_index(bfill: Optional[int] = None) -> Tuple[pd.MultiIndex, List[str], List[str]]:
            left_indices = data.index.names[:first_true_idx]
            right_indices = data.index.names[first_true_idx:]
            left_series_dict = {idx: self._get_level_index(data, idx).to_series().where(signal_map_within_first_true_series) for idx in left_indices}
            right_series_dict = {idx: self._get_level_index(data, idx).to_series() for idx in right_indices}
            index_arrays = [_bfill(left_series_dict[idx], bfill=bfill) for idx in left_indices] \
                            + [_bfill(signal_series_within_first_true_series, bfill=bfill)] \
                            + [_bfill(right_series_dict[idx], bfill=None) for idx in right_indices]
            index_name = index_name_stem + '@' + (freq.name if not _copy_index_name else first_true_freq.name)
            left_indices = [str(idx).split('@')[-1] for idx in left_indices]
            right_indices = [str(idx).split('@')[-1] for idx in right_indices]
            index_names_for_groupby = left_indices + [index_name]
            index_names = index_names_for_groupby + right_indices[1:]
            extended_index = pd.MultiIndex.from_arrays(index_arrays, names=index_names_for_groupby + right_indices)
            return extended_index, index_names_for_groupby, index_names
        
        signal_index, _, index_names = _get_extended_index()
        signal_index = self._get_level_index(signal_index.dropna(), index_names)
        bfill = bfill if bfill is not None else data_multiple - 1
        extended_index, index_names_for_groupby, index_names = _get_extended_index(bfill=bfill)

        mask = ~extended_index.to_frame().isna().any(axis=1)
        extended_index = extended_index[mask]
        data = data[mask.values]

        return {
            'data': data,
            'signal_index': signal_index,
            'extended_index': extended_index,
            'index_names_for_groupby': index_names_for_groupby,
            'index_names': index_names,
            'min_multiple': min_multiple,
            'first_true_col': str(data.index.names[first_true_idx]).split('@')[-1],
        }
    
    def groupby(self, freq: Optional[Any] = None, bfill: Optional[int] = None,
                copy: bool = True, **kwargs) -> DataMeta:
        results = self._get_signal_index(freq=freq, bfill=bfill, copy=copy, **kwargs)
        data = results['data']
        data.index = results['extended_index']
        kwargs.pop('data', None)
        return self._wrap(target_type=GroupedOperator, data=data,
                          groupby_index_names=results['index_names_for_groupby'],
                          original_index_names=results['index_names'],
                          alias=kwargs.pop('alias', None), **kwargs)
    
    def rolling_indays(self, freq: Any, min_periods: Optional[Any] = None, **kwargs) -> DataMeta:
        assert freq is not None, "Frequency must be provided"
        freq = _process_data_freq(freq)
        min_periods = _process_data_freq(min_periods) if min_periods is not None else freq
        assert min_periods is not None, "min_periods must be provided for rolling in days"
        assert min_periods.value <= freq.value, "min_periods must be less than or equal to freq for rolling in days"
        assert freq.is_day_multiple(), "Frequency must be a multiple of 1 day for rolling in days"
        multiple = int(freq.value.total_seconds() / pd.Timedelta('1day').total_seconds())
        list_of_data = []
        groupby_index_names = None
        original_index_names = None
        day_basepoint = kwargs.pop('day_basepoint', 'last')
        day_basepoint_str = (day_basepoint.upper() if day_basepoint.lower() in ['first', 'last'] \
                             else f"{day_basepoint}_OR_FIRST") if isinstance(day_basepoint, str) \
                                else f"({day_basepoint})".upper()
        min_multiple = None
        first_true_col = None
        for _offset in range(multiple):
            results = self._get_signal_index(freq=freq, copy=True, _offset=_offset, min_periods=min_periods, 
                                             _copy_index_name=True, day_basepoint=day_basepoint, **kwargs)
            data = results['data']
            data.index = results['extended_index']
            if min_multiple is None:
                min_multiple = results['min_multiple']
                assert first_true_col is None
                first_true_col = results['first_true_col']
            else:
                assert min_multiple == results['min_multiple'], "min_multiple does not match across offsets"
                assert first_true_col == results['first_true_col'], "First true column does not match across offsets"
            list_of_data.append(data)
            if groupby_index_names is None:
                groupby_index_names = results['index_names_for_groupby']
            else:
                assert groupby_index_names == results['index_names_for_groupby'], "Groupby index names do not match across offsets"
            if original_index_names is None:
                original_index_names = results['index_names']
            else:
                assert original_index_names == results['index_names'], "Original index names do not match across offsets"
        return self._wrap(data=kwargs.pop('data', self.data),
                          target_type=_RollingInDays, list_of_data=list_of_data,
                          groupby_index_names=groupby_index_names,
                          original_index_names=original_index_names,
                          min_multiple=min_multiple, first_true_col=first_true_col,
                          alias=kwargs.pop('alias', f"ROLLING_INDAYS_{freq.name}_AT_{day_basepoint_str}"), **kwargs)
    
    def _sync_signal(self, signal_datameta: DataMeta, freq: Any, replace: bool = False,
                     day_basepoint: str|Callable = 'last',
                     end_session_skip: bool = True, 
                     end_session_gap: pd.Timedelta = pd.Timedelta('3hour'), **kwargs) -> DataMeta:
        signal = signal_datameta.data
        if isinstance(signal, pd.DataFrame):
            assert len(signal.columns) == 1, "Signal must have only one column"
            signal = signal.squeeze()
        assert isinstance(signal, pd.Series), "Signal must be a Series after squeezing"
        index = self._get_signal_index(freq=freq, end_session_skip=end_session_skip, end_session_gap=end_session_gap, day_basepoint=day_basepoint, copy=True, **kwargs)['signal_index']
        assert index.nlevels == signal.index.nlevels, "Index levels do not match between signal index and signal index"
        if not replace:
            map = signal.index.isin(index)
            signal = signal[map]
        else:
            signal_col_signal = next((name for name in signal.index.names if isinstance(name, str) and name.startswith('_SIGNAL@')), None)
            assert signal_col_signal is not None, "Signal index must have a level that starts with '_SIGNAL@' when replace is True"
            signal_col_index = next((name for name in index.names if isinstance(name, str) and name.startswith('_SIGNAL@')), None)
            assert signal_col_index is not None, "Index must have a level that starts with '_SIGNAL@' when replace is True"
            map = signal.index.get_level_values(signal_col_signal).isin(index.get_level_values(signal_col_index))
            signal = signal[map]
            signal.index = index
        signal.index.names = index.names
        signal.rename(self.object.alias, inplace=True)
        return signal_datameta._wrap(signal, alias=f"SYNCED_SIGNAL_{_process_data_freq(freq).name}")
    
    def sync_signal(self, signal: Any, freq: Any, replace: bool = False,
                    day_basepoint: str|Callable = 'last',
                    end_session_skip: bool = True, 
                    end_session_gap: pd.Timedelta = pd.Timedelta('3hour'), **kwargs) -> pd.Series:
        series = self._sync_signal(signal, freq, end_session_skip=end_session_skip, end_session_gap=end_session_gap,
                                   day_basepoint=day_basepoint, replace=replace, **kwargs).data
        assert isinstance(series, pd.Series), "Synced signal must be a Series"
        return series
    
    def rolling(self, window: int|str|pd.Timedelta|DataFreq, 
                min_periods: Optional[int|str|pd.Timedelta|DataFreq] = None, copy: bool = False, **kwargs) -> DataMeta:
        data = self.get_data(copy=copy, data=kwargs.pop('data', None), **kwargs)
        data = self._filter_data_by_start_calc_point(data, **kwargs)
        data_freq = _process_data_freq(data.index.names[-1])
        if isinstance(window, int):
            assert min_periods is None or isinstance(min_periods, int), "min_periods must be an integer when window is an integer"
            min_periods = min_periods if min_periods is not None else window
            return self._wrap(target_type=RollingOperator, data=data, window=window, min_periods=min_periods, alias=f"ROLLING_{window}", **kwargs)
        else:
            window_freq = _process_data_freq(window)
            min_periods = _process_data_freq(min_periods) if min_periods is not None else window_freq
            if window_freq.is_day_multiple() and data_freq.value < pd.Timedelta('1day'):
                return self.rolling_indays(freq=window_freq, data=data, min_periods=min_periods, **kwargs)
            elif window_freq.value.total_seconds() % data_freq.value.total_seconds() == 0:
                window_size = int(window_freq.value.total_seconds() / data_freq.value.total_seconds())
                min_periods_size = int(min_periods.value.total_seconds() / data_freq.value.total_seconds())
                return self._wrap(target_type=RollingOperator, data=data, window=window_size, min_periods=min_periods_size, alias=f"ROLLING_{window_size}", **kwargs)
            else:
                raise ValueError(f"Window frequency {window_freq} is not compatible with data frequency {data_freq}")

    def pct_change(self, window: int|str|pd.Timedelta = 1, 
                   day_basepoint: str|Callable = 'last', # 'last', 'first', '09:01:00'
                   col: Optional[Any] = None, copy: bool = False, **kwargs) -> DataMeta:
        data = self.get_data(copy=copy, data=kwargs.pop('data', None), **kwargs)
        data = self._filter_data_by_start_calc_point(data, **kwargs)
        data_freq = _process_data_freq(data.index.names[-1])
        if col is not None:
            alias = f"{col}_PCT_CHANGE"
            if col not in data.columns:
                raise ValueError(f"Column {col} not found in data")
            col = _process_data_col(col).name
            data = data[col]
        else:
            alias = "PCT_CHANGE"
            if isinstance(data, pd.Series):
                pass
            else:
                col = data.columns[0]
                data = data[col]
        if isinstance(window, int):
            result = data.pct_change(periods=window)
            signal_col = next((name for name in data.index.names if isinstance(name, str) and name.startswith('_SIGNAL@')), None)
            if signal_col is None:
                result.index.names = [str(name).split('@')[-1] for name in result.index.names[:-1]] + ['_SIGNAL@' + str(result.index.names[-1]).split('@')[-1]]
            return self._wrap(result, alias=alias + '_' + str(window))
        else:
            window_freq = _process_data_freq(window)
            if window_freq.is_day_multiple() and data_freq.value < pd.Timedelta('1day'):

                tiny_window = '1min'
                rolling_indays = self.rolling_indays(freq=window_freq, data=data, min_periods=tiny_window, day_basepoint=day_basepoint, **kwargs)
                    
                index_data_freq = [_process_data_freq(level) for level in data.index.names]
                index_map_of_multiple = [window_freq.value.total_seconds() % idx_freq.value.total_seconds() == 0 for idx_freq in index_data_freq]
                first_true_idx = next((i for i, is_multiple in enumerate(index_map_of_multiple) if is_multiple), None)
                assert first_true_idx is not None, f"Frequency {window_freq} is not a multiple of any existing index frequency"
                first_true_freq = index_data_freq[first_true_idx]
                window_size = int(window_freq.value / first_true_freq.value)

                return rolling_indays.last().pct_change(window_size)
            
            elif window_freq.value.total_seconds() % data_freq.value.total_seconds() == 0:
                window_size = int(window_freq.value / data_freq.value)
                result = data.pct_change(periods=window_size)
                signal_col = next((name for name in data.index.names if isinstance(name, str) and name.startswith('_SIGNAL@')), None)
                if signal_col is None:
                    result.index.names = [str(name).split('@')[-1] for name in result.index.names[:-1]] + ['_SIGNAL@' + str(result.index.names[-1]).split('@')[-1]]
                return self._wrap(result, alias=alias + '_' + str(window_size))
            else:
                raise ValueError(f"Window frequency {window_freq} is not compatible with data frequency {data_freq}")

    def __getattr__(self, name: str) -> Any:
            try:
                method = self.__dict__.get(name)
                if method is not None:
                    return method
            except AttributeError:
                pass
            data = self.__dict__.get('data')
            if data is None:
                raise AttributeError(f"'DataMeta' object has no attribute '{name}'")
            try:
                method = getattr(data, name)
            except AttributeError:
                raise AttributeError(f"'DataMeta' object has no attribute '{name}'")
            def wrapper(*args, **kwargs):
                result = method(*args, **kwargs)
                param_str = _rectify_args_kwargs(*args, **kwargs)
                return self._wrap(result, alias=f"{name.upper()}{param_str}")
            return wrapper
    
    def _wrap(self, data: Any, alias: str, target_type: Optional[type] = None, **kwargs) -> DataMeta:
        if isinstance(data, pd.DataFrame) or isinstance(data, pd.Series):
            target_type = target_type if target_type is not None else DataMeta
            return target_type(data=data, object=self, original_object=self.original_object,
                               alias=alias, data_freq=self.freq, timezone=self.timezone, **kwargs)
        else:
            raise NotImplementedError(f"Result type {type(data).__name__} is not supported for wrapping in DataMeta")

    def __dir__(self):
        own_attrs = set(super().__dir__())
        data_attrs = set(dir(self.data))
        return sorted(own_attrs | data_attrs)
    
    @staticmethod
    def _get_alias(other: Any) -> str:
        if hasattr(other, 'alias'):
            return '(' + (other.alias if other.alias is not None else str(other)) + ')'
        elif isinstance(other, str):
            return other
        else:
            return str(other)
    
    @staticmethod
    def _get_data(other: Any) -> Any:
        if isinstance(other, DataMeta):
            return other.data
        else:
            return other
    
    def __add__(self, other): return self._wrap((self.get_data() + self._get_data(other)).where(self.get_data().notna()), alias=f"ADD_{self._get_alias(other)}")
    def __sub__(self, other): return self._wrap((self.get_data() - self._get_data(other)).where(self.get_data().notna()), alias=f"SUB_{self._get_alias(other)}")
    def __mul__(self, other): return self._wrap((self.get_data() * self._get_data(other)).where(self.get_data().notna()), alias=f"MUL_{self._get_alias(other)}")
    def __truediv__(self, other): return self._wrap((self.get_data() / self._get_data(other)).where(self.get_data().notna()), alias=f"DIV_{self._get_alias(other)}")
    def __floordiv__(self, other): return self._wrap((self.get_data() // self._get_data(other)).where(self.get_data().notna()), alias=f"FLOORDIV_{self._get_alias(other)}")
    def __mod__(self, other): return self._wrap((self.get_data() % self._get_data(other)).where(self.get_data().notna()), alias=f"MOD_{self._get_alias(other)}")
    def __pow__(self, other): return self._wrap((self.get_data() ** self._get_data(other)).where(self.get_data().notna()), alias=f"POW_{self._get_alias(other)}")
    def __gt__(self, other): return self._wrap((self.get_data() > self._get_data(other)).where(self.get_data().notna()), alias=f"GT_{self._get_alias(other)}")
    def __lt__(self, other): return self._wrap((self.get_data() < self._get_data(other)).where(self.get_data().notna()), alias=f"LT_{self._get_alias(other)}")
    def __ge__(self, other): return self._wrap((self.get_data() >= self._get_data(other)).where(self.get_data().notna()), alias=f"GE_{self._get_alias(other)}")
    def __le__(self, other): return self._wrap((self.get_data() <= self._get_data(other)).where(self.get_data().notna()), alias=f"LE_{self._get_alias(other)}")
    def __eq__(self, other): return self._wrap((self.get_data() == self._get_data(other)).where(self.get_data().notna()), alias=f"EQ_{self._get_alias(other)}")
    @override
    def __ne__(self, other): #type: ignore[override]
        # if isinstance(other, DataMeta):
        #     return self.alias != other.alias
        return self._wrap((self.get_data() != self._get_data(other)).where(self.get_data().notna()), alias=f"NE_{self._get_alias(other)}")
    def __and__(self, other): return self._wrap((self.get_data() & self._get_data(other)).where(self.get_data().notna()), alias=f"AND_{self._get_alias(other)}")
    def __or__(self, other): return self._wrap((self.get_data() | self._get_data(other)).where(self.get_data().notna()), alias=f"OR_{self._get_alias(other)}")
    def __xor__(self, other): return self._wrap((self.get_data() ^ self._get_data(other)).where(self.get_data().notna()), alias=f"XOR_{self._get_alias(other)}")
    
    def __neg__(self): return self._wrap((-self.get_data()).where(self.get_data().notna()), alias=f"NEG")
    def __pos__(self): return self._wrap((+self.get_data()).where(self.get_data().notna()), alias=f"POS")
    def __abs__(self): return self._wrap(abs(self.get_data()).where(self.get_data().notna()), alias=f"ABS")
    def __invert__(self): return self._wrap((~self.get_data()).where(self.get_data().notna()), alias=f"INVERT")
    def __getitem__(self, key): return self._wrap(self.get_data()[(col := _process_data_col(key).name)], alias=col)
    def __setitem__(self, key, value): self.get_data()[_process_data_col(key).name] = value
    def __delitem__(self, key): del self.get_data()[_process_data_col(key).name]

    # 反向运算符（支持 scalar + meta）
    def __radd__(self, other): return self._wrap((self._get_data(other) + self.get_data()).where(self.get_data().notna()), alias=f"RADD_{self._get_alias(other)}")
    def __rsub__(self, other): return self._wrap((self._get_data(other) - self.get_data()).where(self.get_data().notna()), alias=f"RSUB_{self._get_alias(other)}")
    def __rmul__(self, other): return self._wrap((self._get_data(other) * self.get_data()).where(self.get_data().notna()), alias=f"RMUL_{self._get_alias(other)}")
    def __rtruediv__(self, other): return self._wrap((self._get_data(other) / self.get_data()).where(self.get_data().notna()), alias=f"RDIV_{self._get_alias(other)}")
    def __rfloordiv__(self, other): return self._wrap((self._get_data(other) // self.get_data()).where(self.get_data().notna()), alias=f"RFLOORDIV_{self._get_alias(other)}")
    def __rmod__(self, other): return self._wrap((self._get_data(other) % self.get_data()).where(self.get_data().notna()), alias=f"RMOD_{self._get_alias(other)}")
    def __rpow__(self, other): return self._wrap((self._get_data(other) ** self.get_data()).where(self.get_data().notna()), alias=f"RPOW_{self._get_alias(other)}")
    def __rand__(self, other): return self._wrap((self._get_data(other) & self.get_data()).where(self.get_data().notna()), alias=f"RAND_{self._get_alias(other)}")
    def __ror__(self, other): return self._wrap((self._get_data(other) | self.get_data()).where(self.get_data().notna()), alias=f"ROR_{self._get_alias(other)}")
    def __rxor__(self, other): return self._wrap((self._get_data(other) ^ self.get_data()).where(self.get_data().notna()), alias=f"RXOR_{self._get_alias(other)}")

    # 可选：支持 len() 和 bool()
    def __len__(self): return len(self.get_data())
    def __bool__(self): return bool(self.get_data()) if self.get_data().size else False

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

    def _set_time_index(self, index_names: Optional[Any] = None) -> pd.DataFrame:
        assert not self.data.empty
        if index_names is None:
            ds = self.get_current_source()
            index_names = sorted(ds.time_cols_mapping.values(), key=lambda x: DataFreq[x].value, reverse=True)
        for col in index_names:
            if col not in self.data.columns:
                raise ValueError(f"Column {col} not found in data")
            self.data[col] = pd.to_datetime(self.data[col])
        self.data.set_index(index_names, inplace=True)
        index = self.data.index
        index_tzaware_list = []
        for col in index.names:
            col = str(col)
            level_index = self.data.index.get_level_values(col)
            assert isinstance(level_index, pd.DatetimeIndex)
            if _process_data_freq(col).is_day_multiple():
                if level_index.tz is not None:
                    level_index = level_index.tz_localize(None)
            else:
                if level_index.tz is None:
                    level_index = level_index.tz_localize(self.timezone)
                elif level_index.tz is not None and str(level_index.tz) != self.timezone:
                    level_index = level_index.tz_convert(self.timezone)
            index_tzaware_list.append(level_index)
        self.data.index = pd.MultiIndex.from_arrays(index_tzaware_list, names=index.names)
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

class RollingOperator(DataMeta):
    def __init__(self, data: pd.DataFrame, window: int|str|pd.Timedelta, min_periods: Optional[int] = None, **kwargs):
        if not hasattr(self, '_initialized'):
            super().__init__(data=data, alias=kwargs.pop('alias', f"ROLLING_{window}"), 
                             object=kwargs.pop('object'), original_object=kwargs.pop('original_object', None), 
                             data_freq=kwargs.pop('data_freq'), timezone=kwargs.pop('timezone'), **kwargs)
            self.window = window
            self.min_periods = min_periods
            self.rolling = data.rolling(window=window, min_periods=min_periods, **kwargs)

    def __getattr__(self, name: str) -> Any:
        try:
            method = self.__dict__.get(name)
            if method is not None:
                return method
        except AttributeError:
            pass
        rolling = self.__dict__.get('rolling')
        if rolling is None:
            raise AttributeError(f"'RollingOperator' object has no attribute '{name}'")
        try:
            method = getattr(rolling, name)
        except AttributeError:
            raise AttributeError(f"'RollingOperator' object has no attribute '{name}'")
        def wrapper(*args, **kwargs):
            result = method(*args, **kwargs)
            result.index = self.data.index
            param_str = _rectify_args_kwargs(*args, **kwargs)
            return self._wrap(result, alias=f"{name.upper()}{param_str}")
        return wrapper

    def __dir__(self) -> List[str]:
        return sorted(set(super().__dir__()) | set(dir(self.rolling)))
    
    @override
    def __getitem__(self, key): # type: ignore[override]
        """支持 operator['column'] 语法"""
        return RollingOperator._ColumnSelector(self, key)
    
    class _ColumnSelector:
        def __init__(self, parent: Any, key):
            self.parent = parent
            self.key = key

        def __getattr__(self, name: str) -> Any:
            # 尝试从 parent.rolling 的列选择子对象获取方法
            try:
                method = getattr(self.parent.rolling[self.key], name)
            except AttributeError:
                raise AttributeError(f"'_ColumnSelector' object has no attribute '{name}'")
            # 包装方法，自动恢复索引
            def wrapper(*args, **kwargs):
                result = method(*args, **kwargs)
                result.index = self.parent.data.index
                param_str = _rectify_args_kwargs(*args, **kwargs)
                return self.parent._wrap(result, alias=f"{name.upper()}_{self.key}{param_str}")
            return wrapper

        def __dir__(self) -> List[str]:
            # 提供该列选择器可用的方法
            return sorted(set(super().__dir__()) | set(dir(self.parent.rolling[self.key])))
    
class GroupedOperator(DataMeta):
    def __init__(self, data: pd.DataFrame, groupby_index_names: List[str], original_index_names: Optional[List[str]] = None, **kwargs):
        if not hasattr(self, '_initialized'):
            super().__init__(data=data, alias=kwargs.pop('alias', 'GROUPBY'),
                             object=kwargs.pop('object'), original_object=kwargs.pop('original_object', None), 
                             data_freq=kwargs.pop('data_freq'), timezone=kwargs.pop('timezone'), **kwargs)
            self.original_index_names = original_index_names if original_index_names is not None else data.index.names
            self.groupby_index_names = groupby_index_names
            self.grouped = data.groupby(self.groupby_index_names, **kwargs)

    def _restore_index(self, result: Any) -> pd.DataFrame:
        if isinstance(result, pd.Series):
            result = result.to_frame()
        final_index = self.data.reset_index().groupby(self.groupby_index_names).last().reset_index().set_index(self.original_index_names).index
        result.index = final_index
        return result

    def __getattr__(self, name: str) -> Any:
        try:
            method = self.__dict__.get(name)
            if method is not None:
                return method
        except AttributeError:
            pass
        grouped = self.__dict__.get('grouped')
        if grouped is None:
            raise AttributeError(f"'GroupedOperator' object has no attribute '{name}'")
        try:
            method = getattr(grouped, name)
        except AttributeError:
            raise AttributeError(f"'GroupedOperator' object has no attribute '{name}'")
        def wrapper(*args, **kwargs):
            col = kwargs.pop('col', None)
            grouped = self.grouped if col is None else self.grouped[col]
            result = getattr(grouped, name)(*args, **kwargs)
            param_str = _rectify_args_kwargs(*args, **kwargs)
            return self._wrap(self._restore_index(result), alias=f"{name.upper()}{param_str}")
        return wrapper

    def __dir__(self) -> List[str]:
        return sorted(set(super().__dir__()) | set(dir(self.grouped)))

    @override
    def __getitem__(self, key): # type: ignore[override]
        """支持 operator['column'] 语法"""
        return GroupedOperator._ColumnSelector(self, key)

    class _ColumnSelector:
        def __init__(self, parent: Any, key):
            self.parent = parent
            self.key = key

        def __getattr__(self, name: str) -> Any:
            # 尝试从 parent.grouped 的列选择子对象获取方法
            try:
                method = getattr(self.parent.grouped[self.key], name)
            except AttributeError:
                raise AttributeError(f"'_ColumnSelector' object has no attribute '{name}'")
            # 包装方法，自动恢复索引
            def wrapper(*args, **kwargs):
                result = method(*args, **kwargs)
                param_str = _rectify_args_kwargs(*args, **kwargs)
                return self.parent._wrap(self.parent._restore_index(result), alias=f"{name.upper()}_{self.key}{param_str}")
            return wrapper

        def __dir__(self) -> List[str]:
            # 提供该列选择器可用的方法
            return sorted(set(super().__dir__()) | set(dir(self.parent.grouped[self.key])))
        
class _RollingInDays(DataMeta):
    def __init__(self, list_of_data: List[pd.DataFrame], 
                 groupby_index_names: List[str], original_index_names: List[str], **kwargs):
        if not hasattr(self, '_initialized'):
            self.min_multiple = kwargs.pop('min_multiple', None)
            self.first_true_col = kwargs.pop('first_true_col', None)
            self.groupby_index_names = groupby_index_names
            self.original_index_names = original_index_names
            super().__init__(data=kwargs.pop('data', None), alias=kwargs.pop('alias', 'ROLLING_INDAYS'),
                             object=kwargs.pop('object'), original_object=kwargs.pop('original_object', None), 
                             data_freq=kwargs.pop('data_freq'), timezone=kwargs.pop('timezone'), **kwargs)
            self.list_of_data = list_of_data
            self.list_of_groupby = [
                self._wrap(target_type=GroupedOperator, data=data, 
                           alias=f"ROLLING_INDAYS_GROUPBY_OFFSET_{i}",
                           groupby_index_names=groupby_index_names, 
                           original_index_names=original_index_names, **kwargs) 
                for i, data in enumerate(list_of_data)
            ]
            self.list_of_grouped = [groupby.grouped for groupby in self.list_of_groupby]

    def _restore_index_and_concat(self, list_of_result: Any) -> pd.DataFrame:
        restored_results = []
        for groupby, res in zip(self.list_of_groupby, list_of_result):
            restored_res = groupby._restore_index(res)
            restored_results.append(restored_res)
        return pd.concat(restored_results, axis=0).sort_index()

    def __getattr__(self, name: str) -> Any:
        try:
            method = self.__dict__.get(name)
            if method is not None:
                return method
        except AttributeError:
            pass
        list_of_grouped = self.__dict__.get('list_of_grouped')
        if list_of_grouped is None or len(list_of_grouped) == 0:
            raise AttributeError(f"'GroupedOperator' object has no attribute '{name}'")
        try:
            method = getattr(list_of_grouped[0], name)
        except AttributeError:
            raise AttributeError(f"'GroupedOperator' object has no attribute '{name}'")
        def wrapper(*args, **kwargs):
            col = kwargs.pop('col', None)
            list_of_grouped = self.list_of_grouped if col is None else [grouped[col] for grouped in self.list_of_grouped]
            list_of_target = [getattr(grouped, name) for grouped in list_of_grouped]
            list_of_count = [data.reset_index()[
                self.groupby_index_names + (
                    [data.name] if isinstance(data, pd.Series) else 
                    list(data.columns) if isinstance(data, pd.DataFrame) else []
                )].groupby(self.groupby_index_names).count().squeeze() 
                for data in self.list_of_data]
            if self.min_multiple is not None:
                import numpy as np
                list_of_result = [target(*args, **kwargs).where(count >= self.min_multiple, np.nan) for target, count in zip(list_of_target, list_of_count)]
            else:
                list_of_result = [target(*args, **kwargs) for target in list_of_target]
            param_str = _rectify_args_kwargs(*args, **kwargs)
            return self._wrap(self._restore_index_and_concat(list_of_result), alias=f"{name.upper()}{param_str}")
        return wrapper
    
    def __dir__(self) -> List[str]:
        return sorted(set(super().__dir__()) | set(dir(self.list_of_grouped[0])) if self.list_of_grouped else set())
    
    @override
    def __getitem__(self, key): # type: ignore[override]
        """支持 operator['column'] 语法"""
        return _RollingInDays._ColumnSelector(self, key)
    
    class _ColumnSelector:
        def __init__(self, parent: Any, key):
            self.parent = parent
            self.key = key

        def __getattr__(self, name: str) -> Any:
            try:
                getattr(self.parent.list_of_grouped[0][self.key], name)
            except AttributeError:
                raise AttributeError(f"'_ColumnSelector' object has no attribute '{name}'")
            def wrapper(*args, **kwargs):
                list_of_target = [getattr(grouped[self.key], name) for grouped in self.parent.list_of_grouped]
                list_of_count_func = [getattr(grouped[self.key], 'count') for grouped in self.parent.list_of_grouped]
                import numpy as np
                if self.parent.min_multiple is not None:
                    list_of_result = [target(*args, **kwargs).where(count_func() >= self.parent.min_multiple, np.nan) for target, count_func in zip(list_of_target, list_of_count_func)]
                else:
                    list_of_result = [target(*args, **kwargs) for target in list_of_target]
                param_str = _rectify_args_kwargs(*args, **kwargs)
                return self.parent._wrap(self.parent._restore_index_and_concat(list_of_result), alias=f"{name.upper()}_{self.key}{param_str}")
            return wrapper

        def __dir__(self) -> List[str]:
            return sorted(set(super().__dir__()) | set(dir(self.parent.list_of_grouped[0][self.key])))
        
def _rectify_args_kwargs(*args, **kwargs) -> str:
    def _rectify(s: str):
        return (s if ' ' not in s else '(' + s + ')').upper()
    string = "_".join([_rectify(str(arg)) for arg in args] + [f"{_rectify(str(k))}={_rectify(str(v))}" for k, v in kwargs.items()])
    return '_' + string if string else ''