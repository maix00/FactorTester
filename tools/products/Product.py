# =============================================================================
# tools/products/Product.py
# 金融产品基类模块
#
# Product 是所有可交易产品的抽象基类，主要责责：
#   - 持有各频率的 DataMeta（如 product.MIN1、product.DAY1）
#   - 封装数据访问、频率选择、时间切片、价格获取等
#   - 管理 StartCalcPointParam（各阶段计算起始时间）
# 实际使用中一般会通过 CNFutures 等具体子类访问。
# =============================================================================
from typing import List, Optional, Any, TYPE_CHECKING
import pandas as pd

from tools.base.UniqueObject import UniqueObject
from tools.data.DataMeta import DataMeta
from tools.data.DataColumn import DataColumn
from tools.data.DataFreq import DataFreq
from tools.data.DataSource import DataSource

class Product(UniqueObject):
    """
    金融产品基类。

    初始化时会为每个已知 DataFreq（全局实例）自动创建对应的 DataMeta，
    并设置为同名属性（如 product.MIN1、product.DAY1）。

    属性：
        name        (str)       : 唯一识别名，如 'IF.CFE'
        point_value (int|None)  : 每手合约价值点乘数
        currency    (str|None)  : 计价货币
        timezone    (str|None)  : 对应时区，与 DataSource 匹配用于判断可用性
    """
    # 全局类属性标注（实际属性由具体子类提供）
    desc: str
    MIN1: DataMeta   # 1 分钟数据
    DAY1: DataMeta   # 1 日数据

    def __init__(self, name: str,
                 point_value: Optional[int] = None,
                 currency: Optional[str] = None, *args, **kwargs):
        if not hasattr(self, '_initialized'):
            super().__init__(name=name, *args, **kwargs)
            self.point_value = point_value
            self.currency = currency
            self.timezone = kwargs.get('timezone', None)
            # 为每个已知频率创建 DataMeta 对象，设为对应属性
            for freq in DataFreq:
                setattr(self, freq.name, DataMeta(alias=f"{freq}", object=self, data_freq=freq, timezone=self.timezone))
            if TYPE_CHECKING:
                from tools.parameters import DateOrTimeParam
            self._StartCalcPointParam : DateOrTimeParam  # 计算起始点参数属性

    if TYPE_CHECKING:
        from tools.parameters import DateOrTimeParam
    def set_StartCalcPointParam(self, param: 'DateOrTimeParam', value: Optional[Any] = None):
        """设置本产品的计算起始点参数并注册值。"""
        self._StartCalcPointParam = param
        param.register(self, value if value is not None else param.default_value)

    def get_StartCalcPointParam(self) -> 'Optional[DateOrTimeParam]':
        """获取本产品已设置的计算起始点参数。"""
        return getattr(self, '_StartCalcPointParam', None)
        
    def list_available_freqs(self) -> List[DataFreq]:
        """列出本产品在所有已注册 DataSource 中可用的数据频率。"""
        return [source.freq for source in DataSource if source.if_object_is_in_source(self)]
    
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
        if adjusted:
            list_cols = ['OPEN_ADJUSTED', 'HIGH_ADJUSTED', 'LOW_ADJUSTED', 'CLOSE_ADJUSTED', 'VOLUME']
            if any([col not in data.columns for col in list_cols]):
                dataMeta = getattr(self, self.get_current_freq().name)
                data = dataMeta.get_and_adjust_cols(list_cols)
            return data.loc[mask][list_cols]
        else:
            return data.loc[mask][['OPEN', 'HIGH', 'LOW', 'CLOSE', 'VOLUME']]

    def get_time_cols(self, data_freq: Optional[Any] = None) -> List[str]:
        data_freq = self.get_current_freq() if data_freq is None else DataFreq(data_freq)
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
        slice = self.get_slices(time_col=self.get_current_freq().name, time_range=time)
        return not slice.empty