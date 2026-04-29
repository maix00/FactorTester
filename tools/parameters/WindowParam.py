from typing import Any, Optional

from tools.parameters.Parameter import Parameter, ValueSpace

def WindowParam(alias: str, default_value: Optional[Any] = 1) -> Parameter:
    td_space = ValueSpace.timedelta('pos')
    int_space = ValueSpace(contains=lambda x: isinstance(x, int) and x > 0, alias=str)
    space = int_space.union(td_space)
    param = Parameter(alias=alias, value_space=space, default_value=default_value)
    return param