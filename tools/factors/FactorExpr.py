# =============================================================================
# tools/factors/FactorExpr.py
# 因子表达式系统
#
# 核心思想：因子 = 表达式树，通过运算符组合基本列引用和算子，
# 自动构建依赖关系图，运行时按依赖拓扑顺行求值。
#
# 设计架构（三层）：
#
#   Layer 1 — 叶子节点 (FactorTerm)
#     引用基础数据列：OPEN, HIGH, LOW, CLOSE, VOLUME, ...
#     每个品种有自己的一条时序，组合后形成横截面 DataFrame
#
#   Layer 2 — 算子节点 (FactorOp)
#     时序算子（按品种独立计算）：rolling_mean, rolling_std, shift, delta, ...
#     横截面算子（逐时间点计算）：CS_ZSCORE, CS_RANK, CS_WEIGHTED, ...
#
#   Layer 3 — 表达式组合 (FactorExpr)
#     算术运算：expr1 + expr2, expr1 - expr2, expr1 * expr2, expr1 / expr2
#     比较运算：expr1 > expr2, expr1 == expr2
#     逻辑运算：expr1 & expr2, expr1 | expr2
#     聚合运算：max(expr1, expr2, ...), min(expr1, expr2, ...)
#
# 表达式求值：
#   1. 构建依赖 DAG（每个节点记录其上游依赖）
#   2. 拓扑排序确定求值顺序
#   3. 每个节点从 product.{freq} 获取原始数据，计算自身结果并缓存
#   4. 最终返回 "products × time" 的 DataFrame
#
# =============================================================================
from __future__ import annotations

import pandas as pd
import numpy as np
from typing import (
    TYPE_CHECKING, Any, Callable, Dict, List, Optional, Sequence, Set, Tuple, Union, cast
)

from tools.data.DataColumn import DataColumn
from tools.data.DataFreq import DataFreq

if TYPE_CHECKING:
    from tools.products.Product import Product
    from tools.data.DataSource import DataSource
    from tools.data.DataMeta import DataMeta
    from tools.parameters.Parameter import Parameter


VISUAL_OPERATOR_GROUPS = [
    {
        'key': 'leaf',
        'label': '参数/常数',
        'collapsed': False,
        'operators': [
            {'key': 'DataColumnParam', 'label': '参数', 'symbol': 'P', 'desc': '数据列/窗口/时间参数', 'arity': 0, 'slots': []},
            {'key': 'FactorFreqParam', 'label': '系统频率', 'symbol': '$F', 'desc': '系统参数：因子信号频率', 'arity': 0, 'slots': []},
            {'key': 'Constant', 'label': '常数', 'symbol': '1', 'desc': '数值常量', 'arity': 0, 'slots': []},
        ],
    },
    {
        'key': 'ts',
        'label': '时序算子',
        'collapsed': False,
        'operators': [
            {'key': 'rolling_mean', 'label': '均值', 'symbol': 'RMean', 'desc': 'X.rolling_mean(N)', 'arity': 2, 'slots': ['序列 X', '窗口 N']},
            {'key': 'rolling_std', 'label': '标准差', 'symbol': 'RStd', 'desc': 'X.rolling_std(N)', 'arity': 2, 'slots': ['序列 X', '窗口 N']},
            {'key': 'rolling_min', 'label': '最小值', 'symbol': 'RMin', 'desc': 'X.rolling_min(N)', 'arity': 2, 'slots': ['序列 X', '窗口 N']},
            {'key': 'rolling_max', 'label': '最大值', 'symbol': 'RMax', 'desc': 'X.rolling_max(N)', 'arity': 2, 'slots': ['序列 X', '窗口 N']},
            {'key': 'shift', 'label': '平移', 'symbol': 'shift', 'desc': 'X.shift(N)', 'arity': 2, 'slots': ['序列 X', '步长 N']},
            {'key': 'delta', 'label': '差分', 'symbol': 'delta', 'desc': 'X.delta(N)', 'arity': 2, 'slots': ['序列 X', '步长 N']},
        ],
        'more_label': '更多时序算子',
        'more_operators': [
            {'key': 'rolling_var', 'label': '方差', 'symbol': 'RVar', 'desc': 'X.rolling_var(N)', 'arity': 2, 'slots': ['序列 X', '窗口 N']},
            {'key': 'rolling_sum', 'label': '求和', 'symbol': 'RSum', 'desc': 'X.rolling_sum(N)', 'arity': 2, 'slots': ['序列 X', '窗口 N']},
            {'key': 'rolling_ema', 'label': 'EMA', 'symbol': 'REMA', 'desc': 'X.rolling_ema(N)', 'arity': 2, 'slots': ['序列 X', '窗口 N']},
            {'key': 'rolling_corr', 'label': '滚动相关', 'symbol': 'RCorr', 'desc': 'X.rolling_corr(Y, N)', 'arity': 3, 'slots': ['序列 X', '序列 Y', '窗口 N']},
            {'key': 'rolling_skew', 'label': '偏度', 'symbol': 'RSkew', 'desc': 'X.rolling_skew(N)', 'arity': 2, 'slots': ['序列 X', '窗口 N']},
            {'key': 'rolling_argmax', 'label': '最大位置', 'symbol': 'RArgMax', 'desc': 'X.rolling_argmax(N)', 'arity': 2, 'slots': ['序列 X', '窗口 N']},
            {'key': 'rolling_argmin', 'label': '最小位置', 'symbol': 'RArgMin', 'desc': 'X.rolling_argmin(N)', 'arity': 2, 'slots': ['序列 X', '窗口 N']},
        ],
    },
    {
        'key': 'cs',
        'label': '横截算子',
        'collapsed': False,
        'operators': [
            {'key': 'cs_rank', 'label': '截面排名', 'symbol': 'Rank', 'desc': 'X.cs_rank()', 'arity': 1, 'slots': ['序列 X']},
            {'key': 'cs_zscore', 'label': '截面标准化', 'symbol': 'Z', 'desc': 'X.cs_zscore()', 'arity': 1, 'slots': ['序列 X']},
        ],
        'more_label': '更多横截算子',
        'more_operators': [
            {'key': 'cs_spearman', 'label': 'Spearman', 'symbol': 'rho_s', 'desc': 'X.cs_spearman(Y)', 'arity': 2, 'slots': ['序列 X', '序列 Y']},
        ],
    },
    {
        'key': 'arithUnary',
        'label': '算数一元',
        'collapsed': False,
        'operators': [
            {'key': 'log', 'label': '对数', 'symbol': 'log', 'desc': 'X.log()', 'arity': 1, 'slots': ['序列 X']},
            {'key': 'abs', 'label': '绝对值', 'symbol': 'abs', 'desc': 'X.abs()', 'arity': 1, 'slots': ['序列 X']},
        ],
        'more_label': '更多算数一元',
        'more_operators': [
            {'key': 'sqrt', 'label': '平方根', 'symbol': 'sqrt', 'desc': 'X.sqrt()', 'arity': 1, 'slots': ['序列 X']},
            {'key': 'sign', 'label': '符号', 'symbol': 'sign', 'desc': 'X.sign()', 'arity': 1, 'slots': ['序列 X']},
            {'key': 'neg', 'label': '取负', 'symbol': '-', 'desc': 'X.neg()', 'arity': 1, 'slots': ['序列 X']},
            {'key': '~', 'label': '逻辑非', 'symbol': '~', 'desc': '~A', 'arity': 1, 'slots': ['条件 X'], 'syntax': 'prefix'},
        ],
    },
    {
        'key': 'arithBinary',
        'label': '算数二元',
        'collapsed': False,
        'operators': [
            {'key': '+', 'label': '加法', 'symbol': '+', 'desc': 'A + B', 'arity': 2, 'slots': ['左项', '右项'], 'syntax': 'infix'},
            {'key': '-', 'label': '减法', 'symbol': '-', 'desc': 'A - B', 'arity': 2, 'slots': ['被减数', '减数'], 'syntax': 'infix'},
            {'key': '*', 'label': '乘法', 'symbol': '*', 'desc': 'A * B', 'arity': 2, 'slots': ['左因子', '右因子'], 'syntax': 'infix'},
            {'key': '/', 'label': '除法', 'symbol': '/', 'desc': 'A / B', 'arity': 2, 'slots': ['分子', '分母'], 'syntax': 'infix'},
        ],
        'more_label': '更多算数二元',
        'more_operators': [
            {'key': '**', 'label': '幂', 'symbol': '**', 'desc': 'A ** B', 'arity': 2, 'slots': ['底数', '指数'], 'syntax': 'infix'},
            {'key': 'max', 'label': '逐元素 max', 'symbol': 'max', 'desc': 'A.max(B)', 'arity': 2, 'slots': ['左值', '右值']},
            {'key': 'min', 'label': '逐元素 min', 'symbol': 'min', 'desc': 'A.min(B)', 'arity': 2, 'slots': ['左值', '右值']},
            {'key': '>', 'label': '大于', 'symbol': '>', 'desc': 'A > B', 'arity': 2, 'slots': ['左比较项', '右比较项'], 'syntax': 'infix'},
            {'key': '<', 'label': '小于', 'symbol': '<', 'desc': 'A < B', 'arity': 2, 'slots': ['左比较项', '右比较项'], 'syntax': 'infix'},
            {'key': '>=', 'label': '大于等于', 'symbol': '>=', 'desc': 'A >= B', 'arity': 2, 'slots': ['左比较项', '右比较项'], 'syntax': 'infix'},
            {'key': '<=', 'label': '小于等于', 'symbol': '<=', 'desc': 'A <= B', 'arity': 2, 'slots': ['左比较项', '右比较项'], 'syntax': 'infix'},
            {'key': '==', 'label': '等于', 'symbol': '==', 'desc': 'A == B', 'arity': 2, 'slots': ['左比较项', '右比较项'], 'syntax': 'infix'},
            {'key': '!=', 'label': '不等于', 'symbol': '!=', 'desc': 'A != B', 'arity': 2, 'slots': ['左比较项', '右比较项'], 'syntax': 'infix'},
            {'key': '&', 'label': '逻辑与', 'symbol': '&', 'desc': 'A & B', 'arity': 2, 'slots': ['左条件', '右条件'], 'syntax': 'infix'},
            {'key': '|', 'label': '逻辑或', 'symbol': '|', 'desc': 'A | B', 'arity': 2, 'slots': ['左条件', '右条件'], 'syntax': 'infix'},
        ],
    },
    {
        'key': 'arithVariadic',
        'label': '算数多元',
        'collapsed': False,
        'operators': [
            {'key': 'expr_max', 'label': '多元 max', 'symbol': 'max', 'desc': 'max(A, B, C)', 'arity': 3, 'slots': ['输入 A', '输入 B', '输入 C'], 'syntax': 'function'},
            {'key': 'expr_min', 'label': '多元 min', 'symbol': 'min', 'desc': 'min(A, B, C)', 'arity': 3, 'slots': ['输入 A', '输入 B', '输入 C'], 'syntax': 'function'},
        ],
        'more_label': '更多算数多元',
        'more_operators': [
        ],
    },
    {
        'key': 'termStructure',
        'label': '期限结构',
        'collapsed': False,
        'operators': [
            {
                'key': 'term_spread',
                'label': '近远月价差',
                'symbol': 'TSprd',
                'desc': '隐式使用当前产品/时间/期限结构表；输入 near_rank, far_rank, column；返回 near - far。',
                'arity': 3,
                'slots': ['近端 rank', '远端 rank', '字段 column'],
            },
            {
                'key': 'term_ratio',
                'label': '近远月比值',
                'symbol': 'TRatio',
                'desc': '隐式使用当前产品/时间/期限结构表；输入 near_rank, far_rank, column；返回 near / far - 1。',
                'arity': 3,
                'slots': ['近端 rank', '远端 rank', '字段 column'],
            },
            {
                'key': 'term_slope',
                'label': '期限斜率',
                'symbol': 'TSlope',
                'desc': '隐式使用当前产品/时间/期限结构表；输入 depth, column；返回价格对剩余期限的线性斜率。',
                'arity': 2,
                'slots': ['合约深度 depth', '字段 column'],
            },
        ],
        'more_label': '更多期限结构算子',
        'more_operators': [
        ],
    },
]

