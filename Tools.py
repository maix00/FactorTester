from abc import ABC
from weakref import WeakValueDictionary
from typing import TYPE_CHECKING, Callable, List, Dict, Optional, Sequence, Set, Tuple, Any, Literal
import pandas as pd
from pandas.core.groupby import DataFrameGroupBy
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
    WEEK1 = pd.Timedelta('7day')

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
            self.timezone: str = kwargs.get('timezone', '')
            self.set_time_cols_mapping(kwargs.get('time_cols_mapping', {}))
            self.set_data_cols_mapping(kwargs.get('data_cols_mapping', {}))

    def if_object_is_in_source(self, object: UniqueObject) -> bool:
        if hasattr(object, 'timezone') and getattr(object, 'timezone') is not None and getattr(object, 'timezone')\
            and self.timezone and getattr(object, 'timezone') != self.timezone:
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

class DataMeta(UniqueObject):
    _instances = WeakValueDictionary()

    def __init__(self, name: str, object: UniqueObject, data_freq: DataFreq, *args, **kwargs):
        if not hasattr(self, '_initialized'):
            super().__init__(name=name)
            self.object = object
            self.freq = data_freq
            self.data: pd.DataFrame = pd.DataFrame() if 'data' not in kwargs else kwargs.pop('data')
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
    
    def _set_index_timezone(self, index: Any) -> pd.DatetimeIndex:
        if isinstance(index, pd.DatetimeIndex):
            if self.timezone:
                index = index.tz_localize(self.timezone)
            return index
        else:
            raise NotImplementedError("DataMeta: Index type not supported for timezone localization")
    
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
            return self._set_index_timezone(index.get_level_values(level))

    def _process_start_calc_point(self, object: Optional[UniqueObject] = None, **kwargs) -> Tuple[Optional[Any], Optional[bool]]:
        from Parameter import DateOrTimeParam
        if object is not None and callable(get_param := getattr(object, 'get_StartCalcPointParam', None)):
            StartCalcPointParam = get_param()
            assert isinstance(StartCalcPointParam, DateOrTimeParam)
            time = StartCalcPointParam.get_value(object)
            time_is_date = StartCalcPointParam.is_date(object)
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
                                        copy: bool = False, object: Optional[UniqueObject] = None, **kwargs) -> pd.DataFrame:
        if time is None or time_is_date is None:
            time, time_is_date = self._process_start_calc_point(object=object, **kwargs)
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

    def _get_signal_index(self, object: Optional[UniqueObject] = None,
                          freq: Optional[Any] = None,  bfill: Optional[int] = None,
                          end_session_skip: bool = False, end_session_gap: pd.Timedelta = pd.Timedelta('3hour'),
                          index_name_stem: str = '_SIGNAL', copy: bool = False, **kwargs) -> Dict[str, Any]:

        assert freq is not None, "Frequency must be provided"
        freq = _process_data_freq(freq)
        data = self.get_data(copy=copy, data=kwargs.pop('data', None), **kwargs)
        data = self._filter_data_by_start_calc_point(data, object=object, **kwargs)
        index_data_freq = [_process_data_freq(level) for level in data.index.names]
        
        index_map_of_multiple = [freq.value.total_seconds() % idx_freq.value.total_seconds() == 0 for idx_freq in index_data_freq]
        first_true_idx = next((i for i, is_multiple in enumerate(index_map_of_multiple) if is_multiple), None)
        assert first_true_idx is not None, f"Frequency {freq} is not a multiple of any existing index frequency"
        first_true_freq = index_data_freq[first_true_idx]
        multiple = int(freq.value.total_seconds() / first_true_freq.value.total_seconds())
        last_col_multiple = int(freq.value.total_seconds() / index_data_freq[-1].value.total_seconds())
        first_true_series = self._get_level_index(data, data.index.names[first_true_idx]).to_series().reset_index(drop=True)
        first_true_change_map = first_true_series != first_true_series.shift(-1)
        first_true_change_pos = first_true_series.where(first_true_change_map).dropna().index
        
        if end_session_skip and freq.value < pd.Timedelta('1day'):
            last_col_series = self._get_level_index(data, data.index.names[-1]).to_series().reset_index(drop=True)
            end_session_pos = last_col_series[last_col_series.shift(-1) - last_col_series >= end_session_gap].index
            signal_map_within_first_true_change_pos = first_true_change_pos.isin({i for start, end in zip([0] + (end_session_pos[:-1].values + 1).tolist(), end_session_pos) for i in range(start + multiple - 1, end + 1, multiple) if start + multiple - 1 <= end})
        else:
            signal_map_within_first_true_change_pos = first_true_change_pos % multiple == multiple - 1

        signal_pos_within_first_true_series = first_true_change_pos[signal_map_within_first_true_change_pos]
        signal_map_within_first_true_series = first_true_series.index.isin(signal_pos_within_first_true_series)
        signal_series_within_first_true_series = first_true_series.where(signal_map_within_first_true_series)

        def _get_values(obj, bfill: Optional[int] = None) -> pd.Series:
            if bfill is not None:
                obj = obj.bfill(limit=bfill)
            return obj.dt.tz_localize(None).values if hasattr(obj, 'dt') else obj.values
        
        def _get_extended_index(bfill: Optional[int] = None) -> Tuple[pd.MultiIndex, List[str], List[str]]:
            left_indices = data.index.names[:first_true_idx]
            right_indices = data.index.names[first_true_idx:]
            left_series_dict = {idx: self._get_level_index(data, idx).to_series().reset_index(drop=True).where(signal_map_within_first_true_series) for idx in left_indices}
            right_series_dict = {idx: self._get_level_index(data, idx).to_series().reset_index(drop=True) for idx in right_indices}
            index_arrays = [_get_values(left_series_dict[idx], bfill=bfill) for idx in left_indices] \
                            + [_get_values(signal_series_within_first_true_series, bfill=bfill)] \
                            + [_get_values(right_series_dict[idx]) for idx in right_indices]
            index_name = index_name_stem + '@' + freq.name
            left_indices = [str(idx).split('@')[-1] for idx in left_indices]
            right_indices = [str(idx).split('@')[-1] for idx in right_indices]
            index_names_for_groupby = left_indices + [index_name]
            index_names = index_names_for_groupby + right_indices[1:]
            extended_index = pd.MultiIndex.from_arrays(index_arrays, names=index_names_for_groupby + right_indices)
            return extended_index, index_names_for_groupby, index_names
        
        signal_index, _, index_names = _get_extended_index()
        signal_index = self._get_level_index(signal_index.dropna(), index_names)
        bfill = bfill if bfill is not None else last_col_multiple - 1
        extended_index, index_names_for_groupby, index_names = _get_extended_index(bfill=bfill)

        mask = ~extended_index.to_frame().isna().any(axis=1)
        extended_index = extended_index[mask]
        data = data[mask.values]

        return {
            'data': data,
            'signal_index': signal_index,
            'extended_index': extended_index,
            'index_names_for_groupby': index_names_for_groupby,
            'index_names': index_names
        }
    
    def groupby(self, object: Optional[UniqueObject] = None,
                 freq: Optional[Any] = None,
                 bfill: Optional[int] = None,
                 stem: str = '_SIGNAL',
                 copy: bool = True, **kwargs) -> GroupedOperator:
        results = self._get_signal_index(object=object, freq=freq, bfill=bfill, index_name_stem=stem, copy=copy, **kwargs)
        data = results['data']
        data.index = results['extended_index']
        return GroupedOperator(data, results['index_names_for_groupby'], results['index_names'])
    
    def sync_signal(self, object: UniqueObject, signal: Any, freq: Optional[Any] = None,
                    end_session_skip: bool = True, end_session_gap: pd.Timedelta = pd.Timedelta('3hour'), **kwargs) -> pd.DataFrame:
        if isinstance(signal, pd.DataFrame):
            assert len(signal.columns) == 1, "Signal must have only one column"
            signal = signal.squeeze()
        index = self._get_signal_index(object=object, freq=freq, end_session_skip=end_session_skip, end_session_gap=end_session_gap, copy=True, **kwargs)['signal_index']
        assert index.nlevels == signal.index.nlevels, "Index levels do not match between signal index and signal index"
        map = signal.index.isin(index)
        signal = signal[map]
        signal.index = index
        signal.rename(self.name, inplace=True)
        return signal
    
    def rolling(self, object: UniqueObject, window: int|str|pd.Timedelta, copy: bool = False, **kwargs) -> RollingOperator|GroupedOperator:
        data = self.get_data(copy=copy, data=kwargs.pop('data', None), **kwargs)
        data = self._filter_data_by_start_calc_point(data, object=object, **kwargs)
        data_freq = _process_data_freq(data.index.names[-1])
        if isinstance(window, int):
            return RollingOperator(data, window=window, min_periods=window, **kwargs)
        else:
            window_freq = _process_data_freq(window)
            if window_freq.value >= pd.Timedelta('1day') and data_freq.value < pd.Timedelta('1day')\
                and window_freq.value.total_seconds() % pd.Timedelta('1day').total_seconds() == 0:
                return self.groupby(object=object, freq=window_freq, copy=copy, data=data, **kwargs)
            elif window_freq.value.total_seconds() % data_freq.value.total_seconds() == 0:
                window_size = int(window_freq.value.total_seconds() / data_freq.value.total_seconds())
                return RollingOperator(data, window=window_size, min_periods=window_size, **kwargs)
            else:
                raise ValueError(f"Window frequency {window_freq} is not compatible with data frequency {data_freq}")

    def pct_change(self, object: UniqueObject, window: int|str|pd.Timedelta = 1, col: Optional[Any] = None, copy: bool = False, **kwargs) -> pd.Series:
        data = self.get_data(copy=copy, data=kwargs.pop('data', None), **kwargs)
        data = self._filter_data_by_start_calc_point(data, object=object, **kwargs)
        data_freq = _process_data_freq(data.index.names[-1])
        if col is not None:
            if col not in data.columns:
                raise ValueError(f"Column {col} not found in data")
            col = _process_data_col(col).name
            data = data[col]
        else:
            if isinstance(data, pd.Series):
                pass
            else:
                col = data.columns[0]
                data = data[col]
        if isinstance(window, int):
            return data.pct_change(periods=window)
        else:
            window_freq = _process_data_freq(window)
            if window_freq.value >= pd.Timedelta('1day') and data_freq.value < pd.Timedelta('1day')\
                and window_freq.value.total_seconds() % pd.Timedelta('1day').total_seconds() == 0:
                groupby_freq = window_freq
                grouped = self.groupby(object=object, freq=groupby_freq, copy=copy, **kwargs)
                return grouped.last().pct_change()
            elif window_freq.value.total_seconds() % data_freq.value.total_seconds() == 0:
                window_size = int(window_freq.value.total_seconds() / data_freq.value.total_seconds())
                return data.pct_change(periods=window_size)
            else:
                raise ValueError(f"Window frequency {window_freq} is not compatible with data frequency {data_freq}")

    def __getitem__(self, key):
        col = _process_data_col(key).name
        data = self.get_data(copy=True)
        if col not in data.columns:
            raise ValueError(f"Column {col} not found in data")
        return DataMeta(name=f"{self.name}_{col}", object=self, data=data[col], data_freq=self.freq, timezone=self.timezone)

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

