# =============================================================================
# Factors/VlVolRatio.py
# 短长波动率比因子
#
# FactorFamily 表达式驱动版本。
# X = std(ret, Ns) / std(ret, Nl)
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam

class VlVolRatio(FactorFamily):
    """短长波动率比。\n\n    参数：\n        P (DataColumn) : 价格列\n        Ns (Timedelta)  : 短窗口\n        Nl (Timedelta)  : 长窗口\n        RF (Timedelta)  : 收益步长"""


    @staticmethod
    def factor_expr():
        P = DataColumnParam('P', default_value='CA')
        Ns = WindowParam('Ns', default_value='5d')
        Nl = WindowParam('Nl', default_value='20d')
        RF = WindowParam('RF', default_value='1d')
        p = P.shift(0)
        ret = p.delta(RF) / (p.shift(RF) + 1e-10)
        return ret.std(Ns) / (ret.std(Nl) + 1e-10)

    desc = '短长波动率比'
    description = """
## 这是什么
VlVolRatio 是短期波动率与长期波动率的比值。

## 它在看什么
比值 > 1 意味近期波动放大（可能正在形成趋势），比值 < 1 意味近期波动缩小（盘整）。

## 为什么这个因子可能行得通
波动率扩张是趋势启动的典型特征。短期波动率超越长期波动率是"突破确认"的量化版本。

## 使用提醒
突发事件会导致比值飙升，未必是趋势启动——需要结合方向判断。

## 反转信号
比值从高位回归 1 附近，说明短期亢奋消退，趋势可能进入盘整或反转。
"""

if __name__ == '__main__':
    ff = VlVolRatio()
    ff.add_params(F='1d')
