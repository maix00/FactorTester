# =============================================================================
# Factors/VpLiquidity.py
# 流动性因子
#
# FactorFamily 表达式驱动版本。
# X = MA(V / |ret(1)|, N)
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam

class VpLiquidity(FactorFamily):
    """成交量流动性指标。\n\n    参数：\n        N (Timedelta) : 滚动窗口"""


    @staticmethod
    def factor_expr():
        N = WindowParam('N', default_value='10d')
        p = DataColumnParam('P', default_value='CA')
        v = DataColumnParam('V', default_value='V')
        price = p.shift(0)
        vol = v.shift(0)
        ret = price.delta(1) / (price.shift(1) + 1e-10)
        liquidity_per_bar = vol / (ret.abs() + 1e-6)
        return liquidity_per_bar.ma(N)

    desc = '流动性'
    description = """
## 这是什么
VpLiquidity 度量每单位绝对收益所需的成交量。成交量大而价格变动小代表高流动性。

## 它在看什么
高流动性品种买卖容易、冲击成本低；低流动性品种大单进场会显著影响价格。

## 为什么这个因子可能行得通
流动性是市场效率的基础。流动性越好的品种定价越有效，趋势更可能反映基本面。

## 使用提醒
流动性在极端行情中可能瞬间蒸发，历史流动性指标对尾部风险预测力有限。

## 反转信号
流动性从极低水平恢复说明市场恢复正常运作，是风险偏好情绪改善的信号。
"""

if __name__ == '__main__':
    ff = VpLiquidity()
    ff.add_params(F='1d')
