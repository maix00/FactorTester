# =============================================================================
# Factors/MmTrend.py
# 趋势斜率因子
#
# FactorFamily 表达式驱动版本。
# X_t = (P_t - P_{t-N+1}) / ((N-1) * MA(N, P_t))
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class MmTrend(FactorFamily):
    """趋势斜率因子。\n\n    参数：\n        P (DataColumn) : 价格列\n        N (Timedelta)  : 窗口\n        F (Timedelta)  : 信号频率"""


    @staticmethod
    def factor_expr():
        P = DataColumnParam('P', default_value='CA')
        N = WindowParam('N', default_value='20d')
        return (P - P.shift(N - 1)) / ((N - 1) * P.ma(N) + 1e-10)

    desc = '趋势斜率'
    description = """
## 这是什么
MmTrend 是趋势斜率因子，用首尾价格差除以窗口均价估计线性趋势斜率。

## 它在看什么
窗口内净变动幅度和方向，用均价做归一化。

## 为什么这个因子可能行得通
快速判断价格在窗口内的净变动，比纯收益率多了一层归一化。

## 使用提醒
极端值可能出现在均价尚未追上价格剧烈波动的情况。

## 反转信号
趋势斜率在高位走平或拐头是趋势衰竭的早期信号。
"""

if __name__ == '__main__':
    ff = MmTrend()
    ff.add_params(F='1d')
