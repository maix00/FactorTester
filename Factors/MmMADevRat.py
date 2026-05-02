# =============================================================================
# Factors/MmMADevRat.py
# 均线偏离比因子
#
# FactorFamily 表达式驱动版本。
# X_t = -MA(N, P_t) / P_t
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class MmMADevRat(FactorFamily):
    """均线偏离比值因子。\n\n    参数：\n        P (DataColumn) : 价格列\n        N (Timedelta)  : 均线窗口\n        F (Timedelta)  : 信号频率"""

    source_freq = 'MIN1'

    @staticmethod
    def factor_expr():
        P = DataColumnParam('P', default_value='CA')
        N = WindowParam('N', default_value='5d')
        return -P.ma(N) / (P + 1e-10)

    desc = '均线偏离比'
    description = """
## 这是什么
MmMADevRat 是均线偏离比值因子，-(MA/P)，价格越高因子越大。

## 它在看什么
当价格站上均线时因子 > -1，价格大幅高于均线时趋近于 0。

## 为什么这个因子可能行得通
价格与均线的比值是做多空区分的简单有效方式。

## 使用提醒
价格在均线附近时因子变化剧烈。

## 反转信号
因子值长期在极窄区间后突然跳变，往往是趋势衰竭信号。
"""

if __name__ == '__main__':
    ff = MmMADevRat()
    ff.add_params(F='1d')
