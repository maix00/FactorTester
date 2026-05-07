# =============================================================================
# Factors/VlCV.py
# 变异系数因子
#
# FactorFamily 表达式驱动版本。
# X = std(ret, N) / |mean(ret, N)|
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam

class VlCV(FactorFamily):
    """变异系数（CV = std/|mean|）。\n\n    参数：\n        P (DataColumn) : 价格列\n        RF (Timedelta)  : 收益步长\n        N (Timedelta)   : 滚动窗口"""


    @staticmethod
    def factor_expr():
        P = DataColumnParam('P', default_value='CA')
        RF = WindowParam('RF', default_value='1d')
        N = WindowParam('N', default_value='20d')
        p = P.shift(0)
        ret = p.delta(RF) / (p.shift(RF) + 1e-10)
        return ret.rolling_std(N) / (ret.rolling_mean(N).abs() + 1e-10)

    desc = '变异系数'
    description = """
## 这是什么
VlCV 是收益率标准差除以收益率均值的绝对值（变异系数）。

## 它在看什么
变异系数度量"噪声比"。高 CV 意味波动远大于趋势，低 CV 意味趋势清晰。

## 为什么这个因子可能行得通
低 CV 的品种趋势更清晰，更适合趋势跟踪。高 CV 品种适合均值回归策略。

## 使用提醒
极端趋势期间 mean 接近零，CV 会爆炸。需要截断处理。

## 反转信号
CV 从高位回落代表噪声消退、趋势形成，可视为方向性交易的机会信号。
"""

if __name__ == '__main__':
    ff = VlCV()
    ff.add_params(F='1d')
