from typing import Any, Optional

from tools.decorators import factor_workspace
from tools.parameters.Parameter import Parameter, ValueSpace


@factor_workspace
class WindowParam(Parameter):
    """窗口参数：支持正整数或正 timedelta。"""
    input_help = (
        "填写正整数表示 bar 数，或填写正时间长度（如 30m、2h、20d）；零、负数和无法解析的单位无效。"
    )

    @factor_workspace
    def __init__(self, alias: str, default_value: Optional[Any] = 1, *args, **kwargs):
        if hasattr(self, '_initialized'):
            return
        td_space = ValueSpace.timedelta('pos')
        int_space = ValueSpace(
            contains=lambda x: (
                isinstance(x, int) and not isinstance(x, bool) and x > 0
            ) or (
                isinstance(x, str) and x.strip().isdigit() and int(x.strip()) > 0
            ),
            rectify=lambda x: int(str(x).strip()),
            alias=str,
        )
        space = int_space.union(td_space)
        super().__init__(
            alias=alias,
            value_space=space,
            default_value=default_value,
            *args, **kwargs
        )
