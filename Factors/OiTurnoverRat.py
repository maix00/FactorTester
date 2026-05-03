# =============================================================================
# Factors/OiTurnoverRat.py
# 持仓换手率因子
#
# FactorFamily 表达式驱动版本。
# X = OI / mean(volume, N)
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam

class OiTurnoverRat(FactorFamily):
    """持仓换手率因子。\n\n    参数：\n        N (Timedelta) : 滚动窗口"""


    @staticmethod
    def factor_expr():
        N = WindowParam('N', default_value='5d')
        oi = DataColumnParam('OI', default_value='OI')
        vol = DataColumnParam('V', default_value='V')
        oi_s = oi.shift(0)
        vol_s = vol.shift(0)
        return oi_s / (vol_s.ma(N) + 1e-10)

    desc = '持仓换手率'
    description = """
## 这是什么
OiTurnoverRat 度量持仓量相对于近期平均成交量的比例。

## 它在看什么
高换手率意味着持仓量远超日成交量——大资金深度参与。低换手率代表资金参与度低或持仓分散。

## 为什么这个因子可能行得通
换手率是机构参与度的代理变量。高换手率品种更容易形成趋势，低换手率品种更容易盘整。

## 使用提醒
换手率绝对值因品种而异，更适合做截面比较而非时序分析。

## 反转信号
换手率从高位快速回落代表大资金撤退，流动性枯竭可能导致价格剧烈波动。
"""

if __name__ == '__main__':
    ff = OiTurnoverRat()
    ff.add_params(F='1d')
