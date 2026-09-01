"""Serialize FactorExpr trees into the custom factor visual editor graph."""

from __future__ import annotations

from typing import Any

from tools.data.types import DataColumn
from tools.factors.FactorExpr import (
    ColumnRef,
    CompositeExpr,
    ConstExpr,
    CrossSectionalOp,
    FactorExpr,
    ParamRef,
    RollingOp,
    ShiftOp,
    TermStructureOp,
    get_visual_composite_key,
    get_visual_operator_category,
)


def factor_expr_to_visual_graph(expr: FactorExpr | None) -> dict[str, Any] | None:
    """Convert a FactorExpr tree into the frontend visual graph format."""
    if expr is None:
        return None

    serializer = _VisualGraphSerializer()
    root_id = serializer.emit(expr)
    if root_id is None:
        return None
    return_id = serializer.add_node(
        key='Return',
        cat='output',
        label='return',
        inputs=[root_id],
        params={},
    )
    return {
        'nodes': serializer.nodes,
        'root_id': return_id,
        'next_id': serializer.next_id,
    }


class _VisualGraphSerializer:
    def __init__(self):
        self.nodes: list[dict[str, Any]] = []
        self.next_id = 1
        self._seen: dict[tuple, int] = {}

    def emit(self, expr: FactorExpr | None) -> int | None:
        if expr is None:
            return None

        key = self._expr_cache_key(expr)
        if key in self._seen:
            return self._seen[key]

        if isinstance(expr, ParamRef):
            node_id = self.add_param_ref(expr)
        elif isinstance(expr, ConstExpr):
            node_id = self.add_const(expr)
        elif isinstance(expr, ColumnRef):
            node_id = self.add_column_ref(expr)
        elif isinstance(expr, ShiftOp):
            node_id = self.add_op(expr.op, 'ts', self._intermediate_label(expr) or expr.op, [
                self.emit(expr.operand),
                self.emit(expr.periods),
            ], expr)
        elif isinstance(expr, RollingOp):
            data_ids = [self.emit(opnd) for opnd in expr.operands[1:]]
            node_id = self.add_op(expr.op, 'ts', self._intermediate_label(expr) or expr.op, [
                *data_ids,
                self.emit(expr.window),
            ], expr)
        elif isinstance(expr, CrossSectionalOp):
            node_id = self.add_op(expr.op, 'cs', self._intermediate_label(expr) or expr.op, [
                self.emit(opnd) for opnd in expr.operands
            ], expr)
        elif isinstance(expr, TermStructureOp):
            node_id = self.add_term_structure_op(expr)
        elif isinstance(expr, CompositeExpr):
            visual_key = get_visual_composite_key(expr.op)
            cat = get_visual_operator_category(visual_key, 'arithBinary')
            node_id = self.add_op(visual_key, cat, self._intermediate_label(expr) or visual_key, [
                self.emit(opnd) for opnd in expr.operands
            ], expr)
        else:
            visual_key = getattr(expr, 'op', type(expr).__name__)
            node_id = self.add_op(visual_key, 'arithBinary', self._intermediate_label(expr) or visual_key, [
                self.emit(opnd) for opnd in getattr(expr, 'operands', ())
            ], expr)

        if key is not None and node_id is not None:
            self._seen[key] = node_id
        return node_id

    def add_param_ref(self, expr: ParamRef) -> int:
        param = expr.param
        alias = getattr(param, 'alias', '') or 'P'
        param_type = _visual_param_type(param)
        key = 'FactorFreqParam' if param_type == 'FactorFreqParam' else 'DataColumnParam'
        default_value = _serialize_param_default(param)
        return self.add_node(
            key=key,
            cat='leaf',
            label=alias,
            inputs=[],
            params={
                'alias': alias,
                'type': param_type,
                'default_value': default_value,
                'locked': key == 'FactorFreqParam',
            },
        )

    def add_const(self, expr: ConstExpr) -> int:
        return self.add_node(
            key='Constant',
            cat='leaf',
            label='',
            inputs=[],
            params={'name': '', 'value': _python_literal(expr.value)},
        )

    def add_term_structure_op(self, expr: TermStructureOp) -> int:
        params: dict[str, Any] = {}
        intermediate = self._intermediate_label(expr)
        if intermediate:
            params['intermediate_name'] = intermediate
            params['intermediate_user_defined'] = True
            params['intermediate_from_factor_expr'] = True
        input_ids = [self.emit(opnd) for opnd in expr.operands]
        return self.add_node(
            key=expr.op,
            cat='termStructure',
            label=intermediate or expr.op,
            inputs=[i for i in input_ids if i],
            params=params,
        )

    def add_column_ref(self, expr: ColumnRef) -> int:
        value = expr.column.value if isinstance(expr.column, DataColumn) else str(expr.column)
        return self.add_node(
            key='DataColumnParam',
            cat='leaf',
            label=value,
            inputs=[],
            params={'alias': value, 'type': 'DataColumnParam', 'default_value': value},
        )

    def add_op(
        self,
        key: str,
        cat: str,
        label: str,
        inputs: list[int | None],
        expr: FactorExpr,
    ) -> int:
        params: dict[str, Any] = {}
        intermediate = self._intermediate_label(expr)
        if intermediate:
            params['intermediate_name'] = intermediate
            params['intermediate_user_defined'] = True
            params['intermediate_from_factor_expr'] = True
            label = intermediate
        return self.add_node(key=key, cat=cat, label=label, inputs=[i for i in inputs if i], params=params)

    def add_node(
        self,
        key: str,
        cat: str,
        label: str,
        inputs: list[int],
        params: dict[str, Any],
    ) -> int:
        node_id = self.next_id
        self.next_id += 1
        self.nodes.append({
            'id': node_id,
            'key': key,
            'cat': cat,
            'label': label,
            'x': 0,
            'y': 0,
            'inputs': inputs,
            'params': params,
        })
        return node_id

    @staticmethod
    def _intermediate_label(expr: FactorExpr) -> str:
        return str(getattr(expr, '_intermediate_name', '') or '')

    @staticmethod
    def _expr_cache_key(expr: FactorExpr) -> tuple | None:
        try:
            return expr._structural_key()
        except Exception:
            return None


def _serialize_param_default(param: Any) -> str:
    value = getattr(param, 'default_value', '')
    try:
        return str(param.get_value_alias(value))
    except Exception:
        if isinstance(value, DataColumn):
            return value.value
        return str(value)


def _visual_param_type(param: Any) -> str:
    alias = getattr(param, 'alias', '') or ''
    if alias == '$F':
        return 'FactorFreqParam'
    if alias == '$Rev':
        return 'ReverseParam'
    return type(param).__name__


def _python_literal(value: Any) -> str:
    if isinstance(value, DataColumn):
        return repr(value.value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return repr(value)
    return repr(str(value))
