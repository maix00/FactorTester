# =============================================================================
# Factors/MmIntradayMom.py
# 日内动量因子
#
# 过去 N 个交易日日内涨幅（当日收 / 当日开 - 1）的均值：
#   X_t = (1/N) * Σ (C_s - O_s) / O_s
# 正值意味着近期价格在日内持续上涨，负值意味着日内持续下跌。
# =============================================================================
import pandas as pd
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import WindowParam


class MmIntradayMom(FactorFamily):
    """
    日内动量因子。

    计算过去 N 个交易日每日日内涨幅（收盘价/开盘价 - 1）均值，
    反映日内交易行为的净方向性贡献。

    参数：
        N (Timedelta) : 回看交易日数，默认 10d
        F (Timedelta) : 输出信号频率
    """

    params = [
        WindowParam('N', default_value='10d'),
    ]

    chinese_name = '日内动量'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'MmIntradayMom 是日内动量因子，统计最近 N 个交易日每天收盘价相对当天开盘价的平均涨幅，捕捉日内资金流向的系统性方向。',
        },
        {
            'title': '它在看什么',
            'body': '它回答"日内交易时段的净资金流向是否持续偏向多方"。持续正值意味着多方在日内主导，连续压制价格的空方力量偏弱；持续负值则相反。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '日内动量与隔夜趋势分别代表不同资金的行为：日内动量更多反映存量资金（日内短线、量化程序）的倾向，隔夜趋势更多反映增量资金（宏观驱动）的倾向。日内动量的持续性本身就可能是交易者行为锁定的结果（如量化策略集体同向）。',
        },
        {
            'title': '使用提醒',
            'body': '日内涨幅受收盘前资金博弈影响较大（如尾盘打压/拉升），若存在系统性收盘行为扭曲，因子会有噪声。建议结合成交量加权价格验证方向的真实性。',
        },
        {
            'title': '反转信号',
            'body': '日内动量和隔夜趋势持续背离（日内持续收跌但隔夜持续跳高，或反过来）是行情即将切换的经典信号之一，因为两类资金的方向共识不一致很难长期维持；日内动量从历史高/低极值开始收窄，且伴随成交量萎缩，说明日内主导力量正在减弱，反转时机临近。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            r^{ID}_s &:= \frac{C_s - O_s}{O_s}, \\[4pt]
            X_t      &:= \frac{1}{N}\sum_{s=t-N+1}^{t} r^{ID}_s.
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, N: Any = pd.Timedelta('10d'), **kwargs) -> pd.Series:
        daily_open  = product.DAY1[DataColumn.OPEN_ADJUSTED]
        daily_close = product.DAY1[DataColumn.CLOSE_ADJUSTED]

        intraday_ret = (daily_close - daily_open) / daily_open.replace(0, float('nan'))
        factor = intraday_ret.rolling(N).mean().fillna(0.0)

        return self.sync_signal(factor)

if __name__ == '__main__':
    ff = MmIntradayMom()
    ff.clear_params()
    ff.add_params(F='1d', N='10d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
