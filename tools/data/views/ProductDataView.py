"""
ProductDataView — 围绕 Product + DataFreq 的 DataFrame 视图层。

核心职责：
  - 懒加载 DataFrame（委托 DataHub → IdleResourceManager 按 (namespace, key) 缓存）
  - 列名映射（原始 Parquet 列名 → DataColumn 标准枚举）
  - 时间索引构建（将日期列 + 时间列组合为 MultiIndex）
  - 复权价格计算（OPEN_ADJUSTED / CLOSE_ADJUSTED 等）
  - 按 DataSource 过滤可用频率

使用方式：
  product.DAY1.load_data()                   # 自动缓存，5 分钟无访问后释放
  product.DAY1.get_data(start=..., end=...)  # 时间范围切片

缓存策略：
  - DataHub 统一管理，namespace='datameta'
  - 同一 parquet 文件被多个品种共享时只加载一次
  - 默认 300 秒 TTL，每次访问自动刷新时间戳

注意：本对象不保留 self.data 属性，所有数据通过 DataHub 存取。
"""
from __future__ import annotations

from typing import List, Dict, Optional, Tuple, Any, cast

import numpy as np
import pandas as pd

from tools.base.UniqueNameObject import UniqueNameObject
from ..hub import DataHub
from ..types.DataIndex import DataIndex, finest_index
from ..types.DataFreq import DataFreq
from ..types.DataColumn import DataColumn
from ..providers.DataProviderProductTS import DataProviderProductTS as DataSource

# DataHub 中产品数据视图使用的 namespace 常量
_DATAMETA_NAMESPACE = "datameta"
# 默认空闲 TTL（秒）：5 分钟无访问后自动回收
_DEFAULT_IDLE_TTL = 300

