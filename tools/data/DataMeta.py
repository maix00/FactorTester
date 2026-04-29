# =============================================================================
# tools/data/DataMeta.py
# 数据元信息模块
#
# DataMeta 是围绕特定 Product + DataFreq 的 DataFrame 的薄封装层：
#   - 管理数据加载、时间列处理、列名映射、时间索引构建
#   - 支持按 StartCalcPointParam 过滤历史数据
#   - 支持复权计算（OPEN_ADJUSTED / CLOSE_ADJUSTED 等）
# =============================================================================
import pandas as pd
from typing import List, Dict, Optional, Tuple, Any

from tools.base.UniqueObject import UniqueObject
from tools.data.DataFreq import DataFreq
from tools.data.DataColumn import DataColumn
from tools.data.DataSource import DataSource

class DataMeta(UniqueObject):
    """
    数据元信息对象。

    封装了一个 Product 在特定 DataFreq 下的 DataFrame，并提供：
      - 懒加载（数据首次访问时才从文件读取）
      - 列名映射（原始文件列名 → DataColumn 标准名称）
      - 时间索引构建（将日期/时间列设为 MultiIndex）
      - StartCalcPoint 过滤（只返回计算起始点之后的数据）
      - 复权价格计算

    一般不直接实例化，而是通过 Product.MIN1 / Product.DAY1 访问。
    """

    def __new__(cls, object: UniqueObject, alias: Optional[str] = None, *args, **kwargs):
        alias = alias if alias else ('(' + object.alias + ')' + ('_' + alias if alias else ''))
        return super().__new__(cls, alias=alias, **kwargs)

    def __init__(self, object: UniqueObject, data_freq: DataFreq, 
                 alias: Optional[str] = None, *args, **kwargs):
        if not hasattr(self, '_initialized'):
            alias = alias if alias else ('(' + object.alias + ')' + ('_' + alias if alias else ''))
            super().__init__(alias=alias)
            self.object = object                           # 关联的 Product
            self.freq = data_freq                          # 所属数据频率
            self.data: Any = pd.DataFrame() if 'data' not in kwargs else kwargs.pop('data')  # 实际数据（懒加载）
            self.current_source: DataSource
            self.path: Any
            self.timezone = kwargs.get('timezone', None)  # 时区（用于时间列本地化）

    # ── 兼容旧因子路径（已废弃，保留空壳避免报错） ──
    @classmethod
    def begin_cleanup_scope(cls) -> None:
        """[已废弃] 旧因子链式操作的内存清理入口。新表达式路径不再需要。"""
        pass

    @classmethod
    def end_cleanup_scope(cls) -> None:
        """[已废弃] 旧因子链式操作的内存清理出口。新表达式路径不再需要。"""
        pass

    def list_available_sources(self) -> List[DataSource]:
        return [s for s in DataSource if self.object in s and s.freq == self.freq]
    
    def next_available_source(self) -> Optional[DataSource]:
        return next((s for s in DataSource if self.object in s and s.freq == self.freq), None)

    def is_available(self) -> bool:
        return bool(self.next_available_source())
    
    def set_current_source(self, source: Any) -> DataSource:
        if self.object in source and source.freq == self.freq:
            self.current_source = source
            return source
        else:
            raise ValueError(f"Data source {source.alias} is not available for object {self.object.name}")
        
    def get_current_source(self) -> DataSource:
        if not hasattr(self, 'current_source'):
            if not (source := self.next_available_source()):
                 raise ValueError(f"No data source available for object {self.object.name}")
            self.current_source = source
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
        if self.data.empty:
            return self.data
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
        if data.empty:
            return data
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
        if not isinstance(cols, list):
            cols = [cols]
        cols = list(set(cols))

        from tools.products.Futures import Futures

        df = self.get_data(copy=copy)
        if df.empty:
            return df
        if not isinstance(self.object, Futures):
            # 非期货产品不做复权：将 *_ADJUSTED 回退到原始列返回。
            fallback_cols = [self._get_nonadjusted_col_name(col) if self._check_is_adjusted(col) else col for col in cols]
            existing_cols = [col for col in fallback_cols if col in df.columns]
            return df[existing_cols] if existing_cols else df

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