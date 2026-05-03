# =============================================================================
# tools/data/DataMeta.py
# 数据元信息模块
#
# DataMeta 是围绕特定 Product + DataFreq 的 DataFrame 的薄封装层：
#   - 管理数据加载、时间列处理、列名映射、时间索引构建
#   - 支持按 StartCalcPointParam 过滤历史数据
#   - 支持复权计算（OPEN_ADJUSTED / CLOSE_ADJUSTED 等）
#
# DataFrame 缓存统一委托给 IdleResourceManager（基于访问时间的自动回收）。
# 不保留 self.data 属性，避免双重缓存。
# =============================================================================
from __future__ import annotations

from typing import List, Dict, Optional, Tuple, Any

import pandas as pd

from tools.base.UniqueObject import UniqueObject
from tools.base.IdleResourceManager import IdleResourceManager
from tools.data.DataFreq import DataFreq
from tools.data.DataColumn import DataColumn
from tools.data.DataSource import DataSource

# IdleResourceManager 中 DataMeta 使用的 namespace 常量
_DATAMETA_NAMESPACE = "datameta"
# 默认空闲 TTL（秒）：5 分钟无访问后自动回收
_DEFAULT_IDLE_TTL = 300

class DataMeta(UniqueObject):
    """
    数据元信息对象。

    封装了一个 Product 在特定 DataFreq 下的 DataFrame，并提供：
      - 懒加载 + IdleResourceManager 缓存（自动回收闲置数据）
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
            self.current_source: DataSource
            self.path: Any = None
            self.timezone = kwargs.get('timezone', None)  # 时区（用于时间列本地化）

    # ── DataSource 管理 ──

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

    # ── 资源 ID ──

    def _resource_id(self) -> str:
        """生成 IdleResourceManager 的 resource_id: '{source_alias}:{product_name}:{freq_name}'。"""
        source = self.get_current_source()
        return f"{source.alias}:{self.object.name}:{self.freq.name}"

    # ── 数据加载（委托给 IdleResourceManager） ──

    def _load_raw_file(self, source: DataSource) -> pd.DataFrame:
        """从磁盘读取原始文件（不解映射、不建索引）。"""
        self.path = source.get_path(self.object)
        if self.path.endswith('.csv'):
            return pd.read_csv(self.path)
        elif self.path.endswith('.xlsx'):
            return pd.read_excel(self.path)
        elif self.path.endswith('.parquet'):
            return pd.read_parquet(self.path)
        else:
            raise ValueError("Unsupported file type")

    def _load_and_process(self, source: Optional[DataSource] = None,
                          data_cols_mapping: Optional[Dict[Any, Any]] = None,
                          time_cols_mapping: Optional[Dict[Any, Any]] = None,
                          time_index: Optional[Any] = None,
                          filter_object: bool = False,
                          filter_object_attr: str = 'name') -> pd.DataFrame:
        """
        完整的「加载 + 后处理」流程。
        不修改 self，返回处理好的 DataFrame（由 IdleResourceManager 缓存）。
        """
        src = self.set_current_source(source) if source is not None else self.get_current_source()
        df = self._load_raw_file(src)
        if df.empty:
            return df

        # 时间列映射
        ds = self.get_current_source()
        if time_cols_mapping is not None:
            ds.set_time_cols_mapping(time_cols_mapping)
        df = df.reset_index(drop=True)
        df = df.rename(columns=ds.time_cols_mapping)

        # 数据列映射
        if data_cols_mapping is not None:
            ds.set_data_cols_mapping(data_cols_mapping)
        df = df.rename(columns=ds.data_cols_mapping)

        # 过滤 object
        if filter_object:
            filter_object_name = getattr(self.object, filter_object_attr)
            df = df[df[DataColumn.PRODUCT_NAME] == filter_object_name]

        # 构建时间索引
        if time_index is None:
            time_index = sorted(ds.time_cols_mapping.values(), key=lambda x: DataFreq(x).value, reverse=True)
        for col in time_index:
            if col not in df.columns:
                raise ValueError(f"Column {col} not found in data")
            df[col] = pd.to_datetime(df[col])
        df = df.set_index(time_index)

        # 时区处理
        index = df.index
        index_tzaware_list = []
        for col in index.names:
            col = str(col)
            level_index = index.get_level_values(col)
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
        df.index = pd.MultiIndex.from_arrays(index_tzaware_list, names=index.names)

        return df

    # ── 对外 API ──

    def load_data(self, source: Optional[Any] = None,
                  loaded_data: Optional[pd.DataFrame] = None,
                  data_cols_mapping: Optional[Dict[Any, Any]] = None,
                  time_cols_mapping: Optional[Dict[Any, Any]] = None,
                  time_index: Optional[Any] = None,
                  filter_object: bool = False,
                  filter_object_attr: str = 'name',
                  force_reload: bool = False, **kwargs) -> pd.DataFrame:
        """
        加载数据（委托给 IdleResourceManager 缓存）。

        若 loaded_data 不为 None，直接使用传入数据并处理后返回（不走缓存）。
        force_reload=True 时跳过缓存，重新从文件加载。
        """
        if loaded_data is not None:
            # 直接使用传入数据，不走缓存
            df = loaded_data
            if not df.empty:
                ds = self.get_current_source()
                if time_cols_mapping is not None:
                    ds.set_time_cols_mapping(time_cols_mapping)
                if data_cols_mapping is not None:
                    ds.set_data_cols_mapping(data_cols_mapping)
                if filter_object:
                    filter_object_name = getattr(self.object, filter_object_attr)
                    df = df[df[DataColumn.PRODUCT_NAME] == filter_object_name]
                if time_index is None:
                    time_index = sorted(ds.time_cols_mapping.values(), key=lambda x: DataFreq(x).value, reverse=True)
                for col in time_index:
                    if col not in df.columns:
                        raise ValueError(f"Column {col} not found in data")
            return df

        # 通过 IdleResourceManager 缓存
        manager = IdleResourceManager.get_instance()
        resource_id = self._resource_id()

        if force_reload:
            # 强制重载：先清理缓存
            manager._cache.pop((_DATAMETA_NAMESPACE, resource_id), None)
            manager.registry.remove(f"{_DATAMETA_NAMESPACE}:{resource_id}")

        df = manager.load(
            namespace=_DATAMETA_NAMESPACE,
            path=resource_id,
            reader=lambda _: self._load_and_process(
                source=source,
                data_cols_mapping=data_cols_mapping,
                time_cols_mapping=time_cols_mapping,
                time_index=time_index,
                filter_object=filter_object,
                filter_object_attr=filter_object_attr,
            ),
            ttl=_DEFAULT_IDLE_TTL,
        )
        return df
    
    def get_data(self, copy: bool = False, start_calc_point: Optional[Any] = None, **kwargs) -> pd.DataFrame:
        """
        获取 DataFrame（通过 IdleResourceManager 缓存 + 自动回收）。
        start_calc_point: 可选 Timestamp（带时区），为 None 时不进行截断。
        copy=True 时返回副本，避免外部修改影响缓存。
        """
        if 'data' in kwargs and kwargs['data'] is not None:
            data = kwargs['data']
        else:
            data = self.load_data(**kwargs)

        if start_calc_point is not None:
            data = self._filter_data_by_start_calc_point(data, time=start_calc_point)
        else:
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
            from tools.factors.FactorTester import _active_tester
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
            time_is_date = StartCalcPointParam.is_date(object=StartCalcPointParam, value=time)
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