VISUAL_COMPOSITE_KEY = {
    'add': '+',
    'sub': '-',
    'mul': '*',
    'div': '/',
    'pow': '**',
    'gt': '>',
    'lt': '<',
    'ge': '>=',
    'le': '<=',
    'eq': '==',
    'ne': '!=',
    'and': '&',
    'or': '|',
    'not': '~',
    'neg': 'neg',
    'abs': 'abs',
    'log': 'log',
    'sqrt': 'sqrt',
    'sign': 'sign',
    'bimax': 'max',
    'bimin': 'min',
    'max': 'expr_max',
    'min': 'expr_min',
}

VISUAL_OPERATOR_CATEGORY = {
    '~': 'arithUnary',
    'neg': 'arithUnary',
    'abs': 'arithUnary',
    'log': 'arithUnary',
    'sqrt': 'arithUnary',
    'sign': 'arithUnary',
    'expr_max': 'arithVariadic',
    'expr_min': 'arithVariadic',
    'term_spread': 'termStructure',
    'term_ratio': 'termStructure',
    'term_slope': 'termStructure',
}


def get_visual_operator_groups() -> list[dict]:
    """Return visual-editor operator metadata derived from FactorExpr capabilities."""
    return VISUAL_OPERATOR_GROUPS


def get_visual_composite_key(op: str) -> str:
    """Return the visual-editor key for a CompositeExpr op."""
    return VISUAL_COMPOSITE_KEY.get(op, op)


def get_visual_operator_category(visual_key: str, default: str = 'arithBinary') -> str:
    """Return the visual-editor category for a visual operator key."""
    return VISUAL_OPERATOR_CATEGORY.get(visual_key, default)


# ═════════════════════════════════════════════════════════════════════════════
# Layer 1: 因子表达式基类
# ═════════════════════════════════════════════════════════════════════════════

class FactorExpr:
    """
    因子表达式抽象基类。

    所有叶子节点、算子节点、复合表达式都继承此类。
    核心能力：
      - 运算符重载（+, -, *, /, >, <, ==, &, |）
      - 依赖追踪（.dependencies 返回上游节点集合）
      - 求值接口（.evaluate(data, source=...) → DataFrame）
      - LaTeX 表达式生成（.to_latex() → str）

    数据源：
      evaluate() 接受 source: DataSource 参数。若未指定，自动为每个品种
      选择包含所需列的第一个可用数据源；若指定了 source，校验是否兼容后使用。
    """

    __array_priority__ = 1000

    # ── 中间因子标记 ──

    _is_intermediate: bool = False
    _intermediate_name: 'str | None' = None
    _intermediate_factor: Optional[FactorExpr] = None

    def as_intermediate(self, name: 'str | None' = None, factor: Optional['FactorExpr'] = None) -> 'FactorExpr':
        """标记此表达式节点为中间因子，evaluate 时自动创建 FactorData。

        name: 可选名称，用于后续查询（如 'FE', 'RE'）。
              None 表示匿名中间因子（仅创建 FactorData 不做命名映射）。
        """
        factor = factor or self
        if isinstance(self, OperandExpr) and self.op == 'neg':
            self._is_intermediate = False
            return CompositeExpr('neg', self.operands[0].as_intermediate(name, factor))
        else:
            self._is_intermediate = True
            self._intermediate_name = name
            self._intermediate_factor = factor
            return self

    # ── 可哈希（用于 set/dict 中的依赖追踪和缓存） ──

    def __hash__(self) -> int:
        return id(self)

    # ── 结构等价（用于 FactorData 去重 key） ──

    _SYMMETRIC_OPS = frozenset({
        'add', 'mul', 'and', 'or', 'max', 'min', 'bimax', 'bimin', 'eq', 'ne',
        'cs_spearman', 'cs_corr', 'cs_cov',
    })

    def _structural_hash(self) -> int:
        """
        递归计算表达式树的结构 hash。

        对于对称二元运算，operand 顺序无关（先 sort operands 的 hash）。
        对于非对称运算，按原始顺序计算。
        """
        return hash(self._structural_key())

    def _structural_key(self) -> tuple:
        """
        返回表达式树的标准化元组表示，用于结构等价判断和 hash。

        格式：(type_tag, ...type_specific...)
        """
        raise NotImplementedError(
            f"{type(self).__name__} 未实现 _structural_key()")

    def _structural_eq(self, other: 'FactorExpr') -> bool:
        """基于结构的表达式等价判断。"""
        if type(self) is not type(other):
            return False
        return self._structural_key() == other._structural_key()

    # ── 子类必须实现的接口 ──

    def resolve(self, *args, **kwargs) -> 'FactorExpr':
        """将 ParamRef → 对应的 ConstExpr 或 ColumnRef（取决于参数值类型）。"""
        return self

    def evaluate(self, *args, **kwargs) -> pd.DataFrame:
        """求值：对给定品种集合和数据频率，计算因子值。"""
        cache = kwargs.get('cache', None)
        sk = self._structural_key()
        if self._is_intermediate and cache is not None and sk in cache:
            return cache[sk]
        result = self._evaluate(*args, **kwargs)
        if self._is_intermediate and cache is not None:
            cache[sk] = result
        return result
    
    def _evaluate(self, *args, **kwargs) -> pd.DataFrame:
        """求值：对给定品种集合和数据频率，计算因子值。"""
        raise NotImplementedError

    @property
    def op_name(self) -> str:
        """表达式操作名，用于生成别名和 LaTeX。"""
        raise NotImplementedError

    def _to_latex(self, subst: dict | None = None) -> str:
        """生成 LaTeX 数学表达式（内部，不做 intermediate 展开）。

        subst: structural_key → symbol 映射，用于将 intermediate 替换为符号。
        """
        raise NotImplementedError

    def iter_intermediate_nodes(self) -> 'Iterator[FactorExpr]':
        """遍历表达式树，按后序（子依赖在前）产出所有 _is_intermediate 节点。

        Yields:
            node: 每个唯一的 intermediate 节点（按 structural_key 去重）。
        """
        seen: set[tuple] = set()
        stack: List[FactorExpr] = [self]
        post: List[FactorExpr] = []

        while stack:
            node = stack.pop()
            sk = node._structural_key()
            if sk in seen:
                continue
            seen.add(sk)

            post.append(node)
            for opnd in reversed(list(getattr(node, '_operands', ()))):
                stack.append(opnd)

        # 后序遍历：子节点先产出
        for node in reversed(post):
            if node._is_intermediate:
                yield node

    def to_latex(self, final_name: str = 'X') -> str:
        """生成含 intermediate 分行定义的 LaTeX。

        当表达式树中存在 .as_intermediate() 标记节点时，输出:
                    \\begin{aligned}
            A_t &:= ... \\
            B_t &:= ... \\
            X_t &:= ...
                    \\end{aligned}
        其中 X_t 的定义中，已定义的 intermediate 用其符号替代。
        否则退化为 _to_latex()。
        """
        nodes = list(self.iter_intermediate_nodes())
        if not nodes:
            return self._to_latex()

        # 1) 为每个 intermediate 分配符号，生成定义行
        used: Set[str] = set()
        name_to_sk: Dict[str, tuple] = {}
        sk_to_sym: Dict[tuple, str] = {}   # structural_key → symbol
        lines: List[str] = []
        unnamed_idx = 1
        for node in nodes:
            if node._intermediate_name:
                sk = node._structural_key()
                prev_sk = name_to_sk.get(node._intermediate_name)
                if prev_sk is not None and prev_sk != sk:
                    raise ValueError(
                        f"Intermediate 名称冲突: {node._intermediate_name} 被用于不同表达式。"
                    )
                name_to_sk[node._intermediate_name] = sk
                raw = ''.join(ch if (ch.isalnum() or ch == '_') else '_' for ch in str(node._intermediate_name)).strip('_')
                base = raw or 'I'
            else:
                base = f"I{unnamed_idx}"
                unnamed_idx += 1
            sym = base
            i = 2
            while sym in used:
                sym = f"{base}_{i}"
                i += 1
            used.add(sym)
            latex_sym = f"\\mathrm{{{sym}}}"
            lines.append(f"{latex_sym}_t &:= {node._to_latex(subst=sk_to_sym)},")
            sk_to_sym[node._structural_key()] = latex_sym

        # 2) 最后一行 X_t，用符号映射递归生成
        raw = ''.join(ch if (ch.isalnum() or ch == '_') else '_' for ch in str(final_name)).strip('_')
        final_base = raw or 'X'
        final_sym = final_base
        i = 2
        while final_sym in used:
            final_sym = f"{final_base}_{i}"
            i += 1
        used.add(final_sym)

        # 递归遍历 self，遇到已映射的 intermediate 就用符号替代
        lines.append(f"{final_sym}_t &:= {self._to_latex(subst=sk_to_sym)}.")

        return "\\begin{aligned}\n" + " \\\\\n".join(lines) + "\n\\end{aligned}"

    def _get_alias(self) -> str:
        """生成唯一别名，用于 Factor 注册。"""
        raise NotImplementedError

    def _repr_head(self) -> str:
        """单个节点的展示名（不含子节点）。"""
        if hasattr(self, 'op'):
            return str(getattr(self, 'op'))
        if hasattr(self, 'column'):
            col = getattr(self, 'column')
            return f"ColumnRef[{getattr(col, 'name', col)}]"
        if hasattr(self, 'param'):
            param = getattr(self, 'param')
            return f"ParamRef[{getattr(param, 'alias', param)}]"
        if hasattr(self, 'value'):
            return f"Const[{getattr(self, 'value')!r}]"
        return type(self).__name__

    def __repr__(self) -> str:
        operands = list(getattr(self, '_operands', ()))
        head = self._repr_head()
        if not operands:
            return head
        return f"{head}({', '.join(repr(op) for op in operands)})"

    def tree_repr(self, indent: int = 2, _level: int = 0) -> str:
        """以树状格式打印表达式。"""
        pad = ' ' * (indent * _level)
        line = f"{pad}{self._repr_head()}"
        operands = list(getattr(self, '_operands', ()))
        if not operands:
            return line

        child_lines: List[str] = []
        for op in operands:
            if isinstance(op, FactorExpr):
                child_lines.append(op.tree_repr(indent=indent, _level=_level + 1))
            else:
                child_pad = ' ' * (indent * (_level + 1))
                child_lines.append(f"{child_pad}{op!r}")
        return '\n'.join([line, *child_lines])

    @property
    def is_leaf_ref(self) -> bool:
        """是否作为依赖追踪中的叶子引用节点。"""
        ops = getattr(self, '_operands', ())
        return len(list(ops)) == 0

    @property
    def dependencies(self) -> Set['FactorExpr']:
        """返回此节点依赖的叶子表达式集合（不含自身与 ConstExpr）。"""
        deps = {
            d for d in self.get_ref_types(FactorExpr, leaf_only=True)
            if not isinstance(d, ConstExpr)
        }
        deps.discard(self)
        return deps

    @property
    def param_deps(self) -> Set['Parameter']:
        """返回此节点依赖的参数集合。"""
        params: Set['Parameter'] = set()
        for ref in self.get_ref_types(ParamRef):
            params.add(ref.param)
        return params

    @property
    def ordered_param_deps(self) -> List['Parameter']:
        params = list(self.param_deps)
        params.sort(key=lambda p: (type(p).__name__, p.alias))
        return params
    
    def get_ref_types(self, typ: type, leaf_only: bool = False) -> Set[Any]:
        """收集表达式树中的所有指定类型的引用节点。"""
        result: Set[Any] = set()
        seen: set[tuple] = set()  # 用 structural_key 去重
        stack: list[FactorExpr] = [self]

        while stack:
            node = stack.pop()
            sk = node._structural_key()
            if sk in seen:
                continue
            seen.add(sk)
            ops = getattr(node, '_operands', [])
            ops_list = list(ops)
            is_leaf = node.is_leaf_ref

            if isinstance(node, typ) and (not leaf_only or is_leaf):
                result.add(node)
            for op in reversed(ops_list):
                stack.append(op)

        return result

    @property
    def column_refs(self) -> Set['ColumnRef']:
        """收集表达式树中的所有 ColumnRef 叶子节点。"""
        return self.get_ref_types(ColumnRef)

    @property
    def const_refs(self) -> Set['ConstExpr']:
        """收集表达式树中的所有 ConstExpr 叶子节点"""
        return self.get_ref_types(ConstExpr)

    # ── 运算符重载：自动构建 CompositeExpr ──

    def __add__(self, other: Any) -> 'FactorExpr':
        return CompositeExpr('add', self, _to_expr(other))

    def __radd__(self, other: Any) -> 'FactorExpr':
        return CompositeExpr('add', _to_expr(other), self)

    def __sub__(self, other: Any) -> 'FactorExpr':
        return CompositeExpr('sub', self, _to_expr(other))

    def __rsub__(self, other: Any) -> 'FactorExpr':
        return CompositeExpr('sub', _to_expr(other), self)

    def __mul__(self, other: Any) -> 'FactorExpr':
        return CompositeExpr('mul', self, _to_expr(other))

    def __rmul__(self, other: Any) -> 'FactorExpr':
        return CompositeExpr('mul', _to_expr(other), self)

    def __truediv__(self, other: Any) -> 'FactorExpr':
        return CompositeExpr('div', self, _to_expr(other))

    def __rtruediv__(self, other: Any) -> 'FactorExpr':
        return CompositeExpr('div', _to_expr(other), self)

    def __neg__(self) -> 'FactorExpr':
        return CompositeExpr('neg', self)

    def __pos__(self) -> 'FactorExpr':
        return self

    def __abs__(self) -> 'FactorExpr':
        return CompositeExpr('abs', self)

    def __gt__(self, other: Any) -> 'FactorExpr':
        return CompositeExpr('gt', self, _to_expr(other))

    def __lt__(self, other: Any) -> 'FactorExpr':
        return CompositeExpr('lt', self, _to_expr(other))

    def __ge__(self, other: Any) -> 'FactorExpr':
        return CompositeExpr('ge', self, _to_expr(other))

    def __le__(self, other: Any) -> 'FactorExpr':
        return CompositeExpr('le', self, _to_expr(other))

    def __eq__(self, other: Any) -> 'FactorExpr':  # type: ignore[override]
        return CompositeExpr('eq', self, _to_expr(other))

    def __ne__(self, other: Any) -> 'FactorExpr':  # type: ignore[override]
        return CompositeExpr('ne', self, _to_expr(other))

    def __and__(self, other: Any) -> 'FactorExpr':
        return CompositeExpr('and', self, _to_expr(other))

    def __or__(self, other: Any) -> 'FactorExpr':
        return CompositeExpr('or', self, _to_expr(other))

    def __invert__(self) -> 'FactorExpr':
        return CompositeExpr('not', self)

    def __pow__(self, other: Any) -> 'FactorExpr':
        """幂运算：self ** other。"""
        return CompositeExpr('pow', self, _to_expr(other))

    def max(self, other: Any) -> 'FactorExpr':
        """逐元素最大值：max(self, other)。"""
        return CompositeExpr('bimax', self, _to_expr(other))

    def min(self, other: Any) -> 'FactorExpr':
        """逐元素最小值：min(self, other)。"""
        return CompositeExpr('bimin', self, _to_expr(other))

    # ── 便利方法：时序算子 ──

    def rolling_mean(self, window: Union[int, str, pd.Timedelta]) -> 'RollingOp':
        """N 期移动平均（简单平均）。"""
        return RollingOp('rolling_mean', _to_expr(window), self)

    def rolling_std(self, window: Union[int, str, pd.Timedelta]) -> 'RollingOp':
        """N 期移动标准差。"""
        return RollingOp('rolling_std', _to_expr(window), self)

    def rolling_var(self, window: Union[int, str, pd.Timedelta]) -> 'RollingOp':
        """N 期移动方差。"""
        return RollingOp('rolling_var', _to_expr(window), self)

    def rolling_min(self, window: Union[int, str, pd.Timedelta]) -> 'RollingOp':
        """N 期滚动最小值。"""
        return RollingOp('rolling_min', _to_expr(window), self)

    def rolling_max(self, window: Union[int, str, pd.Timedelta]) -> 'RollingOp':
        """N 期滚动最大值。"""
        return RollingOp('rolling_max', _to_expr(window), self)

    def rolling_sum(self, window: Union[int, str, pd.Timedelta]) -> 'RollingOp':
        """N 期滚动求和。"""
        return RollingOp('rolling_sum', _to_expr(window), self)

    def rolling_ema(self, window: Union[int, str, pd.Timedelta]) -> 'RollingOp':
        """N 期指数移动平均（EMA, span=window）。"""
        return RollingOp('rolling_ema', _to_expr(window), self)

    def rolling_corr(self, other: 'FactorExpr', window: Union[int, str, pd.Timedelta]) -> 'RollingOp':
        """N 期滚动相关系数：self 与 other 的 rolling correlation。"""
        return RollingOp('rolling_corr', _to_expr(window), self, other)

    def rolling_skew(self, window: Union[int, str, pd.Timedelta]) -> 'RollingOp':
        """N 期滚动偏度。"""
        return RollingOp('rolling_skew', _to_expr(window), self)

    def rolling_argmax(self, window: Union[int, str, pd.Timedelta]) -> 'RollingOp':
        """N 期内最大值出现位置（0=最早, 1=最新），归一化到 [0,1]。"""
        return RollingOp('rolling_argmax', _to_expr(window), self)

    def rolling_argmin(self, window: Union[int, str, pd.Timedelta]) -> 'RollingOp':
        """N 期内最小值出现位置（0=最早, 1=最新），归一化到 [0,1]。"""
        return RollingOp('rolling_argmin', _to_expr(window), self)

    def shift(self, periods: Union[int, str, pd.Timedelta, 'Parameter'] = 1) -> 'ShiftOp':
        """前 N 期值：x.shift(1) 即昨天值。"""
        return ShiftOp('shift', periods, self)

    def delta(self, period: Union[int, str, pd.Timedelta, 'Parameter'] = 1) -> 'FactorExpr':
        """N 期变化量：self - self.shift(N)。"""
        return self - self.shift(period)

    def log(self) -> 'FactorExpr':
        """自然对数。"""
        return CompositeExpr('log', self)

    def sign(self) -> 'FactorExpr':
        """符号函数：+1, -1, 0。"""
        return CompositeExpr('sign', self)

    def abs(self) -> 'FactorExpr':
        """绝对值。"""
        return CompositeExpr('abs', self)

    def sqrt(self) -> 'FactorExpr':
        """平方根。"""
        return CompositeExpr('sqrt', self)

    def neg(self) -> 'FactorExpr':
        """取负。"""
        return CompositeExpr('neg', self)

    # ── 便利方法：横截面算子 ──

    def cs_zscore(self) -> 'CrossSectionalOp':
        """横截面 z-score 标准化（逐时间点）。"""
        return CrossSectionalOp('cs_zscore', self)

    def cs_rank(self) -> 'CrossSectionalOp':
        """横截面排名（从小到大，0~1 归一化）。"""
        return CrossSectionalOp('cs_rank', self)

    def cs_spearman(self, other: 'FactorExpr') -> 'CrossSectionalOp':
        """截面 Spearman 秩相关系数：self 与 other 逐时间点计算。"""
        return CrossSectionalOp('cs_spearman', self, other)


