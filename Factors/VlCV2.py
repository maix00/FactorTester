# =============================================================================
# Factors/VlCV2.py
# 变异系数 2 因子
#
# FactorFamily 表达式驱动版本。
# X = var(ret, N) / mean(ret, N)
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam

class VlCV2(FactorFamily):
    """变异系数 2（var/mean）。\n\n    参数：\n        P (DataColumn) : 价格列\n        RF (Timedelta)  : 收益步长\n        N (Timedelta)   : 滚动窗口"""


    @staticmethod
    def factor_expr():
        P = DataColumnParam('P', default_value='CA')
        RF = WindowParam('RF', default_value='1d')
        N = WindowParam('N', default_value='20d')
        p = P.shift(0)
        ret = p.delta(RF) / (p.shift(RF) + 1e-10)
        return ret.rolling_var(N) / (ret.rolling_mean(N) + 1e-10)

    desc = '变异系数 2'
    description = """
## 这是什么
VlCV2 是收益率方差除以收益率均值（另一种变异系数形式）。

## 它在看什么
与 CV 类似但使用方差（平方单位），对极端波动更敏感。

## 为什么这个因子可能行得通
方差对极端值的惩罚更大，在判断是否"噪声过大"时更保守。

## 使用提醒
方差大于 1 时可能严重放大。建议与 VlCV 配合使用。

## 反转信号
CV2 从极端高位快速下降往往意味市场从混乱进入有序——方向性机会。
"""

if __name__ == '__main__':
    ff = VlCV2()
    ff.add_params(F='1d')
