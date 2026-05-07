# =============================================================================
# Factors/OiHedgePressure.py
# 对冲压力因子
#
# FactorFamily 表达式驱动版本。
# X = oi.delta(N) / sum(volume, N)
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam

class OiHedgePressure(FactorFamily):
    """对冲压力因子。\n\n    参数：\n        N (Timedelta) : 回看窗口"""


    @staticmethod
    def factor_expr():
        N = WindowParam('N', default_value='10d')
        oi = DataColumnParam('OI', default_value='OI')
        vol = DataColumnParam('V', default_value='V')
        oi_s = oi.shift(0)
        vol_s = vol.shift(0)
        return oi_s.delta(N) / (vol_s.rolling_sum(N) + 1e-10)

    desc = '对冲压力'
    description = """
## 这是什么
OiHedgePressure 度量单位成交量对应的净持仓变化。

## 它在看什么
持仓变化相对于成交量的比例。高值意味着每单位成交带来了大量持仓变化，可能反映对冲盘的进入。

## 为什么这个因子可能行得通
投机盘通常在趋势方向建仓，而对冲盘在反方向建仓且规模更大。通过持仓变化/成交量的比率可以捕捉这种"非对称资金流"。

## 使用提醒
极端正值可能反映空头对冲压力（期货空头对冲现货多头），对价格形成下行压力。反之亦然。

## 反转信号
对冲压力从极端值回归零轴，代表套保盘解除，趋势动能释放。
"""

if __name__ == '__main__':
    ff = OiHedgePressure()
    ff.add_params(F='1d')