class RollingOperator:
    def __init__(self, data: pd.DataFrame, window: int|str|pd.Timedelta, min_periods: Optional[int] = None, **kwargs):
        self.data = data
        self.window = window
        self.min_periods = min_periods
        self.rolling = data.rolling(window=window, min_periods=min_periods, **kwargs)

    def __getattr__(self, name: str) -> Any:
        # 从 rolling 对象获取同名方法
        try:
            method = getattr(self.rolling, name)
        except AttributeError:
            raise AttributeError(f"RollingOperator has no attribute '{name}'")
        # 包装方法，自动恢复索引
        def wrapper(*args, **kwargs):
            result = method(*args, **kwargs)
            result.index = self.data.index
            return result
        return wrapper

    def __dir__(self) -> List[str]:
        return sorted(set(super().__dir__()) | set(dir(self.rolling)))
    
    def __getitem__(self, key):
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
                return result
            return wrapper

        def __dir__(self) -> List[str]:
            # 提供该列选择器可用的方法
            return sorted(set(super().__dir__()) | set(dir(self.parent.rolling[self.key])))
    
class GroupedOperator:
    def __init__(self, data: pd.DataFrame, groupby_index_names: List[str], original_index_names: Optional[List[str]] = None, **kwargs):
        self.data = data
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
        # 从 grouped 对象获取同名方法
        try:
            method = getattr(self.grouped, name)
        except AttributeError:
            raise AttributeError(f"GroupedOperator has no attribute '{name}'")
        # 包装方法，自动恢复索引，支持可选的 col 参数
        def wrapper(*args, **kwargs):
            col = kwargs.pop('col', None)
            if col is not None:
                target = getattr(self.grouped[col], name)
                result = target(*args, **kwargs)
            else:
                result = method(*args, **kwargs)
            return self._restore_index(result)
        return wrapper

    def __dir__(self) -> List[str]:
        return sorted(set(super().__dir__()) | set(dir(self.grouped)))

    def __getitem__(self, key):
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
                return self.parent._restore_index(result)
            return wrapper

        def __dir__(self) -> List[str]:
            # 提供该列选择器可用的方法
            return sorted(set(super().__dir__()) | set(dir(self.parent.grouped[self.key])))