class ProductDataView(UniqueNameObject):
    """
    产品数据视图。

    封装了一个 Product 在特定 DataFreq 下的 DataFrame 视图，并提供：
      - 懒加载 + IdleResourceManager 缓存（自动回收闲置数据）
      - 列名映射（原始文件列名 → DataColumn 标准名称）
      - 时间索引构建（将日期/时间列设为 MultiIndex）
      - StartCalcPoint 过滤（只返回计算起始点之后的数据）
      - 复权价格计算

    一般不直接实例化，而是通过 Product.MIN1 / Product.DAY1 访问。
    """

    def __new__(cls, object: Any, alias: Optional[str] = None, *args, **kwargs):
        alias = alias if alias else ('(' + object.alias + ')' + ('_' + alias if alias else ''))
        return super().__new__(cls, alias=alias, **kwargs)

    def __init__(self, object: Any, data_freq: DataFreq, 
                 alias: Optional[str] = None, *args, **kwargs):
        if not hasattr(self, '_initialized'):
            alias = alias if alias else ('(' + object.alias + ')' + ('_' + alias if alias else ''))
            super().__init__(alias=alias)
            self.object = object                           # 关联的 Product
            self.freq = data_freq                          # 所属数据频率
            self.current_source: DataSource
            self.path: Any = None
            self.timezone = kwargs.get('timezone', None)  # 时区（用于时间列本地化）
            self._day_periods: Optional[int] = None       # 缓存：每日 bar 数

    # ── 兼容入口：旧代码仍可通过这里拿到当前选择的源 ──

    def list_available_sources(self) -> List[DataSource]:
        return DataSource.available_for_product(self.object, self.freq)
    
    def next_available_source(self) -> Optional[DataSource]:
        return DataSource.select_for_product(self.object, self.freq)

    def is_available(self) -> bool:
        return bool(self.next_available_source())
    
    def set_current_source(self, source: Any) -> DataSource:
        if self.object in source and source.freq == self.freq:
            self.current_source = source
            return source
        else:
            raise ValueError(f"Data source {source.key} is not available for object {self.object.name}")
        
    def get_current_source(self) -> DataSource:
        if not hasattr(self, 'current_source'):
            if not (source := self.next_available_source()):
                 raise ValueError(f"No data source available for object {self.object.name}")
            self.current_source = source
        return self.current_source

    # ── day_periods 缓存 ──

    @property
    def day_periods(self) -> int:
        """该产品+频率下每日的 bar 数量（懒计算，一次求值后缓存）。"""
        if self._day_periods is not None:
            return self._day_periods
        df = self.get_data()
        idx_level = finest_index(df.index)
        dates = pd.Series(getattr(pd.DatetimeIndex(idx_level), 'date'))
        day_boundaries = np.diff(np.where(dates != dates.shift(1))[0])
        if len(day_boundaries) == 0:
            self._day_periods = int(len(df))
        else:
            self._day_periods = int(pd.Series(day_boundaries).mode().iloc[0])
        return self._day_periods

    # ── 资源 ID ──

    def _resource_id(self) -> str:
        """生成 DataHub 的 resource key: '{source_alias}:{product_name}:{freq_name}'。"""
        source = self.get_current_source()
        return f"{source.key}:{self.object.name}:{self.freq.name}"

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
        df = df.set_index(time_index).sort_index()

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
            return cast(pd.DataFrame, df)

        # 通过 DataHub 缓存（传自定义 reader 保留实例上下文）
        hub = DataHub.get_instance()
        resource_key = self._resource_id()

        return hub.load(
            namespace=_DATAMETA_NAMESPACE,
            key=resource_key,
            ttl=_DEFAULT_IDLE_TTL,
            force_reload=force_reload,
            reader=lambda _: self._load_and_process(
                source=source,
                data_cols_mapping=data_cols_mapping,
                time_cols_mapping=time_cols_mapping,
                time_index=time_index,
                filter_object=filter_object,
                filter_object_attr=filter_object_attr,
            ),
        )
    
    def get_data(self, copy: bool = False, start_calc_point: Optional[Any] = None, **kwargs) -> pd.DataFrame:
        """
        获取 DataFrame（通过 DataHub 缓存 + 自动回收）。
        start_calc_point: DataTime | None，为 None 时不截断。
        copy=True 时返回副本，避免外部修改影响缓存。

        Issue #3: start_calc_point 必须显式传入，不再隐式从 _active_tester 读取。
        """
        if 'data' in kwargs and kwargs['data'] is not None:
            data = kwargs['data']
        else:
            data = self.load_data(**kwargs)

        if start_calc_point is not None:
            data = self._filter_data_by_start_calc_point(data, time=start_calc_point)
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

    def _filter_data_by_start_calc_point(self, data: pd.DataFrame, time_col: Optional[str] = None,
                                        time: Optional[Any] = None, time_is_date: Optional[bool] = None,
                                        copy: bool = False) -> pd.DataFrame:
        """
        按起始时间截断数据。time 必须是 DataTime（或 None）。
        通过 DataIndex.slice_by_datatime() 统一处理时区对齐和截断。

        Issue #3: time 参数必须显式传入，不再通过 _active_tester 隐式获取。
        """
        if data.empty:
            return data
        if time is None:
            return data.copy() if copy else data

        from ..types.DataTime import DataTime

        if not isinstance(time, DataTime):
            raise TypeError(f"_filter_data_by_start_calc_point: time must be DataTime, got {type(time)}")
        if not time.is_set:
            return data.copy() if copy else data

        di = DataIndex(data.index)
        # 只有起始点无结束点：用 slice_by(start_ts, None)
        mask = di.slice_by(time.ts, None)
        data = cast(pd.DataFrame, data[mask])
        return cast(pd.DataFrame, data.copy()) if copy else data
    
    @staticmethod
    def _get_adjusted_col_name(col: str) -> str:
        return f"{col}_ADJUSTED"
    
    @staticmethod
    def _get_nonadjusted_col_name(col: str) -> str:
        return col.replace("_ADJUSTED", "")
    
    @staticmethod
    def _check_is_adjusted(col: str) -> bool:
        return col.endswith("_ADJUSTED")

    def get_and_adjust_cols(self, cols: List[str]|str, copy: bool = True, start_calc_point: Optional[Any] = None) -> pd.DataFrame:
        if not isinstance(cols, list):
            cols = [cols]
        cols = list(set(cols))

        from tools.products.Futures import Futures

        df = self.get_data(copy=copy, start_calc_point=start_calc_point)
        if df.empty:
            return df
        if not isinstance(self.object, Futures):
            result = pd.DataFrame(index=df.index)
            for col in cols:
                if col in df.columns:
                    result[col] = df[col]
                    continue
                if self._check_is_adjusted(col):
                    raw_col = self._get_nonadjusted_col_name(col)
                    if raw_col in df.columns:
                        # 非复权产品没有 adjusted 列时，按请求列名返回原始列值。
                        result[col] = df[raw_col]
            return result if len(result.columns) > 0 else df.iloc[:, 0:0]

        adjust_cols = [col if self._check_is_adjusted(col) else self._get_adjusted_col_name(col) for col in cols]
        adjust_cols = [col for col in adjust_cols if col not in df.columns]
        if len(adjust_cols) > 0:
            has_adjustment = (
                DataColumn.ADJUSTMENT_MUL.name in df.columns
                and DataColumn.ADJUSTMENT_ADD.name in df.columns
            )
            raw_cols = [self._get_nonadjusted_col_name(col) for col in adjust_cols]
            for col, col_adj in zip(raw_cols, adjust_cols):
                if col not in df.columns:
                    continue
                if has_adjustment:
                    df[col_adj] = df[col] * df[DataColumn.ADJUSTMENT_MUL.name] \
                        + df[DataColumn.ADJUSTMENT_ADD.name]
                else:
                    # Futures 类但当前数据源没有复权参数时，同样按 adjusted 名称回退原始列。
                    df[col_adj] = df[col]
        return df
