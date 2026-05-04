# =============================================================================
# Factors/MmMABreak.py
# 均价突破因子
#
# FactorFamily 表达式驱动版本。
# X_t = P_t - MA(N, P_t)
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class MmMABreak(FactorFamily):
    """均价突破因子。\n\n    参数：\n        P (DataColumn) : 价格列\n        N (Timedelta)  : 均线窗口\n        F (Timedelta)  : 信号频率"""


    @staticmethod
    def factor_expr():
        P = DataColumnParam('P', default_value='CA')
        N = WindowParam('N', default_value='10d')
        return P - P.rolling_mean(N)

    desc = '均价突破'
    description = """
## 这是什么
MmMABreak 是均价突破因子，计算当前价格与 N 期简单移动均线的差值。

## 它在看什么
价格站在均线上方为正（偏强），均线下方为负（偏弱）。

## 为什么这个因子可能行得通
均线穿越是趋势交易者最常用的信号源之一。

## 使用提醒
不同品种价格绝对值相差悬殊，建议配合标准化版本。

## 反转信号
价格大幅高于均线且均线斜率放缓时，均值回归概率上升。
"""

if __name__ == '__main__':
    ff = MmMABreak()
    ff.add_params(F='1d')
