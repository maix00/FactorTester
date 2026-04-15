from typing import List, Optional, Any, TYPE_CHECKING
import pandas as pd

from tools.base.UniqueObject import UniqueObject
from tools.data.DataMeta import DataMeta
from tools.data.DataColumn import DataColumn
from tools.data.DataFreq import DataFreq
from tools.data.DataSource import DataSource

class Product(UniqueObject):
    # _default_category_attr_name = '__class__.__name__'  # Default attribute name for category
    desc: str
    MIN1: DataMeta
    DAY1: DataMeta

    def __init__(self, name: str,
                 point_value: Optional[int] = None,
                 currency: Optional[str] = None,
                 category_attr_name: Optional[str] = None, *args, **kwargs):
        if not hasattr(self, '_initialized'):
            super().__init__(name=name, *args, **kwargs)
            self.point_value = point_value
            self.currency = currency
            self.timezone = kwargs.get('timezone', None)
            for freq in DataFreq:
                setattr(self, freq.name, DataMeta(alias=f"{freq}", object=self, data_freq=freq, timezone=self.timezone))
            if TYPE_CHECKING:
                from tools.parameters.Parameter import DateOrTimeParam
            self._StartCalcPointParam : DateOrTimeParam

    if TYPE_CHECKING:
        from tools.parameters.Parameter import DateOrTimeParam
    def set_StartCalcPointParam(self, param: DateOrTimeParam, value: Optional[Any] = None):
        self._StartCalcPointParam = param
        param.register(self, value if value is not None else param.default_value)

    def get_StartCalcPointParam(self) -> DateOrTimeParam:
        return self._StartCalcPointParam
        
    def list_available_freqs(self) -> List[DataFreq]:
        return [source.freq for source in DataSource if source.if_object_is_in_source(self)]
    
    def set_current_freq(self, freq: Any) -> DataFreq:
        if freq in self.list_available_freqs():
            self.current_freq = freq
            return freq
        else:
            raise ValueError(f"Data frequency {freq} is not available for product {self.name}")
        
    def get_current_freq(self) -> DataFreq:
        if not hasattr(self, 'current_freq'):
            available_freqs = self.list_available_freqs()
            if len(available_freqs) == 0:
                raise ValueError(f"No data frequency available for product {self.name}")
            self.current_freq = available_freqs[0]
        return getattr(self, 'current_freq')
    
    def get_some_data(self, data_freq: Optional[Any] = None, copy: bool = True) -> pd.DataFrame:
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
        if getattr(data.index.get_level_values(time_col), 'tz', None) is not None and self.timezone is not None:
            start_date = pd.to_datetime(start_date).tz_localize(self.timezone)
            end_date = pd.to_datetime(end_date).tz_localize(self.timezone)
        else:
            start_date = pd.to_datetime(start_date)
            end_date = pd.to_datetime(end_date)
        mask = (data.index.get_level_values(time_col) >= start_date) & \
               (data.index.get_level_values(time_col) <= end_date)
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