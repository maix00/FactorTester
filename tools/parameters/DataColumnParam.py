from typing import Optional, Any

from tools.decorators import factor_workspace
from tools.data.types import DataColumn
from tools.parameters.Parameter import Parameter, ValueSpace

@factor_workspace
class DataColumnParam(Parameter):
    input_help = (
        "填写 DataColumn/ColumnRef alias（如 C、CA、V、TO、OI），或从 Column 候选中选择一列。"
    )

    @factor_workspace
    def __init__(self, alias: Optional[str] = None, default_value: Optional[Any] = None, *args, **kwargs):
        if hasattr(self, '_initialized'):
            return
        if default_value is not None:
            default_value = DataColumn(default_value)
        else:
            try:
                from itertools import takewhile
                result = ''.join(takewhile(str.isalpha, alias)) if alias else ''
                default_value = DataColumn(result.upper()) if alias else None
            except:
                pass

        space = ValueSpace(
            contains=lambda v: _is_valid_datacolumn(v),
            rectify=lambda v: DataColumn(v),
            alias=lambda v: {col: col.value for col in DataColumn}.get(v, str(v)),
        )

        super().__init__(
            alias=alias,
            value_space=space,
            default_value=default_value,
            *args, **kwargs
        )

    @factor_workspace
    def col(self, col: Any):
        from tools.data.types import DataColumn
        col = DataColumn(col)
        return self.get_value_alias(col)


def _is_valid_datacolumn(value: Any) -> bool:
    from tools.data.types import DataColumn
    try:
        DataColumn(value)
        return True
    except Exception:
        return False


if __name__ == '__main__':
    C1 = DataColumnParam('C1')
    print(C1.col(DataColumn.CLOSE))
