from typing import Any, Optional

from tools.parameters.Parameter import Parameter, ValueSpace


class WindowParam(Parameter):
    """窗口参数：支持正整数或正 timedelta。"""

    def __init__(self, alias: str, default_value: Optional[Any] = 1, *args, **kwargs):
        if hasattr(self, '_initialized'):
            return
        td_space = ValueSpace.timedelta('pos')
        int_space = ValueSpace(contains=lambda x: isinstance(x, int) and x > 0, alias=str)
        space = int_space.union(td_space)
        super().__init__(
            alias=alias,
            value_space=space,
            default_value=default_value,
            *args, **kwargs
        )