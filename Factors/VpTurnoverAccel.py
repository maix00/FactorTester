# =============================================================================
# Factors/VpTurnoverAccel.py
# 成交额加速度因子
#
# FactorFamily 表达式驱动版本。
# X = MA(TO, Ns) / MA(TO, Nl) - 1
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam

class VpTurnoverAccel(FactorFamily):
    """成交额加速度。\n\n    参数：\n        Ns (Timedelta) : 短窗口\n        Nl (Timedelta) : 长窗口"""

    source_freq = 'MIN1'

    @staticmethod
    def factor_expr():
        Ns = WindowParam('Ns', default_value='5d')
        Nl = WindowParam('Nl', default_value='20d')
        to = DataColumnParam('TO', default_value='TO')
        turn = to.shift(0)
        return turn.ma(Ns) / (turn.ma(Nl) + 1e-10) - 1.0

    desc = '成交额加速度'
    description = """
## 这是什么
VpTurnoverAccel 是短期成交额均值与长期成交额均值的相对变化。

## 它在看什么
正值代表成交额在加速（资金涌入），负值代表成交额在减速（资金撤退）。

## 为什么这个因子可能行得通
成交额加速往往伴随趋势启动——量先于价。成交额减速则预示趋势动力衰减。

## 使用提醒
成交额受时间因素影响（如夜盘与白盘差异），需要确保时间对齐。

## 反转信号
成交额加速到极端正值后回落，往往是"放量见顶"的经典反转模式。
"""

if __name__ == '__main__':
    ff = VpTurnoverAccel()
    ff.add_params(F='1d')
