from typing import Optional, Any

from tools import DataColumn
from tools.parameters.Parameter import TypeParam

class DataColumnParam(TypeParam):
    def __init__(self, alias: Optional[str] = None, default_value: Optional[Any] = None, *args, **kwargs):
        if default_value is not None:
            default_value = DataColumn(default_value)
        else:
            try:
                from itertools import takewhile
                result = ''.join(takewhile(str.isalpha, alias)) if alias else ''
                default_value = DataColumn(result.upper()) if alias else None
            except:
                pass
        if not hasattr(self, '_initialized'):
            super().__init__(
                alias = alias,
                default_value=default_value,
                whether_in_space=self._whether_in_space,
                get_value_alias = lambda x: {col: col.value for col in DataColumn}.get(x, str(x)),
                *args, **kwargs
            )
        else:
            self.default_value = default_value

    def _whether_in_space(self, value: Any) -> bool:
        from tools import DataColumn
        try:
            DataColumn(value)
            return True
        except Exception:
            return False
        
    def _rectify_value(self, value: Any, **kwargs) -> Any:
        from tools import DataColumn
        return DataColumn(value)
    
    def col(self, col: Any):
        from tools import DataColumn
        col = DataColumn(col)
        return self.get_value_alias(col)

if __name__ == '__main__':
    C1 = DataColumnParam('C1')
    print(C1.col(DataColumn.CLOSE))