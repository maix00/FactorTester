# =============================================================================
# Factors/VpTurnoverAccel.py
# 成交额加速因子
#
# 成交额近期均值相对长期均值的比值（成交活跃度加速）：
#   X_t = MA(TO, N_short) / MA(TO, N_long) - 1
# 正值表示成交额在加速放大（市场热度上升），可结合方向性因子使用。
# =============================================================================
import pandas as pd
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import WindowParam


class VpTurnoverAccel(FactorFamily):
    """
    成交额加速因子。

    短期成交额均值相对长期成交额均值的偏离比率，
    衡量市场活跃度的近期变化趋势。

    参数：
        Ns (Timedelta) : 短期窗口，默认 5d
        Nl (Timedelta) : 长期窗口，默认 20d
        F  (Timedelta) : 输出信号频率
    """

    params = [
        WindowParam('Ns', default_value='5d'),
        WindowParam('Nl', default_value='20d'),
    ]

    chinese_name = '成交额加速度'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'VpTurnoverAccel 是成交额加速度因子，通过比较短窗口与长窗口的成交额均值，衡量资金活跃度是在升温还是降温。',
        },
        {
            'title': '它在看什么',
            'body': '当短期成交额均值显著高于长期均值时，说明资金参与度正在加速提升；若短期低于长期，则说明市场热度在降温。这个因子关注的是量能变化的斜率，而非绝对成交额水平。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '很多趋势启动、突破确认或风险释放，都会伴随成交活跃度突然抬升。量能加速意味着有更多资金开始参与当前状态，因此往往能为价格变化提供确认；如果价格动了但量能没有跟上，则信号可信度通常更弱。',
        },
        {
            'title': '使用提醒',
            'body': '单独看量能升温并不能判断方向，因此它更适合和价格、波动率或持仓因子联合使用。',
        },
        {
            'title': '反转信号',
            'body': '成交额加速度因子的反转：（1）成交额快速从低到高后若价格未跟上（量升价平），是量价背离的信号，后续价格可能向成交量收缩方向回归；（2）成交额在高价位持续萎缩（加速度为负），说明换手资金不足以维持价格，反转压力累积；（3）成交额在急跌后短时间内急速萎缩（恐慌单耗尽），而价格企稳——此类"成交量枯竭"形态是反弹的经典前提。反转在成交额加速度从极端正值快速转负时信号最为明显，持续时间通常较短，适合短线把握。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            X_t &:= \frac{\mathrm{RollingMean}_{N_s}(TO)_t}{\mathrm{RollingMean}_{N_l}(TO)_t} - 1
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, Ns: Any = pd.Timedelta('5d'),
                        Nl: Any = pd.Timedelta('20d'), **kwargs) -> pd.Series:
        turnover = product.MIN1[DataColumn.TURNOVER]
        ma_short = turnover.rolling(Ns).mean()
        ma_long  = turnover.rolling(Nl).mean().replace(0, float('nan'))
        accel = ma_short / ma_long - 1.0
        accel = accel.fillna(0.0)
        return self.sync_signal(accel)
if __name__ == '__main__':
    ff = VpTurnoverAccel()
    ff.clear_params()
    ff.add_params(F='1d', Ns='5d', Nl='20d')
    ff.add_params(F='1d', Ns='3d', Nl='10d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
