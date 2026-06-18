FACTOR_WORKSPACE = True

if FACTOR_WORKSPACE:
    from tools.parameters.Parameter import Parameter, TypeParam, FinRangeParam, TimeDeltaParam, FactorParam, ValueSpace
    from tools.parameters.DataColumnParam import DataColumnParam
    from tools.parameters.DataTimeParam import DataTimeParam
    from tools.parameters.WindowParam import WindowParam

__all__ = [
    "Parameter",
    "TypeParam",
    "FinRangeParam",
    "TimeDeltaParam",
    "FactorParam",
    "ValueSpace",
    "DataColumnParam",
    "DataTimeParam",
    "WindowParam",
]
