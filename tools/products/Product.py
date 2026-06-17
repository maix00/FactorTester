"""
Product 抽象基类 — 所有金融产品的统一接口。

核心职责：
  - 为每个 DataFreq 自动创建 ProductDataView 对象（如 product.MIN1 / product.DAY1）
  - 封装数据可用性判断（list_available_freqs / list_available_datasources）
  - 在后台与 IdleResourceManager 协作，按需加载和回收 DataFrame

子类：Futures (tools/products/Futures.py) → CNFutures (sources/LocalCNFutures/)
"""
from typing import List, Optional, Any, TYPE_CHECKING, cast
import pandas as pd

from tools.data.types import UniqueNameObject
from tools.data.views.ProductDataView import ProductDataView
from tools.data.types import DataColumn
from tools.data.types import DataFreq
from tools.data.providers import DataProviderProductTS as DataSource

class Product(UniqueNameObject):
    """
    金融产品基类。

    初始化时会为每个已知 DataFreq（全局实例）自动创建对应的 ProductDataView，
    并设置为同名属性（如 product.MIN1、product.DAY1）。

    属性：
        name        (str)       : 唯一识别名，如 'IF.CFE'
        point_value (int|None)  : 每手合约价值点乘数
        currency    (str|None)  : 计价货币
        timezone    (str|None)  : 对应时区，与 DataSource 匹配用于判断可用性
        is_margin_traded (bool) : 是否使用保证金交易
    """
    # 全局类属性标注（实际属性由具体子类提供）
    desc: str
    MIN1: ProductDataView   # 1 分钟数据
    DAY1: ProductDataView   # 1 日数据

    # 技术基类可覆写为 True，以在前端产品树中隐藏该层级。
    _is_hidden_product_tree_class: bool = False
    TRADING_SPEC_FIELDS: tuple[str, ...] = (
        "multiplier",
        "min_tick",
        "min_trade_quantity",
        "max_trade_quantity",
        "long_margin_ratio",
        "long_margin_fixed",
        "short_margin_ratio",
        "short_margin_fixed",
        "open_ratio",
        "open_fixed",
        "close_ratio",
        "close_fixed",
        "closetoday_ratio",
        "closetoday_fixed",
    )

    def __init__(self, name: str,
                 point_value: Optional[int] = None,
                 currency: Optional[str] = None,
                 is_margin_traded: bool = False,
                 *args, **kwargs):
        if not hasattr(self, '_initialized'):
            super().__init__(name=name, *args, **kwargs)
            self.point_value = point_value
            self.currency = currency
            self.is_margin_traded = bool(is_margin_traded)
            self.timezone = kwargs.get('timezone', None)
            for field in self.TRADING_SPEC_FIELDS:
                if field in kwargs and kwargs[field] is not None:
                    setattr(self, field, kwargs[field])
            # 为每个已知频率创建 ProductDataView 对象，设为对应属性
            for freq in DataFreq:
                setattr(self, freq.name, ProductDataView(alias=f"{freq}", object=self, data_freq=freq, timezone=self.timezone))
            if TYPE_CHECKING:
                from tools.parameters import DataTimeParam

    def list_available_freqs(self) -> List[DataFreq]:
        """列出本产品在所有已注册 DataSource 中可用的数据频率。"""
        return [source.freq for source in DataSource if self in source]
    
    def set_current_freq(self, freq: Any) -> DataFreq:
        """设置本产品当前默认数据频率，必须是可用频率。"""
        if freq in self.list_available_freqs():
            self.current_freq = freq
            return freq
        else:
            raise ValueError(f"Data frequency {freq} is not available for product {self.name}")
        
    def get_current_freq(self) -> DataFreq:
        """获取当前默认频率，未设置时自动选择第一个可用频率。"""
        if not hasattr(self, 'current_freq'):
            available_freqs = self.list_available_freqs()
            if len(available_freqs) == 0:
                raise ValueError(f"No data frequency available for product {self.name}")
            self.current_freq = available_freqs[0]
        return getattr(self, 'current_freq')

    def supports_adjusted_price(self) -> bool:
        """Whether this product class supports adjusted OHLC prices."""
        return False

    def supports_term_structure(self) -> bool:
        """Whether this product class supports term-structure contract chains."""
        return False

    def is_term_contract(self) -> bool:
        """Whether this product is an individual contract in a term structure."""
        return False

    def get_trading_spec_field(self, field: str, default: Any = None) -> Any:
        """Return one product trading-spec field with local-first fallback."""
        try:
            from sources.OpenCTP.fields import get_product_field
            value = get_product_field(self, field)
        except Exception:
            return default
        return default if value in (None, "") else value

    def get_trading_spec_fields(self, fields: Optional[List[str]] = None) -> dict[str, Any]:
        """Return selected product trading-spec fields, resolved independently."""
        if fields is None:
            fields = list(self.TRADING_SPEC_FIELDS)
        from sources.OpenCTP.fields import get_product_fields
        return get_product_fields(self, fields)

    def get_multiplier(self, default: Any = None) -> Any:
        return self.get_trading_spec_field("multiplier", default)

    def get_min_tick(self, default: Any = None) -> Any:
        return self.get_trading_spec_field("min_tick", default)

    def get_min_trade_quantity(self, default: Any = None) -> Any:
        return self.get_trading_spec_field("min_trade_quantity", default)

    def get_max_trade_quantity(self, default: Any = None) -> Any:
        return self.get_trading_spec_field("max_trade_quantity", default)

    def get_long_margin_ratio(self, default: Any = None) -> Any:
        return self.get_trading_spec_field("long_margin_ratio", default)

    def get_long_margin_fixed(self, default: Any = None) -> Any:
        return self.get_trading_spec_field("long_margin_fixed", default)

    def get_short_margin_ratio(self, default: Any = None) -> Any:
        return self.get_trading_spec_field("short_margin_ratio", default)

    def get_short_margin_fixed(self, default: Any = None) -> Any:
        return self.get_trading_spec_field("short_margin_fixed", default)

    def get_open_ratio(self, default: Any = None) -> Any:
        return self.get_trading_spec_field("open_ratio", default)

    def get_open_fixed(self, default: Any = None) -> Any:
        return self.get_trading_spec_field("open_fixed", default)

    def get_close_ratio(self, default: Any = None) -> Any:
        return self.get_trading_spec_field("close_ratio", default)

    def get_close_fixed(self, default: Any = None) -> Any:
        return self.get_trading_spec_field("close_fixed", default)

    def get_closetoday_ratio(self, default: Any = None) -> Any:
        return self.get_trading_spec_field("closetoday_ratio", default)

    def get_closetoday_fixed(self, default: Any = None) -> Any:
        return self.get_trading_spec_field("closetoday_fixed", default)
    
    def get_some_data(self, data_freq: Optional[Any] = None, copy: bool = False) -> pd.DataFrame:
        """
        获取一种频率下的数据。如果所请频率不可用则回退空 DataFrame。
        data_freq=None 时使用当前默认频率。
        """
        try:
            data_freq = self.get_current_freq() if data_freq is None else DataFreq(data_freq)
            return getattr(self, data_freq.name).get_data(copy=copy)
        except:
            return pd.DataFrame()
        
    def get_price_data(self, start_date: Any, end_date: Any, adjusted: bool = False) -> pd.DataFrame:
        data = self.get_some_data(self.get_current_freq(), copy=False)
        time_cols = self.get_time_cols(self.get_current_freq())
        if not time_cols:
            return pd.DataFrame()
        if 'DAY1' in time_cols:
            time_col = 'DAY1'
        else:
            time_col = sorted(time_cols, key=lambda x: DataFreq[str(x)].value)[0]
        # Resolve time_index: MultiIndex → get_level_values; DatetimeIndex → use directly; else look in columns
        if isinstance(data.index, pd.MultiIndex):
            time_index = data.index.get_level_values(time_col)
        elif isinstance(data.index, pd.DatetimeIndex):
            time_index = data.index
        elif time_col in data.columns:
            time_index = pd.to_datetime(data[time_col])
        else:
            return pd.DataFrame()
        if getattr(time_index, 'tz', None) is not None and self.timezone is not None:
            start_date = pd.to_datetime(start_date).tz_localize(self.timezone)
            end_date = pd.to_datetime(end_date).tz_localize(self.timezone)
        else:
            start_date = pd.to_datetime(start_date)
            end_date = pd.to_datetime(end_date)
        mask = (time_index >= start_date) & (time_index <= end_date)
        # 基础 OHLCV 列 + 可选 OI 列
        base_cols = ['OPEN', 'HIGH', 'LOW', 'CLOSE', 'VOLUME']
        if adjusted:
            adj_cols = ['OPEN_ADJUSTED', 'HIGH_ADJUSTED', 'LOW_ADJUSTED', 'CLOSE_ADJUSTED', 'VOLUME']
            if any(col not in data.columns for col in adj_cols):
                dataMeta = getattr(self, self.get_current_freq().name)
                data = dataMeta.get_and_adjust_cols(adj_cols)
            # 若复权列仍不可用（如非 Futures），则回退到原始 OHLCV
            selected = adj_cols if all(col in data.columns for col in adj_cols) else base_cols
        else:
            selected = list(base_cols)
        # 附加 OPEN_INTEREST 列（如有）
        if 'OPEN_INTEREST' in data.columns and 'OPEN_INTEREST' not in selected:
            selected.append('OPEN_INTEREST')
        return data.loc[mask][selected]

    def get_time_cols(self, data_freq: Optional[Any] = None) -> List[str]:
        data_freq = self.get_current_freq() if data_freq is None else DataFreq(data_freq)
        meta = getattr(self, data_freq.name)
        source = getattr(meta, 'current_source', None)
        if source is None:
            source = DataSource.select_for_product(self, data_freq)
        if source is None:
            return []
        return list(source.time_cols_mapping.values())
    
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
                    return cast(pd.DataFrame, data[target_cols].copy())
                else:
                    return cast(pd.DataFrame, data[target_cols])
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
        slice = self.get_slices(time_col=self.get_current_freq().name, time_range=time)
        return not slice.empty
