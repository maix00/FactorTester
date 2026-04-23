# =============================================================================
# tools/data/DataMeta.py
# 数据元信息模块
#
# DataMeta 是围绕特定 Product + DataFreq 的 DataFrame 的薄封装层：
#   - 管理数据加载、时间列处理、列名映射、时间索引构建
#   - 透明转发 pandas 的大多数操作（rolling/pct_change/shift/+/-/... 等）
#   - 计算结果（如 rolling().mean()）仍是 DataMeta，保留原始数据上下文
#   - 支持按 StartCalcPointParam 过滤历史数据
#   - 支持复权计算（OPEN_ADJUSTED / CLOSE_ADJUSTED 等）
# =============================================================================
import pandas as pd
from weakref import WeakValueDictionary
from typing import List, Dict, Optional, Tuple, Any, override

from tools.base.UniqueObject import UniqueObject
from tools.base.SerialObject import SerialObject
from tools.data.DataFreq import DataFreq
from tools.data.DataColumn import DataColumn
from tools.data.DataSource import DataSource

class DataMeta(SerialObject):
    """
    数据元信息对象。

    封装了一个 Product 在特定 DataFreq 下的 DataFrame，并提供：
      - 懒加载（数据首次访问时才从文件读取）
      - 列名映射（原始文件列名 → DataColumn 标准名称）
      - 时间索引构建（将日期/时间列设为 MultiIndex）
      - 透明的 pandas 运算代理（所有在 data 上的操作都转发并返回新的 DataMeta）
      - StartCalcPoint 过滤（只返回计算起始点之后的数据）
      - 复权价格计算

    一般不直接实例化，而是通过 Product.MIN1 / Product.DAY1 访问。
    """
    _instances = WeakValueDictionary()

    def __new__(cls, object: UniqueObject, alias: Optional[str] = None, *args, **kwargs):
        alias = '(' + object.alias + ')' + ('_' + alias if alias else '')
        return super().__new__(cls, type_alias='DM', alias=alias)

    def __init__(self, object: UniqueObject, data_freq: DataFreq, 
                 original_object: Optional[UniqueObject] = None,
                 alias: Optional[str] = None, *args, **kwargs):
        if not hasattr(self, '_initialized'):
            alias = '(' + object.alias + ')' + ('_' + alias if alias else '')
            super().__init__(type_alias='DM', alias=alias)
            self.object = object                           # 关联的 Product 或上游 DataMeta
            self.original_object = object if original_object is None else original_object  # 原始 Product（链式操作时保持）
            self.freq = data_freq                          # 所属数据频率
            self.data: Any = pd.DataFrame() if 'data' not in kwargs else kwargs.pop('data')  # 实际数据（懒加载）
            self.current_source: DataSource
            self.path: Any
            self.timezone = kwargs.get('timezone', None)  # 时区（用于时间列本地化）
            self.day_periods: int                         # 每日 bar 数量缓存，用于窗口换算

    def _get_freq(self, **kwargs) -> DataFreq:
        """获取本对象的数据频率（若已知直接返回，否则从索引列名推断）。"""
        if hasattr(self, 'freq') and self.freq is not None:
            return self.freq
        data = self.get_data(copy=False, data=kwargs.pop('data', None), **kwargs)
        self.freq = DataFreq(data.index.names[-1])
        return self.freq

    def _get_window_k(self, window: Any, **kwargs) -> Any:
        """
        将时间窗口参数（Timedelta 或整数）转换为 bar 数量（整数 periods）。

        规则：
          - 整数：直接使用
          - day-multiple 时间跨度（如 '5d'）：从数据推断每日 bar 数 × 天数
          - 其他 Timedelta：要求整除当前数据频率，返回整数倍数
        结果缓存在 self.day_periods 避免重复计算。
        """
        data_freq = self._get_freq(**kwargs)
        if isinstance(window, int):
            periods = window
        else:
            window_freq = DataFreq(window)
            if window_freq.is_day_multiple():
                import numpy as np
                # 缓存“每个交易日的 bar 数”，但不能缓存“本次窗口对应 periods”。
                # 否则不同窗口（如 21d 和 252d）会被错误地复用为同一个 shift 长度。
                if not hasattr(self, 'day_periods') or self.day_periods is None:
                    self.day_periods = pd.Series(
                        np.diff(np.where((dates := pd.Series(self.data.index.get_level_values(-1).date)) != dates.shift(1)))[0]
                    ).mode()[0]  # type: ignore
                day_periods = int(self.day_periods)
                day_count = int(window_freq.value.total_seconds() / pd.Timedelta('1day').total_seconds())
                periods = day_periods * day_count
            elif window_freq.value.total_seconds() % data_freq.value.total_seconds() == 0:
                periods = int(window_freq.value / data_freq.value)
            else:
                raise ValueError(f"Window frequency {window_freq} is not compatible with data frequency {data_freq}")
        return periods

    def list_available_sources(self) -> List[DataSource]:
        return [s for s in DataSource if s.if_object_is_in_source(self.object) and s.freq == self.freq]
    
    def is_available(self) -> bool:
        return bool(self.list_available_sources())
    
    def set_current_source(self, source: Any) -> DataSource:
        if source in self.list_available_sources():
            self.current_source = source
            return source
        else:
            raise ValueError(f"Data source {source.alias} is not available for object {self.object.name}")
        
    def get_current_source(self) -> DataSource:
        if not hasattr(self, 'current_source'):
            if not (available_sources := self.list_available_sources()):
                raise ValueError(f"No data source available for object {self.object.name}")
            self.current_source = available_sources[0]
        return self.current_source

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
    
    def get_data(self, copy: bool = False, start_calc_point: Optional[Any] = None, **kwargs) -> pd.DataFrame:
        """
        获取 DataFrame，若为空或指定了 source 则先触发加载。
        start_calc_point: 可选 Timestamp（带时区），为 None 时不进行截断。
        copy=True 时返回副本，避免外部修改影响缓存。
        """
        if 'data' in kwargs and kwargs['data'] is not None:
            data = kwargs['data']
        else:
            if self.data.empty or 'source' in kwargs:
                self.load_data(**kwargs)
            data = self.data
        if start_calc_point is not None:
            data = self._filter_data_by_start_calc_point(data, time=start_calc_point)
        else:
            # 备用：兼容旧有 duck-typing 注册机制（不为空则仍尝试过滤）
            data = self._filter_data_by_start_calc_point(data)
        return data.copy() if copy else data
    
    def get_level_index(self, level: Any, **kwargs) -> pd.Index:
        return self._get_level_index(self.get_data(**kwargs), level)

    def _get_level_index(self, index: Any, level: Any) -> pd.Index:
        if not isinstance(index, pd.Index):
            index = index.index
        assert isinstance(index, pd.Index)
        if isinstance(level, list):
            level = [next((lvl for lvl in index.names if str(lvl).split('@')[-1] == DataFreq(lvl_freq).name), None) for lvl_freq in level]
            return pd.MultiIndex.from_arrays([index.get_level_values(lvl) for lvl in level], names=level)
        else:
            level = next((lvl for lvl in index.names if str(lvl).split('@')[-1] == DataFreq(level).name), None)
            return index.get_level_values(level)

    def _process_start_calc_point(self, object: Optional[UniqueObject] = None, **kwargs) -> Tuple[Optional[Any], Optional[bool]]:
        # 优先从 ContextVar 活跃 FactorTester 读取 start_calc_point（并发安全）
        try:
            from tools.factors.FactorFamily import _active_tester
            tester = _active_tester.get()
            if tester is not None and tester.start_calc_point is not None:
                ts = pd.Timestamp(tester.start_calc_point)
                time_is_date = (ts.hour == 0 and ts.minute == 0 and ts.second == 0)
                return ts, time_is_date
        except ImportError:
            pass
        # 兜底：从 kwargs 读取显式传入的 StartCalcPointParam
        from tools.parameters import DateOrTimeParam
        StartCalcPointParam = kwargs.get('StartCalcPointParam', None)
        if StartCalcPointParam is not None:
            assert isinstance(StartCalcPointParam, DateOrTimeParam)
            time = StartCalcPointParam.default_value
            time_is_date = StartCalcPointParam.is_date(value=time)
            return time, time_is_date
        return None, None
    
    def _filter_data_by_start_calc_point(self, data: pd.DataFrame, time_col: Optional[str] = None,
                                        time: Optional[Any] = None, time_is_date: Optional[bool] = None,
                                        copy: bool = False, **kwargs) -> pd.DataFrame:
        """
        按起始时间截断数据。
        time 可是带时区的 Timestamp，与索引比较时自动对齐时区。
        """
        if time is None or time_is_date is None:
            time, time_is_date = self._process_start_calc_point(object=self, **kwargs)
        if time is not None:
            ts = pd.Timestamp(time)
            if time_col is None:
                data_day_col = [str(level) for level in data.index.names if DataFreq(str(level).split('@')[-1]).value >= pd.Timedelta('1day')][-1]
                data_min_col = [str(level) for level in data.index.names if DataFreq(str(level).split('@')[-1]).value >= pd.Timedelta('1min')][-1]
                if time_is_date is None:
                    # 显式传入的 Timestamp，自动判断是否日级
                    time_is_date = (ts.hour == 0 and ts.minute == 0 and ts.second == 0)
                if self.freq.value >= pd.Timedelta('1day') and time_is_date:
                    time_col = data_day_col
                else:
                    time_col = data_day_col if time_is_date else data_min_col
            idx = self._get_level_index(data, time_col)
            assert isinstance(idx, pd.DatetimeIndex), f"Expected DatetimeIndex for column '{time_col}', got {type(idx).__name__}"
            # 对齐时区：如果索引带时区而 ts 不带（或反之），进行转换
            if idx.tz is not None:
                if ts.tzinfo is None:
                    ts = ts.tz_localize(idx.tz)
                else:
                    ts = ts.tz_convert(idx.tz)
            else:
                if ts.tzinfo is not None:
                    ts = ts.tz_convert('UTC').tz_localize(None)
            data = data[idx >= ts]
        return data.copy() if copy else data
    
    def __getattr__(self, name: str) -> Any:
        """
        属性代理：将未显式定义的属性访问转发到内部 data（DataFrame/Series）。

        特殊处理：
          - rolling(window)  : 将 window 参数从 Timedelta 换算为 bar 数量
          - pct_change(n)    : 同上
          - shift(n)         : 同上
          - 其他 DataFrame 方法：直接转发，结果包装为 DataMeta
        这样可以直接写 product.MIN1.rolling('5d').mean() 而无需手动换算。
        """
        if (target := self.__dict__.get(name, None)) is not None:
            return target
        if (data := self.__dict__.get('data', None)) is None:
            raise AttributeError(f"'DataMeta' object has no attribute '{name}'")
        if (method := getattr(data, name, None)) is not None:
            def wrapper(*args, **kwargs):
                def _rectify_window_arg(*args, arg_name: Optional[str] = None, **kwargs):
                    if args:
                        args = (self._get_window_k(args[0], **kwargs),) + args[1:] if args else args
                    else:
                        assert arg_name is not None
                        kwargs = {arg_name: self._get_window_k(w, **kwargs), **kwargs} if (w := kwargs.pop(arg_name, None)) is not None else kwargs
                    return args, kwargs
                if name == 'rolling':
                    args, kwargs = _rectify_window_arg(*args, arg_name='window', **kwargs)
                elif name == 'pct_change':
                    args, kwargs = _rectify_window_arg(*args, arg_name='periods', **kwargs)
                elif name == 'shift':
                    args, kwargs = _rectify_window_arg(*args, **kwargs)
                return self._wrap(method(*args, **kwargs), alias=f"{name.upper()}{_rectify_args_kwargs(*args, **kwargs)}")
            return wrapper
        else:
            raise AttributeError(f"'DataMeta' object has no attribute '{name}'")
    
    def _wrap(self, data: Any, alias: str, target_type: Optional[type] = None, **kwargs) -> DataMeta:
        target_type = target_type if target_type is not None else DataMeta
        res = target_type(data=data, object=self, original_object=self.original_object,
                            alias=alias, data_freq=self.freq, timezone=self.timezone, **kwargs)
        return res

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
    def __getitem__(self, key):
        col = DataColumn(key).name
        if col.endswith('_ADJUSTED') and col not in self.get_data().columns:
            data = self.get_and_adjust_cols(col, copy=False)
            return self._wrap(data[col], alias=col)
        return self._wrap(self.get_data()[col], alias=col)
    def __setitem__(self, key, value): self.get_data()[DataColumn(key).name] = value
    def __delitem__(self, key): del self.get_data()[DataColumn(key).name]

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
            index_names = sorted(ds.time_cols_mapping.values(), key=lambda x: DataFreq(x).value, reverse=True)
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
            if DataFreq(col).is_day_multiple():
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
        
        from tools.products.Futures import Futures

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

def _rectify_args_kwargs(*args, **kwargs) -> str:
    def _rectify(s: str):
        return (s if ' ' not in s else '(' + s + ')').upper()
    string = "_".join([_rectify(str(arg)) for arg in args] + [f"{_rectify(str(k))}={_rectify(str(v))}" for k, v in kwargs.items()])
    return '_' + string if string else ''