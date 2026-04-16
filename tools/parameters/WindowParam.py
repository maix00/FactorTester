from typing import Any, Optional

from tools.parameters.Parameter import Parameter, TimeDeltaParam

def WindowParam(alias: str, default_value: Optional[Any] = 1) -> Parameter:
    return Parameter(alias=alias, 
                     default_value=default_value, 
                     whether_in_space=lambda x: isinstance(x, int) and x > 0,
                     get_value_alias=lambda x: str(x)
                    ) + TimeDeltaParam(flag='pos', single_use=True)