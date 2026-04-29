import pandas as pd
from typing import Optional, Any

from tools.parameters.Parameter import Parameter, ValueSpace

class DateOrTimeParam(Parameter):
    def __init__(self, alias: Optional[str] = None,
                 default_value: Optional[Any] = None, *args, **kwargs):
        if hasattr(self, '_initialized'):
            return
        if default_value is None:
            default_value = pd.Timestamp('2000-01-01').date()

        space = ValueSpace(
            contains=_is_valid_timestamp,
            rectify=lambda v: pd.Timestamp(v),
            alias=str,
        )

        super().__init__(
            alias=alias,
            value_space=space,
            default_value=default_value,
            *args, **kwargs
        )
        # 覆盖 rectify_value：DateOrTimeParam 的 rectify 依赖运行时 kwargs
        self.rectify_value = self._rectify_value
        self.default_value = self._rectify_value(self.default_value, **kwargs)

    def _rectify_value(self, value: Any, **kwargs) -> Any:
        if self.check_in_space(value):
            import datetime
            isDate = kwargs.get('isDate', None) or type(value) is datetime.date
            isDatetime = kwargs.get('isDatetime', None)
            timezone = kwargs.get('timezone', None)
            value = pd.Timestamp(value, tz=timezone)
            if isDate is not None and isDatetime is not None and isDate and isDatetime:
                raise ValueError(f"DateOrTimeParam {self.name}: Cannot specify both isDate and isDatetime for {value}")
            if isDate is not None and isDate:
                return value.date()
            return value

    def _get_value_alias(self, value: Any, **kwargs) -> str:
        return str(self._rectify_value(value, **kwargs))

    def is_date(self, object, value: Optional[Any] = None, **kwargs) -> bool:
        value = self.get_value(object) if object is not None else self._rectify_value(value, **kwargs)
        assert value is not None, "Either object or value must be provided"
        import datetime
        return type(value) is datetime.date

    def is_time(self, object: Optional[UniqueObject] = None, value: Optional[Any] = None, **kwargs) -> bool:
        value = self.get_value(object) if object is not None else self._rectify_value(value, **kwargs)
        assert value is not None, "Either object or value must be provided"
        import datetime
        return not type(value) is datetime.date


def _is_valid_timestamp(value: Any) -> bool:
    try:
        pd.Timestamp(value)
        return True
    except Exception:
        return False