# ═════════════════════════════════════════════════════════════════════════════
# Layer 1.5: 多元算子基类
# ═════════════════════════════════════════════════════════════════════════════

class OperandExpr(FactorExpr):
    """
    多元算子基类 — 所有含有子表达式的节点继承此类。

    核心设计：
      - __init__(op, *operands) 存储操作名和子表达式元组
      - _operands 属性自动从 self.operands 派生
      - evaluate() 递归求值所有子表达式 → 调用 _apply_op(values)
      - 子类只需覆盖 _apply_op() 和展示方法（op_name/to_latex/_get_alias）

    dependencies / param_deps 均复用 FactorExpr 基类的树遍历实现。
    """

    def __init__(self, op: str, *operands: 'FactorExpr'):
        self.op = op
        self.operands: Tuple[FactorExpr, ...] = operands

    @property
    def _operands(self) -> Sequence['FactorExpr']:
        return self.operands

    def resolve(self, *args, **kwargs) -> 'FactorExpr':
        resolved_operands = [opnd.resolve(*args, **kwargs) for opnd in self._operands]
        resolved = type(self)(self.op, *resolved_operands)
        if self._is_intermediate:
            resolved = resolved.as_intermediate(self._intermediate_name, factor=kwargs.get('caller', None))
        return resolved

    # ── 通用求值 ──

    def _evaluate(self, *args, **kwargs) -> pd.DataFrame:
        values = [opnd.evaluate(*args, **kwargs) for opnd in self.operands]
        return self._apply_op(values)

    def _apply_op(self, values: List[Any]) -> pd.DataFrame:
        """子类覆盖：对已求值的 operands DataFrame 执行核心运算。"""
        raise NotImplementedError

    # ── 展示方法 ──

    @property
    def op_name(self) -> str:
        return self.op.upper()

    def _to_latex(self, subst: dict | None = None) -> str:
        sk = self._structural_key()
        if subst is not None and sk in subst:
            return f"{subst[sk]}_t"
        parts = [opnd._to_latex(subst) for opnd in self.operands]
        return f'\\text{{{self.op}}}({", ".join(parts)})'

    def _get_alias(self) -> str:
        parts = [opnd._get_alias() for opnd in self.operands]
        return f"{self.op.upper()}_{'_'.join(parts)}"

    # ── 结构等价（FactorData 去重 key） ──

    def _structural_key(self) -> tuple:
        """
        OperandExpr 的结构 key。

        子类可通过覆盖 _structural_extra() 添加 op 之外的结构信息
        （如 RollingOp 需要 window, ShiftOp 需要 periods）。

        对称运算（add, mul, max, min, and, or, eq, ne,
        cs_spearman, cs_corr, cs_cov）的 operands 排序后取 key，
        保证 a+b ≡ b+a, max(a,b,c) ≡ max(c,a,b) 等。
        """
        type_tag = type(self).__name__
        op_tag = self.op
        op_keys_raw = [opnd._structural_key() for opnd in self._operands]
        if op_tag in FactorExpr._SYMMETRIC_OPS:
            op_keys = tuple(sorted(op_keys_raw, key=str))
        else:
            op_keys = tuple(op_keys_raw)
        extra = self._structural_extra()
        return (type_tag, op_tag, op_keys) + extra

    def _structural_extra(self) -> tuple:
        """子类覆盖：返回除 op + operands 外的额外结构信息。"""
        return ()


