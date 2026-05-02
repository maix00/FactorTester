# =============================================================================
# Factors/OiChgRat.py
# 持仓量变化率因子
#
# FactorFamily 表达式驱动版本。
# X = (OI - OI.shift(N)) / OI.shift(N)
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam

class OiChgRat(FactorFamily):
    """持仓量变化率。"""

    source_freq = 'MIN1'

    @staticmethod
    def factor_expr():
        N = WindowParam('N', default_value='5d')
        oi = DataColumnParam('OI', default_value='OI')
        oi_s = oi.shift(0)
        return oi_s.delta(N) / (oi_s.shift(N) + 1e-10)

    desc = '持仓量变化率'
    description = """
## 这是什么
OiChgRat 是持仓量 N 期变化率。

## 它在看什么
当市场参与者在特定方向加仓，持仓量会同步上升，因子捕捉这种资金入场速度。

## 为什么这个因子可能行得通
持仓扩张代表资金持续流入，通常意味着趋势有资金面支撑。

## 使用提醒
需结合价格方向判断——持仓增加配合价格上涨是标准多头信号；持仓增加配合价格下跌则是空头信号。

## 反转信号
持仓增速见顶后回落，往往意味着主力资金正在撤退。
"""

if __name__ == '__main__':
    ff = OiChgRat()
    ff.add_params(F='1d')
