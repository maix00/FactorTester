# =============================================================================
# tools/parameters/DataTimeParam.py
# DataTime 参数类型 — 日期/时间参数
#
# rectified 为 DataTime，可直接传给 DataIndex.slice_by_datatime()。
# isDate=True 参数（→ precision="trading_day"）。
# =============================================================================
import pandas as pd
from typing import Optional, Any, TYPE_CHECKING

from tools.decorators import factor_workspace
from tools.data.types import DataTime
from tools.parameters.Parameter import Parameter, ValueSpace

if TYPE_CHECKING:
    from typing import Any

@factor_workspace
class DataTimeParam(Parameter):
    input_help = (
        "填写可解析的日期或时间，例如 2026-09-01 或 2026-09-01 09:30:00；日期模式按交易日解释，"
        "精确时间模式可携带时区。"
    )

    @factor_workspace
    def __init__(self, alias: Optional[str] = None,
                 default_value: Optional[Any] = None, *args, **kwargs):
        if hasattr(self, '_initialized'):
            return
        if default_value is None:
            default_value = pd.Timestamp('2000-01-01').date()

        space = ValueSpace(
            contains=_is_valid_timestamp,
            rectify=lambda v: DataTime.parse(str(v)),
            alias=str,
        )

        super().__init__(
            alias=alias,
            value_space=space,
            default_value=default_value,
            *args, **kwargs
        )
        # 覆盖 rectify_value：DataTimeParam 的 rectify 依赖运行时 kwargs
        self.rectify_value = self._rectify_value
        self.default_value = self._rectify_value(self.default_value, **kwargs)

    def _rectify_value(self, value: Any, **kwargs) -> DataTime:
        if value is None:
            raise ValueError(f"DataTimeParam {self.alias}: value cannot be None")
        if isinstance(value, DataTime):
            return value
        ts = pd.Timestamp(value)
        isDate = kwargs.get('isDate', False)
        tz = kwargs.get('timezone', None)
        if isDate:
            return DataTime(ts=ts, precision='trading_day')
        else:
            return DataTime(ts=ts, tz=tz)

    def _get_value_alias(self, value: Any, **kwargs) -> str:
        dt = self._rectify_value(value, **kwargs)
        return str(dt.ts) if dt.ts is not None else str(dt)

    @factor_workspace
    def is_date(self, object: 'Optional[Any]' = None, value: Optional[Any] = None, **kwargs) -> bool:
        dt = self._resolve(object, value, **kwargs)
        return dt is not None and dt.precision == 'trading_day'

    @factor_workspace
    def is_time(self, object: 'Optional[Any]' = None, value: Optional[Any] = None, **kwargs) -> bool:
        dt = self._resolve(object, value, **kwargs)
        return dt is not None and dt.precision == 'exact'

    def _resolve(self, object: 'Optional[Any]', value: Optional[Any], **kwargs) -> Optional[DataTime]:
        if object is not None:
            return self.get_value(object)
        if value is not None:
            return self._rectify_value(value, **kwargs)
        return None


def _is_valid_timestamp(value: Any) -> bool:
    try:
        pd.Timestamp(value)
        return True
    except Exception:
        return False
