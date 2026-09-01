# =============================================================================
# tools/factors/expr/visual_groups.py
# 因子表达式系统 — 从 FactorExpr.py 拆分
# =============================================================================
from __future__ import annotations

import threading
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Iterator,
    List,
    NamedTuple,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
    cast,
)

import numpy as np
import pandas as pd

from tools.data.types import DataColumn, DataFreq

if TYPE_CHECKING:
    from tools.data.providers import DataProviderProductTS as DataSource
    from tools.data.views.ProductDataView import ProductDataView
    from tools.parameters.Parameter import Parameter
    from tools.products.Product import Product


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
            {
                'key': 'bar_since',
                'label': '事件距离',
                'symbol': 'BarSince',
                'desc': (
                    'bar_since(condition, scope=bars(N), select="nearest", '
                    'default=nan, include_current=True)；scope 也可使用 '
                    'session(gap="3h") 或 trading_day()'
                ),
                'arity': 2,
                'slots': ['条件', '回看范围'],
            },
            {
                'key': 'bar_distance',
                'label': '历史匹配距离',
                'symbol': 'BarDistance',
                'desc': (
                    'X.bar_distance(condition, scope=bars(N), '
                    'select="nearest", default=nan)；condition 用 CURRENT 与 '
                    'CANDIDATE 表示当前值和候选历史值；scope 也可使用 '
                    'session(gap="3h") 或 trading_day()'
                ),
                'arity': 3,
                'slots': ['序列 X', '匹配条件', '回看范围'],
            },
        ],
        'more_label': '更多时序算子',
        'more_operators': [
            {'key': 'rolling_var', 'label': '方差', 'symbol': 'RVar', 'desc': 'X.rolling_var(N)', 'arity': 2, 'slots': ['序列 X', '窗口 N']},
            {'key': 'rolling_sum', 'label': '求和', 'symbol': 'RSum', 'desc': 'X.rolling_sum(N)', 'arity': 2, 'slots': ['序列 X', '窗口 N']},
            {'key': 'rolling_ema', 'label': 'EMA', 'symbol': 'REMA', 'desc': 'X.rolling_ema(N)', 'arity': 2, 'slots': ['序列 X', '窗口 N']},
            {'key': 'rolling_corr', 'label': '滚动相关', 'symbol': 'RCorr', 'desc': 'X.rolling_corr(Y, N)', 'arity': 3, 'slots': ['序列 X', '序列 Y', '窗口 N']},
            {'key': 'rolling_skew', 'label': '偏度', 'symbol': 'RSkew', 'desc': 'X.rolling_skew(N)', 'arity': 2, 'slots': ['序列 X', '窗口 N']},
            {'key': 'rolling_median', 'label': '中位数', 'symbol': 'RMed', 'desc': 'X.rolling_median(N)', 'arity': 2, 'slots': ['序列 X', '窗口 N']},
            {'key': 'rolling_quantile', 'label': '分位数', 'symbol': 'RQuant', 'desc': 'X.rolling_quantile(q, N)', 'arity': 3, 'slots': ['序列 X', '分位 q', '窗口 N']},
            {'key': 'rolling_mad', 'label': '中位绝对偏差', 'symbol': 'RMAD', 'desc': 'X.rolling_mad(N)', 'arity': 2, 'slots': ['序列 X', '窗口 N']},
            {'key': 'rolling_linreg_slope', 'label': '回归趋势斜率', 'symbol': 'Rβ', 'desc': 'X.rolling_linreg_slope(N)', 'arity': 2, 'slots': ['序列 X', '窗口 N']},
            {'key': 'rolling_linreg_r2', 'label': '回归趋势R²', 'symbol': 'RR²', 'desc': 'X.rolling_linreg_r2(N)', 'arity': 2, 'slots': ['序列 X', '窗口 N']},
            {'key': 'rolling_linreg_tstat', 'label': '回归趋势t值', 'symbol': 'Rt', 'desc': 'X.rolling_linreg_tstat(N)', 'arity': 2, 'slots': ['序列 X', '窗口 N']},
            {'key': 'rolling_linreg_resid_std', 'label': '回归残差波动', 'symbol': 'Rσe', 'desc': 'X.rolling_linreg_resid_std(N)', 'arity': 2, 'slots': ['序列 X', '窗口 N']},
            {'key': 'rolling_argmax', 'label': '最大位置', 'symbol': 'RArgMax', 'desc': 'X.rolling_argmax(N)', 'arity': 2, 'slots': ['序列 X', '窗口 N']},
            {'key': 'rolling_argmin', 'label': '最小位置', 'symbol': 'RArgMin', 'desc': 'X.rolling_argmin(N)', 'arity': 2, 'slots': ['序列 X', '窗口 N']},
        ],
    },
    {
        'key': 'cs',
        'label': '横截算子',
        'collapsed': False,
        'operators': [
            {'key': 'cs_rank', 'label': '截面排名', 'symbol': 'Rank', 'desc': 'X.cs_rank(mask=None)', 'arity': 2, 'slots': ['序列 X', '可选资格条件 mask']},
            {'key': 'cs_ordinal_rank', 'label': '截面整数排名', 'symbol': 'ORank', 'desc': 'X.cs_ordinal_rank(mask, ascending=True)', 'arity': 2, 'slots': ['序列 X', '资格条件 mask']},
            {'key': 'cs_zscore', 'label': '截面标准化', 'symbol': 'Z', 'desc': 'X.cs_zscore()', 'arity': 1, 'slots': ['序列 X']},
        ],
        'more_label': '更多横截算子',
        'more_operators': [
            {'key': 'cs_spearman', 'label': 'Spearman', 'symbol': 'rho_s', 'desc': 'X.cs_spearman(Y)', 'arity': 2, 'slots': ['序列 X', '序列 Y']},
            {'key': 'cs_corr', 'label': 'Pearson', 'symbol': 'rho', 'desc': 'X.cs_corr(Y)', 'arity': 2, 'slots': ['序列 X', '序列 Y']},
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
            {'key': 'tanh', 'label': '双曲正切', 'symbol': 'tanh', 'desc': 'X.tanh()', 'arity': 1, 'slots': ['序列 X']},
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
            {
                'key': 'term_carry_annualized',
                'label': '年化期限 carry',
                'symbol': 'TCarryAnn',
                'desc': '输入 near_rank, far_rank, column；返回 (near / far - 1) * 365 / 到期日差。',
                'arity': 3,
                'slots': ['近端 rank', '远端 rank', '字段 column'],
            },
            {
                'key': 'term_log_ratio',
                'label': '近远月 log 比值',
                'symbol': 'TLogRatio',
                'desc': '输入 near_rank, far_rank, column；返回 log(near / far)。',
                'arity': 3,
                'slots': ['近端 rank', '远端 rank', '字段 column'],
            },
            {
                'key': 'term_contango',
                'label': '升水强度',
                'symbol': 'TContango',
                'desc': '输入 near_rank, far_rank, column；返回 far / near - 1。',
                'arity': 3,
                'slots': ['近端 rank', '远端 rank', '字段 column'],
            },
            {
                'key': 'term_curvature',
                'label': '期限曲率',
                'symbol': 'TCurve',
                'desc': '输入 depth, column；返回价格对剩余期限二次拟合的二次项系数。',
                'arity': 2,
                'slots': ['合约深度 depth', '字段 column'],
            },
            {
                'key': 'term_slope_segment',
                'label': '分段期限斜率',
                'symbol': 'TSlopeSeg',
                'desc': '输入 near_rank, far_rank, column；返回两个指定 rank 间的价格/到期日斜率。',
                'arity': 3,
                'slots': ['近端 rank', '远端 rank', '字段 column'],
            },
            {
                'key': 'term_rank_value',
                'label': '指定 rank 曲线值',
                'symbol': 'TRankValue',
                'desc': '输入 rank, column；返回指定 rank 合约的曲线字段值。',
                'arity': 2,
                'slots': ['rank', '字段 column'],
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
    'tanh': 'tanh',
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
    'tanh': 'arithUnary',
    'sign': 'arithUnary',
    'expr_max': 'arithVariadic',
    'expr_min': 'arithVariadic',
    'term_spread': 'termStructure',
    'term_ratio': 'termStructure',
    'term_slope': 'termStructure',
    'term_carry_annualized': 'termStructure',
    'term_log_ratio': 'termStructure',
    'term_contango': 'termStructure',
    'term_curvature': 'termStructure',
    'term_slope_segment': 'termStructure',
    'term_rank_value': 'termStructure',
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
