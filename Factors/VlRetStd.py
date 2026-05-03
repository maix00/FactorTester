# =============================================================================
# Factors/VlRetStd.py
# 收益率标准差因子
#
# FactorFamily 表达式驱动版本。
# X = std(pct_change(P, RF), N)
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam

class VlRetStd(FactorFamily):
    """收益率标准差。\n\n    参数：\n        P (DataColumn) : 价格列\n        RF (Timedelta)  : 收益步长\n        N (Timedelta)   : 滚动窗口"""


    @staticmethod
    def factor_expr():
        P = DataColumnParam('P', default_value='CA')
        RF = WindowParam('RF', default_value='1d')
        N = WindowParam('N', default_value='20d')
        p = P.shift(0)
        ret = p.delta(RF) / (p.shift(RF) + 1e-10)
        return ret.std(N)

    desc = '收益率标准差'
    description = """
## 这是什么
VlRetStd 是收益率的标准差，最直接的历史波动率度量。

## 它在看什么
波动率本身不判断方向，只度量价格的离散程度。高波动意味着不确定性大。

## 为什么这个因子可能行得通
波动率聚集效应：高波动后往往继续高波动，低波动后继续低波动。作为风险度量，在截面和时间序列都有预测力。

## 使用提醒
波动率本身不能判断方向——高波动既能出现在牛市也能出现在熊市。

## 反转信号
波动率冲至极端值后回归均值，是期权交易中最经典的均值回归策略。
"""

if __name__ == '__main__':
    ff = VlRetStd()
    ff.add_params(F='1d')
