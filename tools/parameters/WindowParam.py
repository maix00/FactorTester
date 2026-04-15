from typing import Any, Optional

from tools.parameters.Parameter import Parameter, TimeDeltaParam, TypeParam

def WindowParam(alias: str, default_value: Optional[Any] = 1) -> Parameter:
    return TypeParam(alias=alias, default_value=default_value, type_=int, whether_in_space=lambda x: x > 0) + TimeDeltaParam(flag='pos', single_use=True)