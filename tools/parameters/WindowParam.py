from typing import Any, Optional

from tools.parameters.Parameter import Parameter, TimeDeltaParam

def WindowParam(alias: str, default_value: Optional[Any] = 1) -> Parameter:
    param = Parameter(alias=alias,
                      default_value=1,
                      whether_in_space=lambda x: isinstance(x, int) and x > 0,
                      get_value_alias=lambda x: str(x))
    param += TimeDeltaParam(flag='pos', single_use=True)
    param.change_default_value(default_value)
    return param