# ═════════════════════════════════════════════════════════════════════════════
# Layer 2: 叶子节点
# ═════════════════════════════════════════════════════════════════════════════

class ColumnRef(FactorExpr):
    """
    数据列引用 — 表达式树的叶子节点。

    示例：
        close = ColumnRef(DataColumn.CLOSE_ADJUSTED)
        high  = ColumnRef(DataColumn.HIGH_ADJUSTED)
        vol   = ColumnRef(DataColumn.VOLUME)

    运行时通过 product.{freq} 获取数据，source 参数选择数据源。
    """

    def __init__(self, column: DataColumn):
        self.column = column

    @property
    def is_leaf_ref(self) -> bool:
        return True

    @property
    def required_columns(self) -> Set[str]:
        """此列引用所需的数据列名（用于校验数据源是否兼容）。"""
        return {self.column.name, self.column.value}

    def _select_source(self, product: 'Product', freq: DataFreq,
                       source: Optional['DataSource'] = None) -> Optional['DataSource']:
        """
        为给定品种选择数据源。返回 None 表示无需指定（DataMeta 使用自己的加载逻辑）。

        - 若 source 已指定：校验该品种在此 source+freq 下是否有数据
        - 若未指定：遍历 DataSource 找到第一个可用且包含所需列的源
        - 若无注册的数据源：返回 None，由 DataMeta 自行加载
        """
        from tools.data.DataSource import DataSource as DS

        if source is not None and source.freq == freq and product in source:
            return source
        
        available_sources = getattr(product, freq.name).list_available_sources()
        if available_sources:
            return available_sources[0]
        else:
            return None

    def _evaluate(self, products: Sequence['Product'], freq: DataFreq,
                 source: Optional['DataSource'] = None,
                 cache: Optional[Dict[FactorExpr, pd.DataFrame]] = None,
                 preloaded: Optional[Dict[Any, pd.DataFrame]] = None, *args, **kwargs) -> pd.DataFrame:

        from tools.data.DataMeta import DataMeta

        series_dict = {}
        for p in products:
            # 优先使用预加载数据
            if preloaded is not None:
                preload_key = (p, freq.name)
                preloaded_df = preloaded.get(preload_key)
                if preloaded_df is not None and self.column.name in preloaded_df.columns:
                    series_dict[p] = preloaded_df[self.column.name]
                    continue
                if preloaded_df is not None:
                    from tools.data.DataMeta import DataMeta
                    raw_col = DataMeta._get_nonadjusted_col_name(self.column.name)
                    if DataMeta._check_is_adjusted(self.column.name) and raw_col in preloaded_df.columns:
                        series_dict[p] = preloaded_df[raw_col]
                        continue

            dm: DataMeta = getattr(p, freq.name)
            if source is not None:
                try:
                    ds = dm.set_current_source(source)
                except ValueError as e:
                    raise Warning(f"ColumnRef: source {source.alias} is not compatible with product {p.name} at freq {freq.name}") from e
            if dm.next_available_source() is None:
                continue  # 无可用数据源，跳过此品种
            col_name = self.column.name   # 如 'CLOSE_ADJUSTED' for CA

            # 使用 get_and_adjust_cols 确保复权列（如 CLOSE_ADJUSTED）被自动计算
            data = dm.get_and_adjust_cols([col_name], copy=False)
            if data.empty:
                continue
            series_dict[p] = data[col_name]

        result = pd.concat(series_dict, axis=1)
        result.columns = list(series_dict.keys())

        return result

    @property
    def op_name(self) -> str:
        return self.column.value

    def _to_latex(self, subst: dict | None = None) -> str:
        sk = self._structural_key()
        if subst is not None and sk in subst:
            return f"{subst[sk]}_t"
        col_to_latex = {
            'O': 'O_t', 'H': 'H_t', 'L': 'L_t', 'C': 'C_t',
            'OA': '\\tilde{O}_t', 'HA': '\\tilde{H}_t',
            'LA': '\\tilde{L}_t', 'CA': '\\tilde{C}_t',
            'V': 'V_t', 'OI': 'OI_t',
        }
        return col_to_latex.get(self.column.value) or self.column.value

    def _get_alias(self) -> str:
        return self.column.value

    def _structural_key(self) -> tuple:
        return ('ColumnRef', self.column)

class ParamRef(FactorExpr):
    """
    参数引用 — 表达式树的叶子节点，运行时从 FactorFamily 注册表取参数值。

    示例：
        window_param = WindowParam('W', 5)            # 2. WindowParam 来自 tools/parameters
        close_ma = ColumnRef(DataColumn.CLOSE_ADJUSTED).rolling_mean(window_param)

        # 等价于：close_ma = CLOSE.rolling_mean(5)，但窗口长度由外部参数化

    支持的类型：
      - DataColumnParam: 值会被 rectify 为 DataColumn 后用于列查找
      - WindowParam: 值作为窗口参数传入 RollingOp
      - 任意 Parameter: 值直接作为标量参与表达式计算
    """

    def __init__(self, param: 'Parameter'):
        self.param = param

    @property
    def is_leaf_ref(self) -> bool:
        return True

    def _evaluate(self, *args, **kwargs) -> pd.DataFrame:
        raise RuntimeError("ParamRef._evaluate() 不得调用; 请先调用 resolve(param_values) 将 ParamRef 转为 ConstExpr/ColumnRef 后再求值")

    def resolve(self, param_values: dict | None = None, *args, **kwargs) -> FactorExpr:
        """从宿主对象的注册表中取出当前参数值。若提供 param_values 则优先从中查找。"""
        from tools.parameters import DataColumnParam, FactorParam
        from tools.factors import Factor
        factor: Optional['Factor'] = None

        if param_values is not None and self.param.alias in param_values:
            value = param_values[self.param.alias]
        else:
            value = self.param.default_value
        if isinstance(self.param, DataColumnParam):
            resolved: FactorExpr = ColumnRef(DataColumn(value))
        elif isinstance(self.param, FactorParam):
            value = self.param._value_space.rectify(value)
            if value is None:
                resolved = ConstExpr(None)
            else:
                if isinstance(value, (str, dict)):
                    try:
                        from server.modules.shared.factor_param_resolver import resolve_factor_param_value
                        value = resolve_factor_param_value(value)
                    except Exception as exc:
                        raise TypeError(f"参数 {self.param.alias} 无法解析为因子: {value}") from exc
                if isinstance(value, Factor):
                    resolved = value._func_expr
                    factor = value
                else:
                    resolved = value
                if not isinstance(resolved, FactorExpr):
                    raise TypeError(f"参数 {self.param.alias} 需要 FactorExpr，收到 {type(value).__name__}")
                resolved = resolved.resolve(param_values=param_values, *args, **kwargs)
        else:
            resolved = ConstExpr(value)

        if self._is_intermediate:
            resolved = resolved.as_intermediate(self._intermediate_name, factor=factor)
        return resolved

    @property
    def op_name(self) -> str:
        return f"${{{self.param.alias}}}"

    def _to_latex(self, subst: dict | None = None) -> str:
        """LaTeX 变量名。ParamRef 的参数名作为基础变量，如 'P' → P_t。"""
        sk = self._structural_key()
        if subst is not None and sk in subst:
            return f"{subst[sk]}_t"
        param_latex = f"\\textcolor{{red}}{{{self.param.alias}}}"
        from tools.parameters import DataColumnParam, FactorParam
        if isinstance(self.param, (DataColumnParam, FactorParam)):
            return f"{param_latex}_{{t}}"
        return param_latex

    def _get_alias(self) -> str:
        return f"P{self.param.alias}"

    def _structural_key(self) -> tuple:
        return ('ParamRef', self.param.alias)

class ConstExpr(FactorExpr):
    """
    常量表达式 — 标量、固定值或窗口/位移参数的叶子节点。

    当 value 是 int/float/ndarray 时 → 参与表达式运算，evaluate() 返回 self
    （由 CompositeExpr._apply_op 提取 .value 后内联处理）。

    当 value 是 pd.Timedelta/DataFreq 时 → 窗口/位移参数，
    evaluate() 直接返回 bar 数（int）。
    """

    def __init__(self, value: Any):
        self.value = value

    @property
    def is_leaf_ref(self) -> bool:
        return True

    def _evaluate(self, **kwargs) -> Any:
        return self.value

    @property
    def op_name(self) -> str:
        return f"const({self.value})"

    def _to_latex(self, subst: dict | None = None) -> str:
        sk = self._structural_key()
        if subst is not None and sk in subst:
            return f"{subst[sk]}_t"
        return str(self.value)

    def _get_alias(self) -> str:
        v = self.value
        if isinstance(v, (int, float)):
            return str(v).replace('.', 'd').replace('-', 'N')
        return 'const'

    def _structural_key(self) -> tuple:
        v = self.value
        if isinstance(v, np.ndarray):
            return ('ConstExpr', v.tobytes())
        return ('ConstExpr', v)


# ═════════════════════════════════════════════════════════════════════════════
# 辅助：将标量/ndarray 转为 ConstExpr
# ═════════════════════════════════════════════════════════════════════════════

def _to_expr(value: Any) -> FactorExpr:
    """将非 FactorExpr 值包装为 ConstExpr，将 Parameter 转为 ParamRef。"""
    if isinstance(value, FactorExpr):
        return value
    from tools.parameters.Parameter import Parameter
    if isinstance(value, Parameter):
        return ParamRef(value)
    return ConstExpr(value)  # type: ignore[arg-type]


# ═════════════════════════════════════════════════════════════════════════════
# Layer 4: 滚动窗口算子
# ═════════════════════════════════════════════════════════════════════════════

