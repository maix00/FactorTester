# =============================================================================
# Factors/VpAmihud.py
# Amihud 非流动性因子
#
# FactorFamily 表达式驱动版本。
# X = MA(|ret(RF)| / TO, N)
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam

class VpAmihud(FactorFamily):
    """Amihud 非流动性指标。\n\n    参数：\n        P (DataColumn) : 价格列\n        N (Timedelta)   : 滚动窗口\n        RF (Timedelta)  : 收益步长"""


    @staticmethod
    def factor_expr():
        P = DataColumnParam('P', default_value='CA')
        N = WindowParam('N', default_value='20d')
        RF = WindowParam('RF', default_value='1d')
        p = P.shift(0)
        to = DataColumnParam('TO', default_value='TO')
        turn = to.shift(0)
        abs_ret = (p.delta(RF) / (p.shift(RF) + 1e-10)).abs()
        return (abs_ret / (turn + 1e-10)).ma(N)

    desc = 'Amihud 非流动性'
    description = """
## 这是什么
VpAmihud 是经典的 Amihud (2002) 非流动性度量：日收益绝对值除以成交额，再做移动平均。

## 它在看什么
每单位成交额引发的价格变动幅度。高值意味着流动性差，小资金就能推动价格；低值意味着流动性好。

## 为什么这个因子可能行得通
非流动性是风险溢价的源头之一。流动性差的品种需要更高的预期收益来补偿。

## 使用提醒
该指标对极端行情敏感（如涨跌停零成交），需要与其他流动性指标交叉验证。

## 反转信号
非流动性飙升往往预示市场恐慌，恐慌缓解后价格可能反弹。
"""

if __name__ == '__main__':
    ff = VpAmihud()
    ff.add_params(F='1d')
