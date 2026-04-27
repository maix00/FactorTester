# =============================================================================
# Factors/MmIntradayRange.py
# 日内累计振幅因子
#
# 过去 N 个交易日日内路径振幅均值：
#   step_s = [2*(H_s - L_s)*sign(C_s - O_s) - (C_s - O_s)] / C_s
#   X_t = (1/N) * Σ step_s
# 正值表示日内呈扩张性上涨路径，负值表示扩张性下跌路径。
# =============================================================================
import numpy as np
import pandas as pd
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import WindowParam


class MmIntradayRange(FactorFamily):
    """
    日内累计振幅因子。

    将每日的日内路径拆解为"有向振幅"：
    高低点区间乘以日内方向，再减去净开收变动，最后用收盘价归一化。
    相比纯日内收益率，额外捕捉了"区间扩张"信息。

    参数：
        N (Timedelta) : 回看交易日数，默认 10d
        F (Timedelta) : 输出信号频率
    """

    params = [
        WindowParam('N', default_value='10d'),
    ]

    chinese_name = '日内累计振幅'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'MmIntradayRange 是日内累计振幅因子，将每日的高低点区间乘以日内价格方向（sign），再减去净收益变动后归一化，捕捉"方向性扩张"的程度，比纯日内收益率包含更多路径信息。',
        },
        {
            'title': '它在看什么',
            'body': '若一天内价格大幅向上扩张（高点很高、低点也相对固守），因子取较大正值；若向下扩张（低点很低、高点较收敛），取较大负值。它强调方向和区间的联合信息，而不仅是净收益。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '一个真正的上涨日不仅收盘涨，而且盘中持续在较高区间运行（高点高、低点也高）。日内振幅扩张因子把这种"区间整体抬升"的信息量化出来，能区分"真实上涨"（宽幅高位振荡）和"尾盘拉升"（收盘涨但振幅窄）。',
        },
        {
            'title': '使用提醒',
            'body': '该因子对盘中极值（高低点）比较敏感，若存在个别异常报价拉高 H 或压低 L，会被计入。建议对 H-L 做极值处理；N 太短时波动大，N 太长时对近期变化反应迟钝。',
        },
        {
            'title': '反转信号',
            'body': '日内振幅连续多日大幅扩张上行后，若突然出现高位缩量窄幅（H-L 收窄、振幅回落），是动能衰竭信号；若连续几天出现" 巨大振幅但净收益接近 0"（即 sign 项开始接近中性），说明多空分歧加剧，方向性突破前的震荡期，更适合等待而非追趋势。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            step_s &:= \frac{2(H_s - L_s)\cdot\text{sign}(C_s - O_s) - (C_s - O_s)}{C_s}, \\[4pt]
            X_t    &:= \frac{1}{N}\sum_{s=t-N+1}^{t} step_s.
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, N: Any = pd.Timedelta('10d'), **kwargs) -> pd.Series:
        high   = product.DAY1[DataColumn.HIGH_ADJUSTED]
        low    = product.DAY1[DataColumn.LOW_ADJUSTED]
        open_  = product.DAY1[DataColumn.OPEN_ADJUSTED]
        close  = product.DAY1[DataColumn.CLOSE_ADJUSTED]

        hl_range   = high - low
        co_change  = close - open_
        direction  = co_change.apply(np.sign)
        close_safe = close.replace(0, float('nan'))

        step = (2 * hl_range * direction - co_change) / close_safe
        factor = step.rolling(N).mean().fillna(0.0)

        return self.sync_signal(factor)

if __name__ == '__main__':
    ff = MmIntradayRange()
    ff.clear_params()
    ff.add_params(F='1d', N='10d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