class RollingOp(OperandExpr):
    """
    滚动窗口算子抽象基类。

    operands = (window, data1, data2, ...)
    window 是第一 operand（ConstExpr 或 ParamRef），数据 operands 紧随其后。

    子类只需声明操作数和核心滚动运算逻辑。
    """

    @property
    def window(self) -> 'FactorExpr':
        """第一 operand：窗口参数。"""
        return self.operands[0]

    # ── 算子映射：op → lambda(*series_or_dfs, window) ──

    _OP_MAP = {
        'rolling_mean': lambda s, w: s.rolling(w, min_periods=max(1, w // 2)).mean(),
        'rolling_std':  lambda s, w: s.rolling(w, min_periods=max(1, w // 2)).std(),
        'rolling_var':  lambda s, w: s.rolling(w, min_periods=max(1, w // 2)).var(),
        'rolling_min':  lambda s, w: s.rolling(w, min_periods=1).min(),
        'rolling_max':  lambda s, w: s.rolling(w, min_periods=1).max(),
        'rolling_sum':  lambda s, w: s.rolling(w, min_periods=1).sum(),
        'rolling_ema':  lambda s, w: s.ewm(span=w, min_periods=max(1, w // 2)).mean(),
        'rolling_skew': lambda s, w: s.rolling(w, min_periods=max(1, w // 2)).skew(),
    }

    def _apply_rolling(self, window: int, *dfs: pd.DataFrame,
                       freq: DataFreq) -> pd.DataFrame:
        # argmax/argmin：全向量化，不依赖 rolling()
        if self.op in ('rolling_argmax', 'rolling_argmin'):
            return _rolling_argmaxmin(dfs[0], window, self.op)

        if self.op in self._OP_MAP:
            func = self._OP_MAP[self.op]
            return dfs[0].apply(func, axis=0, args=(window,))

        # 二元
        if self.op in ('rolling_corr', 'rolling_cov'):
            left_df, right_df = dfs
            result = pd.DataFrame(index=left_df.index, columns=left_df.columns, dtype=float)
            for col in left_df.columns:
                if self.op == 'rolling_corr':
                    result[col] = left_df[col].rolling(window).corr(right_df[col])
                else:
                    result[col] = left_df[col].rolling(window).cov(right_df[col])
            return result

        raise ValueError(f"Unknown rolling op: {self.op}")

    # ── 展示方法 ──

    @property
    def operand(self) -> FactorExpr:
        """数据操作数（向后兼容，一元时使用）。"""
        return self.operands[1]

    @property
    def op_name(self) -> str:
        p = self.window
        label = str(p.value) if isinstance(p, ConstExpr) else str(p)
        return f"{self.op.upper()}_{label}"

    def _to_latex(self, subst: dict | None = None) -> str:
        sk = self._structural_key()
        if subst is not None and sk in subst:
            return f"{subst[sk]}_t"
        w_str = self.window._to_latex(subst) if isinstance(self.window, FactorExpr) else str(self.window)
        if len(self.operands) == 2:
            # 一元
            operand_latex = self.operands[1]._to_latex(subst)
            _LATEX_MAP = {
                'rolling_mean': f'\\text{{RMean}}_{{{w_str}}}\\left({operand_latex}\\right)',
                'rolling_std': f'\\text{{RStd}}_{{{w_str}}}\\left({operand_latex}\\right)',
                'rolling_var': f'\\text{{RVar}}_{{{w_str}}}\\left({operand_latex}\\right)',
                'rolling_min': f'\\text{{RMin}}_{{{w_str}}}\\left({operand_latex}\\right)',
                'rolling_max': f'\\text{{RMax}}_{{{w_str}}}\\left({operand_latex}\\right)',
                'rolling_sum': f'\\text{{RSum}}_{{{w_str}}}\\left({operand_latex}\\right)',
                'rolling_ema': f'\\text{{REMA}}_{{{w_str}}}\\left({operand_latex}\\right)',
                'rolling_skew': f'\\text{{RSkew}}_{{{w_str}}}\\left({operand_latex}\\right)',
                'rolling_argmax': f'\\text{{RArgMax}}_{{{w_str}}}\\left({operand_latex}\\right)',
                'rolling_argmin': f'\\text{{RArgMin}}_{{{w_str}}}\\left({operand_latex}\\right)',
            }
            return _LATEX_MAP.get(self.op, f'{self.op}_{{{w_str}}}\\left({operand_latex}\\right)')
        else:
            left_latex = self.operands[1]._to_latex(subst)
            right_latex = self.operands[2]._to_latex(subst)
            return f'\\text{{{self.op.capitalize()}}}_{{{w_str}}}\\left({left_latex}, {right_latex}\\right)'

    def _get_alias(self) -> str:
        parts = [self.op]
        for opnd in self.operands[1:]:
            parts.append(opnd._get_alias())
        p_expr = self.window
        p = str(p_expr.value) if isinstance(p_expr, ConstExpr) else str(p_expr).replace(' ', '')
        parts.append(p)
        return "_".join(parts)

    def _evaluate(self, products: Sequence['Product'], freq: DataFreq,
                 source: Optional['DataSource'] = None,
                 cache: Optional[Dict['FactorExpr', pd.DataFrame]] = None,
                 preloaded: Optional[Dict[Any, pd.DataFrame]] = None, *args, **kwargs) -> pd.DataFrame:

        # 先求值数据 operands（非 window）
        data_vals = [opnd.evaluate(products=products, freq=freq, source=source,
                       cache=cache, preloaded=preloaded)
                     for opnd in self.operands[1:]]
        
        periods_expr = self.operands[0]
        if not isinstance(periods_expr, ConstExpr):
            periods_val = periods_expr.evaluate(products=products, freq=freq, source=source, cache=cache, preloaded=preloaded)
            assert isinstance(periods_val, ConstExpr)
            periods_val = periods_val.value
        else:
            periods_val = periods_expr.value
        common, common_periods, product_periods = _resolve_windows(window=periods_val, freq=freq, products=[p for p in products if p in data_vals[0].columns])
        if common:
            result = self._apply_rolling(common_periods, *data_vals, freq=freq)  # type: ignore[arg-type]
        else:
            # 按照有相同的 periods 的产品分组，分别 shift 后再合并
            unique_periods = set(product_periods.values())
            periods_products_map = {p: [product for product, period in product_periods.items() if period == p] for p in unique_periods}
            result_parts = []
            for p, products_group in periods_products_map.items():
                result_parts.append(self._apply_rolling(p, *[dv[products_group] for dv in data_vals], freq=freq))  # type: ignore[arg-type]
            result = pd.concat(result_parts, axis=1)

        return result

class ShiftOp(OperandExpr):
    """
    位移算子：SHIFT(periods, x) 即前 N 期的 x 值。

    operands = (periods, operand)
    periods 是第一 operand（ConstExpr 或 ParamRef），operand 是第二 operand。
    """

    def __init__(self, op: str, periods: Union[int, str, pd.Timedelta, 'Parameter', 'FactorExpr'],
                 operand: 'FactorExpr'):
        super().__init__(op, _to_expr(periods), operand)

    @property
    def periods(self) -> 'FactorExpr':
        return self.operands[0]

    @property
    def operand(self) -> 'FactorExpr':
        return self.operands[1]

    # ── evaluate：覆盖 OperandExpr 默认实现 ──

    def _evaluate(self, products: Sequence['Product'], freq: DataFreq,
                 source: Optional['DataSource'] = None,
                 cache: Optional[Dict[FactorExpr, pd.DataFrame]] = None,
                 preloaded: Optional[Dict[Any, pd.DataFrame]] = None, *args, **kwargs) -> pd.DataFrame:

        # 先求 operand（DataFrame）
        operand_val = self.operands[1].evaluate(products=products, freq=freq, source=source,
                            cache=cache, preloaded=preloaded)

        periods_expr = self.operands[0]
        if not isinstance(periods_expr, ConstExpr):
            periods_val = periods_expr.evaluate(products=products, freq=freq, source=source, cache=cache, preloaded=preloaded)
        else:
            periods_val = periods_expr.value
        common, common_periods, product_periods = _resolve_windows(window=periods_val, freq=freq, products=[p for p in products if p in operand_val.columns])
        if common:
            result = operand_val.shift(int(common_periods))
        else:
            # 按照有相同的 periods 的产品分组，分别 shift 后再合并
            unique_periods = set(product_periods.values())
            periods_products_map = {p: [product for product, period in product_periods.items() if period == p] for p in unique_periods}
            result_parts = []
            for p, products_group in periods_products_map.items():
                result_parts.append(operand_val[products_group].shift(int(p)))
            result = pd.concat(result_parts, axis=1)

        return result

    # ── 展示方法 ──

    @property
    def op_name(self) -> str:
        p = self.periods
        label = str(p.value) if isinstance(p, ConstExpr) else str(p)
        return f"SHIFT_{label}"

    def _to_latex(self, subst: dict | None = None) -> str:
        sk = self._structural_key()
        if subst is not None and sk in subst:
            return f"{subst[sk]}_t"
        operand_latex = self.operand._to_latex(subst)
        operand_base = _strip_latex_time_subscript(operand_latex)
        if _is_zero_shift_period(self.periods):
            return f"{operand_base}_{{t}}"
        p_label = self.periods._to_latex(subst) if isinstance(self.periods, FactorExpr) else str(self.periods)
        return f"{operand_base}_{{t - {p_label}}}"

    def _get_alias(self) -> str:
        p_expr = self.periods
        p = str(p_expr.value) if isinstance(p_expr, ConstExpr) else str(p_expr).replace(' ', '')
        return f"shift_{self.operand._get_alias()}_{p}"


def _is_zero_shift_period(periods: 'FactorExpr') -> bool:
    if not isinstance(periods, ConstExpr):
        return False
    value = periods.value
    if value == 0:
        return True
    try:
        return pd.Timedelta(value) == pd.Timedelta(0)
    except Exception:
        return False


def _strip_latex_time_subscript(latex: str) -> str:
    suffix = '_{t}'
    return latex[:-len(suffix)] if latex.endswith(suffix) else latex


def _rolling_argmaxmin(
    df: pd.DataFrame,
    window: int,
    op: str,
    normalize: bool = True,
) -> pd.DataFrame:
    """用 sliding_window_view 对 DataFrame 每列计算滚动 argmax 或 argmin。"""
    if window < 2:
        raise ValueError(f"window must be >= 2, got {window}")

    n_rows = len(df)
    if n_rows < window:
        return pd.DataFrame(np.full((n_rows, df.shape[1]), np.nan),
                            index=df.index, columns=df.columns)

    arr = df.to_numpy(dtype=float)
    windows = np.lib.stride_tricks.sliding_window_view(arr, window, axis=0)
    reversed_view = windows[..., ::-1]
    if op == 'rolling_argmax':
        pos = (window - 1) - np.argmax(reversed_view, axis=-1)
    elif op == 'rolling_argmin':
        pos = (window - 1) - np.argmin(reversed_view, axis=-1)
    else:
        raise ValueError(f"Invalid op: {op}")

    pos = pos.astype(float)
    if normalize and window > 1:
        pos = pos / (window - 1)

    nan_rows = np.full((window - 1, df.shape[1]), np.nan)
    result = np.vstack([nan_rows, pos])
    return pd.DataFrame(result, index=df.index, columns=df.columns)

def _resolve_windows(window: Any, freq: Any, products: Sequence[Product]) -> Tuple[bool, int, Dict[Product, int]]:
    """将 DataFreq 类型的窗口参数转为 bar 数量（整数）。"""
    if isinstance(window, int):
        return True, window, {}
    window = DataFreq(window)
    freq = DataFreq(freq)
    days = window.days
    freq_subday_sec = freq.subday.total_seconds()
    if freq_subday_sec == 0:
        subday_periods = 0
    else:
        subday_periods = int(window.subday.total_seconds() / freq_subday_sec)
    if days == 0:
        return True, subday_periods, {}
    else:
        product_periods = {product: int(subday_periods + days * getattr(product, freq.name).day_periods) for product in products}
        if product_periods.values() and len(set(product_periods.values())) == 1:
            return True, next(iter(product_periods.values())), {}
        return False, 0, product_periods


# ═════════════════════════════════════════════════════════════════════════════
# Layer 5: 横截面算子
# ═════════════════════════════════════════════════════════════════════════════

class CrossSectionalOp(OperandExpr):
    """
    一元横截面算子：CS_ZSCORE, CS_RANK 等。

    在每个时间点对横截面（所有品种）进行聚合计算。
    """

    def __init__(self, op: str, *operands: FactorExpr):
        super().__init__(op, *operands)

    @property
    def operand(self) -> FactorExpr:
        return self.operands[0]

    @property
    def left(self) -> FactorExpr:
        return self.operands[0]

    @property
    def right(self) -> FactorExpr:
        return self.operands[1]

    def _apply_op(self, values: List[Any]) -> pd.DataFrame:
        vals: List[Any] = []
        for i, val in enumerate(values):
            opnd = self.operands[i]
            vals.append(opnd.value if isinstance(opnd, ConstExpr) else val)

        if self.op == 'cs_spearman':
            left_df, right_df = vals[0], vals[1]
            if not isinstance(left_df, pd.DataFrame) or not isinstance(right_df, pd.DataFrame):
                raise TypeError(
                    f"cs_spearman 需要两个 DataFrame 输入，收到 "
                    f"{type(left_df).__name__} 与 {type(right_df).__name__}"
                )
            return self._apply_spearman(left_df, right_df)

        x = vals[0]
        if self.op == 'cs_zscore':
            mean = x.mean(axis=1)
            std = x.std(axis=1)
            std = std.replace(0, np.nan)
            return x.sub(mean, axis=0).div(std, axis=0)
        if self.op == 'cs_rank':
            return x.rank(axis=1, pct=True) - 0.5
        raise ValueError(f"Unknown cross-sectional op: {self.op}")

    @staticmethod
    def _apply_spearman(left_df: pd.DataFrame, right_df: pd.DataFrame) -> pd.DataFrame:
        common_idx = pd.Index(left_df.index).intersection(pd.Index(right_df.index))
        common_cols = left_df.columns.intersection(right_df.columns)

        if len(common_idx) == 0 or len(common_cols) == 0:
            empty_idx = pd.Index([], name=left_df.index.names[-1] if left_df.index.names else None)
            result = pd.DataFrame({'IC': []}, index=empty_idx)
            result.index.names = left_df.index.names
            return result

        l = left_df.loc[common_idx, common_cols]
        r = right_df.loc[common_idx, common_cols]

        # Spearman = Pearson(rank(x), rank(y)); 按行（横截面）一次性向量化计算。
        valid = l.notna() & r.notna()
        l_rank = l.where(valid).rank(axis=1, method='average', na_option='keep')
        r_rank = r.where(valid).rank(axis=1, method='average', na_option='keep')

        x = l_rank.to_numpy(dtype=float)
        y = r_rank.to_numpy(dtype=float)
        mask = ~np.isnan(x) & ~np.isnan(y)

        x_masked = np.where(mask, x, 0.0)
        y_masked = np.where(mask, y, 0.0)

        n = mask.sum(axis=1).astype(float)
        sum_x = x_masked.sum(axis=1)
        sum_y = y_masked.sum(axis=1)
        sum_x2 = (x_masked * x_masked).sum(axis=1)
        sum_y2 = (y_masked * y_masked).sum(axis=1)
        sum_xy = (x_masked * y_masked).sum(axis=1)

        num = n * sum_xy - sum_x * sum_y
        den = np.sqrt((n * sum_x2 - sum_x * sum_x) * (n * sum_y2 - sum_y * sum_y))

        with np.errstate(divide='ignore', invalid='ignore'):
            ic = num / den

        ic[(n <= 1) | (den <= 0)] = np.nan

        result = pd.DataFrame({'IC': ic}, index=l.index)
        result.index.names = left_df.index.names
        return result

    def _to_latex(self, subst: dict | None = None) -> str:
        sk = self._structural_key()
        if subst is not None and sk in subst:
            return f"{subst[sk]}_t"
        if self.op == 'cs_spearman':
            left_latex = self.left._to_latex(subst)
            right_latex = self.right._to_latex(subst)
            return f'\\rho_s({left_latex}, {right_latex})'

        operand_latex = self.operand._to_latex(subst)
        _LATEX_MAP = {
            'cs_zscore': f'Z({operand_latex})',
            'cs_rank': f'\\text{{Rank}}({operand_latex})',
        }
        return _LATEX_MAP.get(self.op, f'\\text{{{self.op}}}({operand_latex})')

    def _get_alias(self) -> str:
        if self.op == 'cs_spearman':
            return f"{self.op}_{self.left._get_alias()}_{self.right._get_alias()}"
        return f"{self.op}_{self.operand._get_alias()}"


# ═════════════════════════════════════════════════════════════════════════════
# Layer 6: 复合表达式（二元运算树节点）
# ═════════════════════════════════════════════════════════════════════════════

def _reduce_biop(op: str, args: tuple) -> Any:
    """从左到右依次用 _biOps[op] 折叠 args，正确处理 DataFrame+scalar 混合。"""
    result = args[0]
    bi_func = CompositeExpr._biOps[op]['func']
    for a in args[1:]:
        result = bi_func(result, a)
    return result


class CompositeExpr(OperandExpr):
    """
    复合表达式 — 元素级多元运算。

    支持：
      - add, sub, mul, div（算术）
      - gt, lt, ge, le, eq, ne（比较）
      - and, or（逻辑）
      - max, min, pow（多元聚合）
    - neg, abs, not, log, sign, sqrt（一元）
    """

    _biOps = {
        'bimax': {
            'symb': 'max',
            'latex': '\\max',
            'nop': 2,
            'func': lambda a, b: (
                np.maximum(a, b)
                if not isinstance(a, pd.DataFrame) and not isinstance(b, pd.DataFrame)
                else (
                    a.clip(lower=b)  # type: ignore[arg-type]
                    if isinstance(a, pd.DataFrame) and np.isscalar(b)
                    else (
                        b.clip(lower=a)  # type: ignore[arg-type]
                        if isinstance(b, pd.DataFrame) and np.isscalar(a)
                        else pd.DataFrame(
                            np.maximum(a.values, b.values),
                            index=a.index,
                            columns=a.columns,
                        )
                    )
                )
            ),
        },
        'bimin': {
            'symb': 'min',
            'latex': '\\min',
            'nop': 2,
            'func': lambda a, b: (
                np.minimum(a, b)
                if not isinstance(a, pd.DataFrame) and not isinstance(b, pd.DataFrame)
                else (
                    a.clip(upper=b)  # type: ignore[arg-type]
                    if isinstance(a, pd.DataFrame) and np.isscalar(b)
                    else (
                        b.clip(upper=a)  # type: ignore[arg-type]
                        if isinstance(b, pd.DataFrame) and np.isscalar(a)
                        else pd.DataFrame(
                            np.minimum(a.values, b.values),
                            index=a.index,
                            columns=a.columns,
                        )
                    )
                )
            ),
        },
    }

    _Ops = {
        'add': {'symb': '+', 'latex': '+', 'nop': 2, 'func': lambda a, b, *args: a + b},
        'sub': {'symb': '-', 'latex': '-', 'nop': 2, 'func': lambda a, b, *args: a - b},
        'mul': {'symb': '*', 'latex': '\\times', 'nop': 2, 'func': lambda a, b, *args: a * b},
        'div': {'symb': '/', 'latex': '\\frac', 'nop': 2, 'func': lambda a, b, *args: a / b},
        'gt': {'symb': '>', 'latex': '>', 'nop': 2, 'func': lambda a, b, *args: a > b},
        'lt': {'symb': '<', 'latex': '<', 'nop': 2, 'func': lambda a, b, *args: a < b},
        'ge': {'symb': '>=', 'latex': '\\ge', 'nop': 2, 'func': lambda a, b, *args: a >= b},
        'le': {'symb': '<=', 'latex': '\\le', 'nop': 2, 'func': lambda a, b, *args: a <= b},
        'eq': {'symb': '==', 'latex': '=', 'nop': 2, 'func': lambda a, b, *args: a == b},
        'ne': {'symb': '!=', 'latex': '\\neq', 'nop': 2, 'func': lambda a, b, *args: a != b},
        'and': {'symb': '&', 'latex': '\\wedge', 'nop': 2, 'func': lambda a, b, *args: a & b},
        'or': {'symb': '|', 'latex': '\\vee', 'nop': 2, 'func': lambda a, b, *args: a | b},
        'neg': {'symb': '-', 'latex': '-', 'nop': 1, 'func': lambda a, *args: -a},
        'abs': {'symb': 'abs', 'latex': '\\mathrm{abs}', 'nop': 1, 'func': lambda a, *args: abs(a)},
        'not': {'symb': '~', 'latex': '\\neg', 'nop': 1, 'func': lambda a, *args: ~a},
        'log': {'symb': 'log', 'latex': '\\log', 'nop': 1, 'func': lambda a, *args: np.log(a)},
        'sign': {'symb': 'sign', 'latex': '\\mathrm{sign}', 'nop': 1, 'func': lambda a, *args: np.sign(a)},
        'sqrt': {'symb': 'sqrt', 'latex': '\\sqrt', 'nop': 1, 'func': lambda a, *args: np.sqrt(a)},
        'pow': {'symb': '**', 'latex': '^', 'nop': 2, 'func': lambda a, b, *args: a ** b},
        'max': {'symb': 'max', 'latex': '\\max', 'nop': -1, 'func': lambda *args: _reduce_biop('bimax', args)},
        'min': {'symb': 'min', 'latex': '\\min', 'nop': -1, 'func': lambda *args: _reduce_biop('bimin', args)},
    }

    _LATEX_PRECEDENCE = {
        'or': 10,
        'and': 20,
        'gt': 30, 'lt': 30, 'ge': 30, 'le': 30, 'eq': 30, 'ne': 30,
        'add': 40, 'sub': 40,
        'mul': 50, 'div': 50,
        'pow': 60,
        'neg': 70, 'abs': 70, 'not': 70, 'log': 70, 'sign': 70, 'sqrt': 70,
        'max': 80, 'min': 80,
    }

    def __new__(cls, op: str, *operands: FactorExpr, **kwargs) -> 'FactorExpr':
        """表达式规范化：常量折叠 + 等价化简，在构造前归并。

        常量折叠：所有 operand 为 ConstExpr → 直接求值为 ConstExpr。
        等价化简：
          - neg(neg(a))         → a
          - neg(sub(a, b))      → sub(b, a)
          - add(a, Const(0))    → a
          - sub(a, Const(0))    → a
          - mul(a, Const(1))    → a
          - mul(a, Const(0))    → Const(0)
          - div(a, Const(1))    → a
          - pow(a, Const(1))    → a
          - pow(a, Const(0))    → Const(1)
          - sub(a, Const(c))    → add(a, Const(-c))
          - div(a, Const(c))    → mul(a, Const(1/c))
        """
        # ── 常量折叠 ──
        if operands and all(isinstance(opnd, ConstExpr) for opnd in operands):
            values = [cast(ConstExpr, opnd).value for opnd in operands]
            if op in cls._Ops:
                result = cls._Ops[op]['func'](*values)
                return ConstExpr(result)
            if op in cls._biOps:
                result = cls._biOps[op]['func'](*values)
                return ConstExpr(result)

        # ── 等价化简 ──
        if op == 'neg' and len(operands) == 1:
            inner = operands[0]
            if isinstance(inner, CompositeExpr):
                # neg(neg(a)) → a
                if inner.op == 'neg':
                    return inner.operands[0]
                # neg(sub(a, b)) → sub(b, a)
                if inner.op == 'sub':
                    return CompositeExpr('sub', inner.operands[1], inner.operands[0])

        # ── 身份消元 / 常量优化 ──
        if len(operands) == 2 and isinstance(operands[1], ConstExpr):
            c = cast(ConstExpr, operands[1]).value
            a = operands[0]
            if op == 'add' and c == 0:
                return a
            if op == 'sub' and c == 0:
                return a
            if op == 'mul':
                if c == 1:
                    return a
                if c == 0:
                    return ConstExpr(0)
            if op == 'div' and c == 1:
                return a
            if op == 'pow':
                if c == 1:
                    return a
                if c == 0:
                    return ConstExpr(1)

        # sub(a, Const(c)) → add(a, Const(-c))
        if op == 'sub' and len(operands) == 2:
            if isinstance(operands[1], ConstExpr):
                v = cast(ConstExpr, operands[1]).value
                try:
                    neg_v = -v
                    return cls.__new__(cls, 'add', operands[0], ConstExpr(neg_v))
                except (TypeError, ValueError):
                    pass

        # div(a, Const(c)) → mul(a, Const(1/c))
        if op == 'div' and len(operands) == 2:
            if isinstance(operands[1], ConstExpr):
                v = cast(ConstExpr, operands[1]).value
                try:
                    inv_v = 1.0 / v
                    return cls.__new__(cls, 'mul', operands[0], ConstExpr(inv_v))
                except (TypeError, ValueError, ZeroDivisionError):
                    pass

        return super().__new__(cls)

    def __init__(self, op: str, *operands: FactorExpr):
        super().__init__(op, *operands)

    def _apply_op(self, values: List[Any]) -> pd.DataFrame:
        """根据 op 类型执行实际运算（由 OperandExpr.evaluate 调用）。"""
        if self.op in self._biOps:
            return self._biOps[self.op]['func'](*values)
        if self.op in self._Ops:
            return self._Ops[self.op]['func'](*values)
        raise ValueError(f"Unknown op: {self.op}")

    @property
    def op_name(self) -> str:
        if self.op in self._biOps:
            return self._biOps[self.op]['symb']
        if self.op in self._Ops:
            return self._Ops[self.op]['symb']
        return self.op

    def _to_latex(self, subst: dict | None = None) -> str:
        sk = self._structural_key()
        if subst is not None and sk in subst:
            return f"{subst[sk]}_t"
        operands_latex = [opnd._to_latex(subst) for opnd in self.operands]
        if self.op in self._biOps:
            op_latex = self._biOps[self.op]['latex']
            return f'{op_latex}\\left({operands_latex[0]}, {operands_latex[1]}\\right)'
        if self.op in self._Ops:
            if self._Ops[self.op]['nop'] == 1:
                operand_latex = operands_latex[0]
                return f"{self._Ops[self.op]['latex']}\\left({operand_latex}\\right)"
            elif self._Ops[self.op]['nop'] == 2:
                left_latex = self._binary_operand_latex(self.operands[0], operands_latex[0], side='left', subst=subst)
                right_latex = self._binary_operand_latex(self.operands[1], operands_latex[1], side='right', subst=subst)
                if self.op in ('add', 'sub', 'mul', 'pow', 'gt', 'lt', 'ge', 'le', 'eq', 'ne', 'and', 'or'):
                    return f'{left_latex} {self._Ops[self.op]["latex"]} {right_latex}'
                elif self.op in ('div'):
                    return f'{self._Ops[self.op]["latex"]}{{{left_latex}}}{{{right_latex}}}'
                else:
                    return f'{self._Ops[self.op]["latex"]}\\left({left_latex}, {right_latex}\\right)'
            else:
                return f'{self._Ops[self.op]["latex"]}\\left({", ".join(operands_latex)}\\right)'
        else:
            return f'\\text{{{self.op.capitalize()}}}\\left({", ".join(operands_latex)}\\right)'

    @classmethod
    def _expr_precedence(cls, expr: FactorExpr) -> int:
        if not isinstance(expr, CompositeExpr):
            return 10_000
        return cls._LATEX_PRECEDENCE.get(expr.op, 0)

    def _needs_parenthesis(self, child: FactorExpr, side: str, subst: dict | None = None) -> bool:
        if not isinstance(child, CompositeExpr):
            return False
        if subst is not None and child._structural_key() in subst:
            return False
        if self.op == 'div':
            return False

        parent_prec = self._LATEX_PRECEDENCE.get(self.op, 0)
        child_prec = self._expr_precedence(child)

        if child_prec < parent_prec:
            return True
        if child_prec > parent_prec:
            return False

        # 同优先级时按算子特性处理，保证树结构语义不丢失。
        if self.op == 'sub' and side == 'right':
            return True
        if self.op == 'pow':
            return True
        if self.op == 'mul' and child.op == 'div':
            return True
        if self.op in ('gt', 'lt', 'ge', 'le', 'eq', 'ne', 'and', 'or'):
            return True
        return False

    def _binary_operand_latex(self, child: FactorExpr, child_latex: str, side: str, subst: dict | None = None) -> str:
        return f'\\left({child_latex}\\right)' if self._needs_parenthesis(child, side, subst=subst) else child_latex

    def _get_alias(self) -> str:
        op_aliases = {
            'add': 'ADD', 'sub': 'SUB', 'mul': 'MUL', 'div': 'DIV',
            'gt': 'GT', 'lt': 'LT', 'ge': 'GE', 'le': 'LE',
            'eq': 'EQ', 'ne': 'NE',
            'and': 'AND', 'or': 'OR',
            'neg': 'NEG', 'abs': 'ABS', 'not': 'NOT',
            'log': 'LOG', 'sign': 'SIGN', 'sqrt': 'SQRT',
            'bimax': 'MAX', 'bimin': 'MIN',
        }
        op_alias = op_aliases.get(self.op, self.op.upper())
        parts = [opnd._get_alias() for opnd in self.operands]
        return f"{op_alias}_{'_'.join(parts)}"


# ═════════════════════════════════════════════════════════════════════════════
# 顶层便利函数：max / min 多元聚合
# ═════════════════════════════════════════════════════════════════════════════

def expr_max(*exprs: FactorExpr) -> FactorExpr:
    """多元逐元素最大值。"""
    if len(exprs) == 0:
        raise ValueError("expr_max requires at least one argument")
    if len(exprs) == 1:
        return exprs[0]
    return CompositeExpr('max', *exprs)


def expr_min(*exprs: FactorExpr) -> FactorExpr:
    """多元逐元素最小值。"""
    if len(exprs) == 0:
        raise ValueError("expr_min requires at least one argument")
    if len(exprs) == 1:
        return exprs[0]
    return CompositeExpr('min', *exprs)


class TermStructureOp(OperandExpr):
    """Futures term-structure snapshot operator.

    This operator evaluates along each product's own futures contract curve at
    every timestamp. It is deliberately separate from CrossSectionalOp: the
    "cross section" here is contracts under one product, not products.
    """

    _LATEX = {
        'term_spread': '\\mathrm{TermSpread}',
        'term_ratio': '\\mathrm{TermRatio}',
        'term_slope': '\\mathrm{TermSlope}',
    }

    def __init__(self, op: str, *operands: FactorExpr):
        if op not in self._LATEX:
            raise ValueError(f"Unknown term structure op: {op}")
        expected = 3 if op in ('term_spread', 'term_ratio') else 2
        if len(operands) != expected:
            raise ValueError(f"{op} requires {expected} operands, got {len(operands)}")
        super().__init__(op, *operands)

    def _structural_key(self) -> tuple:
        return (type(self).__name__, self.op, tuple(op._structural_key() for op in self.operands))

    def _time_index_for_product(self, product: 'Product', freq: DataFreq) -> pd.Index:
        try:
            data = product.get_some_data(freq, copy=False)
        except Exception:
            return pd.Index([])
        if data is None or data.empty:
            return pd.Index([])
        return data.index

    @staticmethod
    def _trading_days_for_index(idx: pd.Index) -> pd.DatetimeIndex:
        if isinstance(idx, pd.MultiIndex):
            level_pos = 0
            for i, name in enumerate(idx.names):
                if name and str(name).upper().startswith('DAY'):
                    level_pos = i
                    break
            ts = pd.to_datetime(idx.get_level_values(level_pos))
        else:
            ts = pd.to_datetime(idx)
        days = pd.DatetimeIndex(ts)
        if days.tz is not None:
            days = days.tz_localize(None)
        return days.normalize()

    @staticmethod
    def _const_operand_value(expr: FactorExpr) -> Any:
        if isinstance(expr, ConstExpr):
            return expr.value
        raise TypeError(f"TermStructureOp operands must resolve to ConstExpr, got {type(expr).__name__}")

    @staticmethod
    def _column_name(expr: FactorExpr) -> str:
        if isinstance(expr, ColumnRef):
            return expr.column.name
        if isinstance(expr, ConstExpr):
            return DataColumn(expr.value).name
        raise TypeError(f"TermStructureOp column operand must resolve to ConstExpr or ColumnRef, got {type(expr).__name__}")

    @staticmethod
    def _operand_latex_arg(expr: FactorExpr, *, column: bool = False) -> str:
        if column:
            if isinstance(expr, ColumnRef):
                return expr.column.name
            if isinstance(expr, ConstExpr):
                return DataColumn(expr.value).name
            if isinstance(expr, ParamRef):
                return f"\\textcolor{{red}}{{{expr.param.alias}}}"
        if isinstance(expr, ConstExpr):
            return str(expr.value)
        return expr._to_latex()

    @staticmethod
    def _operand_alias_arg(expr: FactorExpr, *, column: bool = False) -> str:
        if column:
            if isinstance(expr, ColumnRef):
                return expr.column.value
            if isinstance(expr, ConstExpr):
                return DataColumn(expr.value).value
        return expr._get_alias()

    def _term_param_values(self) -> tuple[int, int, int, str]:
        if self.op in ('term_spread', 'term_ratio'):
            near_rank = int(self._const_operand_value(self.operands[0]))
            far_rank = int(self._const_operand_value(self.operands[1]))
            column = self._column_name(self.operands[2])
            return near_rank, far_rank, 0, column
        depth = int(self._const_operand_value(self.operands[0]))
        column = self._column_name(self.operands[1])
        return 0, 1, depth, column

    def _evaluate(
        self,
        products: Sequence['Product'],
        freq: DataFreq,
        source: Optional['DataSource'] = None,
        cache: Optional[Dict[FactorExpr, pd.DataFrame]] = None,
        preloaded: Optional[Dict[Any, pd.DataFrame]] = None,
        *args,
        **kwargs,
    ) -> pd.DataFrame:
        del source, cache, preloaded, args, kwargs
        near_rank, far_rank, depth, column = self._term_param_values()
        series_dict = {}
        for product in products:
            supports_term_structure = getattr(product, 'supports_term_structure', None)
            if callable(supports_term_structure) and not supports_term_structure():
                continue
            if not hasattr(product, 'get_term_structure'):
                continue
            raw_idx = self._time_index_for_product(product, freq)
            if len(raw_idx) == 0:
                continue
            trading_days = self._trading_days_for_index(raw_idx)
            if len(trading_days) == 0:
                continue
            if self.op == 'term_spread':
                batch_fn = getattr(product, 'term_spread_series', None)
                if not callable(batch_fn):
                    raise TypeError(f"Product {getattr(product, 'name', product)} missing required method term_spread_series")
                series = batch_fn(trading_days, near_rank=near_rank, far_rank=far_rank, column=column)
            elif self.op == 'term_ratio':
                batch_fn = getattr(product, 'term_ratio_series', None)
                if not callable(batch_fn):
                    raise TypeError(f"Product {getattr(product, 'name', product)} missing required method term_ratio_series")
                series = batch_fn(trading_days, near_rank=near_rank, far_rank=far_rank, column=column)
            else:
                batch_fn = getattr(product, 'term_slope_series', None)
                if not callable(batch_fn):
                    raise TypeError(f"Product {getattr(product, 'name', product)} missing required method term_slope_series")
                series = batch_fn(trading_days, depth=depth, column=column)
            if not isinstance(series, pd.Series):
                raise TypeError(f"Batch method for {getattr(product, 'name', product)} must return pd.Series, got {type(series).__name__}")
            mapped = series.astype(float).reindex(trading_days).to_numpy(dtype=float)
            series_dict[product] = pd.Series(mapped, index=raw_idx, dtype=float)
        if not series_dict:
            return pd.DataFrame()
        result = pd.concat(series_dict, axis=1)
        result.columns = list(series_dict.keys())
        return result

    @property
    def op_name(self) -> str:
        return self.op

    def _to_latex(self, subst: dict | None = None) -> str:
        sk = self._structural_key()
        if subst is not None and sk in subst:
            return f"{subst[sk]}_t"
        if self.op in ('term_spread', 'term_ratio'):
            near_rank = self._operand_latex_arg(self.operands[0])
            far_rank = self._operand_latex_arg(self.operands[1])
            column = self._operand_latex_arg(self.operands[2], column=True)
            return f"{self._LATEX[self.op]}_{{{near_rank},{far_rank}}}({column})"
        depth = self._operand_latex_arg(self.operands[0])
        column = self._operand_latex_arg(self.operands[1], column=True)
        return f"{self._LATEX[self.op]}_{{{depth}}}({column})"

    def _get_alias(self) -> str:
        if self.op in ('term_spread', 'term_ratio'):
            near_rank = self._operand_alias_arg(self.operands[0])
            far_rank = self._operand_alias_arg(self.operands[1])
            column = self._operand_alias_arg(self.operands[2], column=True)
            return f"{self.op}_{column}_{near_rank}_{far_rank}"
        depth = self._operand_alias_arg(self.operands[0])
        column = self._operand_alias_arg(self.operands[1], column=True)
        return f"{self.op}_{column}_{depth}"


def term_spread(near_rank: Any = 0, far_rank: Any = 1, column: Any = DataColumn.CLOSE) -> TermStructureOp:
    """Near-far futures term-structure spread: near - far."""
    return TermStructureOp('term_spread', _to_expr(near_rank), _to_expr(far_rank), _to_expr(column))


def term_ratio(near_rank: Any = 0, far_rank: Any = 1, column: Any = DataColumn.CLOSE) -> TermStructureOp:
    """Near-far futures term-structure ratio: near / far - 1."""
    return TermStructureOp('term_ratio', _to_expr(near_rank), _to_expr(far_rank), _to_expr(column))


def term_slope(depth: Any = 4, column: Any = DataColumn.CLOSE) -> TermStructureOp:
    """Linear slope of futures prices against days-to-maturity."""
    return TermStructureOp('term_slope', _to_expr(depth), _to_expr(column))


# ═════════════════════════════════════════════════════════════════════════════
# 预定义常用列引用（方便直接使用）
# ═════════════════════════════════════════════════════════════════════════════

OPEN = ColumnRef(DataColumn.OPEN_ADJUSTED)
HIGH = ColumnRef(DataColumn.HIGH_ADJUSTED)
LOW = ColumnRef(DataColumn.LOW_ADJUSTED)
CLOSE = ColumnRef(DataColumn.CLOSE_ADJUSTED)
VOLUME = ColumnRef(DataColumn.VOLUME)
TURNOVER = ColumnRef(DataColumn.TURNOVER)
OPEN_INTEREST = ColumnRef(DataColumn.OPEN_INTEREST)
VWAP = ColumnRef(DataColumn.VWAP)
SETTLE = ColumnRef(DataColumn.SETTLEMENT_PRICE)

# 原始（不复权）价格列
OPEN_RAW = ColumnRef(DataColumn.OPEN)
HIGH_RAW = ColumnRef(DataColumn.HIGH)
LOW_RAW = ColumnRef(DataColumn.LOW)
CLOSE_RAW = ColumnRef(DataColumn.CLOSE)


# ═════════════════════════════════════════════════════════════════════════════
# 信号对齐工具函数 & 表达式节点
# ═════════════════════════════════════════════════════════════════════════════

def signal_align(
    data: pd.DataFrame,
    freq: Any,
    basepoint: 'str|Callable' = 'last',
    daily_basepoint: 'str|None' = None,
    end_session_skip: bool = True,
    end_session_gap: pd.Timedelta = pd.Timedelta('3hours'),
) -> pd.DataFrame:
    """
    将原始数据对齐到等间隔信号时间点。

    参数：
        data           : 待对齐的 DataFrame（列=Product，行=MultiIndex 时间）
        freq           : 目标信号频率（如 '1d', '1h'）
        basepoint      : 基准点选择策略 'last'/'first'/callable
        daily_basepoint: 日倍频时的具体时间基准点（如 '15:00:00'），None 用 basepoint
        end_session_skip: 是否跳过盘间间隔（仅子日频生效）
        end_session_gap: 盘间间隔阈值

    返回：
        对齐后的 DataFrame，索引含 _SIGNAL@ 层级
    """
    import pandas as pd
    freq_dc = DataFreq(freq)
    bp = basepoint
    end_skip = end_session_skip
    end_gap = end_session_gap

    # 找到 freq 是其整数倍的索引层级（第一个匹配的）
    index_names = [str(n) for n in data.index.names]
    index_freqs = [DataFreq(n) for n in index_names]
    try:
        first_true_idx = next(
            (i for i, f in enumerate(index_freqs)
             if freq_dc.value.total_seconds() % f.value.total_seconds() == 0))
    except StopIteration:
        raise ValueError(
            f"频率 {freq_dc} 不是任何数据索引频率的整数倍")
    multiple = int(freq_dc.value.total_seconds() / index_freqs[first_true_idx].value.total_seconds())

    idx_name = index_names[first_true_idx]
    idx_series = data.index.get_level_values(idx_name).to_series().reset_index(drop=True)

    # 确定各组的基准点位置
    if freq_dc.is_day_multiple and daily_basepoint is not None:
        try:
            base_time = pd.Timestamp(daily_basepoint).time()
        except Exception:
            raise ValueError(
                f"Invalid time basepoint '{daily_basepoint}'. "
                f"Must be a time string like '09:01:00' or '15:00:00'")
        series = data.groupby(idx_name).transform(
            lambda x: pd.DatetimeIndex(x.index.get_level_values(-1)).time == base_time)
    elif isinstance(bp, str):
        bp_lower = bp.lower()
        if bp_lower == 'last':
            series = data.groupby(idx_name).cumcount(ascending=False) == 0
        elif bp_lower == 'first':
            series = data.groupby(idx_name).cumcount() == 0
        else:
            raise ValueError(
                f"Invalid basepoint '{bp}'. Must be 'last', 'first', or a callable")
    else:
        series = bp(data.groupby(idx_name))

    if not any(series):
        series = data.groupby(idx_name).cumcount(ascending=False) == 0
    assert isinstance(series, pd.Series) and series.dtype == bool, \
        "basepoint function must return a boolean Series"

    basepoint_pos = series.reset_index(drop=True).index[series]

    # 从基准点按 multiple 间隔取信号点
    if end_skip and isinstance(freq_dc.value, pd.Timedelta) and freq_dc.value < pd.Timedelta('1day'):
        last_col_name = index_names[-1]
        last_col = data.index.get_level_values(last_col_name).to_series().reset_index(drop=True)
        end_session_pos = last_col[last_col.shift(-1) - last_col >= end_gap].index
        signal_map_mask = basepoint_pos.isin({
            i
            for start, end in zip(
                [0] + (end_session_pos[:-1].values + 1).tolist(),
                end_session_pos
            )
            for i in range(start + multiple - 1, end + 1, multiple)
            if start + multiple - 1 <= end
        })
    else:
        idx = basepoint_pos.to_series().reset_index(drop=True).index
        signal_map_mask = (idx % multiple == multiple - 1)

    signal_pos = basepoint_pos[signal_map_mask]
    signal_map = idx_series.index.isin(signal_pos)

    # 构建新的索引
    signal_name = f'_SIGNAL@{freq_dc.name}'
    left_arrays = [
        data.index.get_level_values(index_names[i]).to_series().where(signal_map)
        for i in range(first_true_idx)
    ]
    signal_vals = idx_series.where(signal_map)
    right_arrays = [
        data.index.get_level_values(index_names[i]).to_series()
        for i in range(first_true_idx + 1, len(index_names))
    ]
    left_names = [str(n).split('@')[-1] for n in index_names[:first_true_idx]]
    right_names = [str(n).split('@')[-1] for n in index_names[first_true_idx + 1:]]
    new_index = pd.MultiIndex.from_arrays(
        left_arrays + [signal_vals] + right_arrays,
        names=left_names + [signal_name] + right_names
    ).dropna()

    result = data[signal_map].copy()
    result.index = new_index
    return result


# ═════════════════════════════════════════════════════════════════════════════
# 信号对齐表达式节点
# ═════════════════════════════════════════════════════════════════════════════

class SignalAlign(CompositeExpr):
    """
    信号对齐表达式节点 — 作为 CompositeExpr 的一元运算。

    将操作数表达式的求值结果对齐到等间隔信号时间点。
    op = 'SIGNAL_ALIGN'，operands = (func_expr,)

    参数：
        operand         : 被包裹的因子表达式
        signal_freq     : 目标信号频率（如 '1d', '1h'，可以是 $F 参数的值）
        basepoint       : 基准点选择策略 'last'/'first'/callable，默认 'last'
        daily_basepoint : 日倍频时的具体时间基准点，None 则用 basepoint
        end_session_skip: 是否跳过盘间间隔（仅子日频生效），默认 True
        end_session_gap : 盘间间隔阈值，默认 3hours
    """

    def __new__(cls, operand: FactorExpr, *args, **kwargs):
        return super().__new__(cls, 'SIGNAL_ALIGN', operand)

    def __init__(self, operand: FactorExpr, signal_freq: Any,
                 basepoint: 'str|Callable' = 'last',
                 daily_basepoint: 'str|None' = None,
                 end_session_skip: bool = True,
                 end_session_gap: pd.Timedelta = pd.Timedelta('3hours')):
        super().__init__('SIGNAL_ALIGN', operand)
        self.signal_freq = signal_freq
        self.basepoint = basepoint
        self.daily_basepoint = daily_basepoint
        self.end_session_skip = end_session_skip
        self.end_session_gap = end_session_gap
        # 保存最近一次求值前的原始数据（供 source_table 使用）
        self._raw_data: pd.DataFrame | None = None

    def _structural_extra(self) -> tuple:
        return ('signal_freq', str(self.signal_freq),
                'basepoint', str(self.basepoint),
                'daily_basepoint', str(self.daily_basepoint),
                'end_session_skip', self.end_session_skip,
                'end_session_gap', str(self.end_session_gap))

    def _apply_op(self, values: List[Any]) -> pd.DataFrame:
        data = values[0]
        self._raw_data = data  # 保存未对齐的原始数据
        return signal_align(
            data, self.signal_freq,
            basepoint=self.basepoint,
            daily_basepoint=self.daily_basepoint,
            end_session_skip=self.end_session_skip,
            end_session_gap=self.end_session_gap,
        )

    # ── 展示 ──

    @property
    def op_name(self) -> str:
        return f'SIGNAL@{self.signal_freq}'

    def _get_alias(self) -> str:
        inner = self.operands[0]._get_alias()
        return f'SIGNAL_{inner}'

    def _to_latex(self, subst: dict | None = None) -> str:
        sk = self._structural_key()
        if subst is not None and sk in subst:
            return f"{subst[sk]}_t"
        inner = self.operands[0]._to_latex(subst)
        return f'\\text{{SIGNAL}}_{{{self.signal_freq}}}({inner})'
