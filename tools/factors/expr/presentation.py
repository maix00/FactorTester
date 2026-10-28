"""Translate legacy expression field types into alpha's presentation protocol.

No formatting, labeling, computation or result storage is implemented here.
"""
from tools.data.types import DataColumn


def describe(expression):
    kind=type(expression).__name__
    fields={}
    if kind=='WhereOp':
        kind='OperandExpr'
    if kind=='ColumnRef':
        fields['column']=expression.column
    elif kind=='ParamRef':
        from tools.parameters import DataColumnParam, FactorParam
        fields['param']=expression.param
        fields['indexed_parameter']=isinstance(expression.param,(DataColumnParam,FactorParam))
        if isinstance(expression.param,DataColumnParam):
            fields['bound_column']=lambda value: DataColumn(value)
        default=expression.param.default_value
        # Declarations may carry deferred transport refs. Formula export never
        # invokes a remote resolver; a hydrated Factor supplies these fields.
        if isinstance(expression.param,FactorParam) and hasattr(default,'_expr'):
            family=getattr(default,'family',None)
            fields.update(nested_template=getattr(family,'_expr',default._expr),
                          nested_bound=default._expr,
                          nested_label=str(getattr(family,'alias',expression.param.alias)))
    elif kind=='ConstExpr':
        try:
            fields['display_column_name']=DataColumn(expression.value).name
        except (ValueError,TypeError,AttributeError):
            fields['display_column_name']=str(expression.value)
    elif hasattr(expression,'scope'):
        fields['scope']=expression.scope
    from alpha.factor.latex_formatters import RENDERERS
    if kind not in RENDERERS:
        custom=type(expression).__dict__.get('_to_latex')
        if custom is not None:
            return 'Literal', {'literal':custom(expression)}
    return kind,fields
