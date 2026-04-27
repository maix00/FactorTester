# =============================================================================
# Factors/OiHedgePressure.py
# 对冲压力因子
#
# 主力合约持仓量变化与 N 期累计成交量之比：
#   X_t = (OI_t - OI_{t-N}) / sum(Vol, t-N+1..t)
# 正值表示净建仓，负值表示净减仓；分母归一化使得结果可跨品种比较。
# =============================================================================
import pandas as pd
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import WindowParam


class OiHedgePressure(FactorFamily):
    """
    对冲压力因子。

    持仓量变化量除以同期成交量之和，刻画每单位成交量背后的净建仓强度。
    正值意味着每笔交易总体上是在净建仓，负值意味着净减仓。

    参数：
        N  (Timedelta) : 回看窗口，默认 10d
        RF (Timedelta) : 单期步长，默认 1d
        F  (Timedelta) : 输出信号频率
    """

    params = [
        WindowParam('N',  default_value='10d'),
        WindowParam('RF', default_value='1d'),
    ]

    chinese_name = '对冲压力'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'OiHedgePressure 是对冲压力因子，用持仓量净变化除以同期全部成交量之和，衡量"有多少比例的成交是在净建仓（而不是对冲平仓）"。',
        },
        {
            'title': '它在看什么',
            'body': '如果因子为正且绝对值大，说明市场成交中大部分是在净建新仓，新资金在主动暴露头寸；为负则说明大量成交在净去化仓位，可能是机构对冲减仓。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '对冲压力因子本质上类似于 OiNetBuild，但分母换成了累计成交量（而不是只看绝对变化量），因此对不同品种的交易活跃程度进行了标准化，更适合跨品种横截面比较。它回答的是"这段时间的活跃交易到底是在建仓还是在去化" 这个问题。',
        },
        {
            'title': '使用提醒',
            'body': '成交量分母受到交割前放量和节假日缩量的影响，会产生阶段性失真；建议对分母做最小值保护，避免低成交量期间的极端值。',
        },
        {
            'title': '反转信号',
            'body': '对冲压力长期为正（持续净建仓）后若价格开始高位震荡甚至回落，意味着新增仓位正在被套，后续清仓带来的抛压可能较重，反转幅度更大；因子从高正值快速滑落至负值（由净建仓转为净去化），是趋势反转的强确认信号，结合价格下跌时尤其可靠。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            X_t &:= \frac{OI_t - OI_{t-N}}{\displaystyle\sum_{s=t-N+1}^{t} Vol_s}.
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, N: Any = pd.Timedelta('10d'), RF: Any = pd.Timedelta('1d'),
                        **kwargs) -> pd.Series:
        oi     = product.MIN1[DataColumn.OPEN_ADJUSTED_INTEREST]
        volume = product.MIN1[DataColumn.VOLUME]

        if isinstance(N, pd.Timedelta) and isinstance(RF, pd.Timedelta):
            steps = max(1, int(N / RF))
        else:
            steps = int(N) if not isinstance(N, pd.Timedelta) else 1

        oi_change = oi - oi.shift(steps)
        vol_sum   = volume.rolling(N).sum().replace(0, float('nan'))
        factor    = (oi_change / vol_sum).fillna(0.0).replace([float('inf'), -float('inf')], 0.0)
        return self.sync_signal(factor)

if __name__ == '__main__':
    ff = OiHedgePressure()
    ff.clear_params()
    ff.add_params(F='1d', N='10d', RF='1d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
