# =============================================================================
# Factors/OiNetBuild.py
# 净建仓因子
#
# FactorFamily 表达式驱动版本。
# signal = sign(d_price) when d_oi > 0 else 0; X = signal.ma(N)
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam

class OiNetBuild(FactorFamily):
    """净建仓因子。\n\n    参数：\n        P (DataColumn) : 价格列\n        OI (DataColumn) : 持仓量列\n        RF (Timedelta)  : 差分步长\n        N (Timedelta)   : 滚动窗口"""

    source_freq = 'MIN1'

    @staticmethod
    def factor_expr():
        P = DataColumnParam('P', default_value='CA')
        OI = DataColumnParam('OI', default_value='OI')
        RF = WindowParam('RF', default_value='1d')
        N = WindowParam('N', default_value='10d')
        p = P.shift(0)
        oi = OI.shift(0)
        d_price = p.delta(RF)
        d_oi = oi.delta(RF)
        signal = d_price.sign() * (d_oi > 0)
        return signal.ma(N)

    desc = '净建仓因子'
    description = """
## 这是什么
OiNetBuild 在持仓增加时取价格方向信号，然后做移动平均得到净建仓倾向。

## 它在看什么
当持仓增加时，记录价格是涨（+1）还是跌（-1），跨 N 期平均后得到资金的净方向偏好。

## 为什么这个因子可能行得通
持仓增加代表新资金入场，方向信号告诉我们是多头还是空头在加仓。N 期平均剔除噪声。

## 使用提醒
该因子只关注增仓时的方向，减仓时不贡献信号。在减仓市场中因子可能"失声"。

## 反转信号
净建仓从持续正/负转为零线附近波动，代表多空力量趋于均衡，可能出现方向选择。
"""

if __name__ == '__main__':
    ff = OiNetBuild()
    ff.add_params(F='1d')
