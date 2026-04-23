# =============================================================================
# Factors/VlYZ.py
# Yang-Zhang 波动率因子
#
# 综合隔夜方差、日内方差和 RS 方差的无偏估计量：
#   sigma^2 = sigma_o^2 + w * sigma_c^2 + (1-w) * sigma_RS^2
#   w = 0.34 / (1.34 + (N+1)/(N-1))
# =============================================================================
import numpy as np
import pandas as pd
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import WindowParam


class VlYZ(FactorFamily):
    """
    Yang-Zhang 波动率因子。

    同时考虑隔夜跳空、日内波动和 RS 估计量的综合波动率指标，
    是目前已知对 OHLC Bar 数据统计效率最高的无偏估计量之一。

    参数：
        N (Timedelta) : 滚动窗口，默认 14d
        F (Timedelta) : 输出信号频率
    """

    params = [
        WindowParam('N', default_value='14d'),
    ]

    chinese_name = 'Yang-Zhang 波动率'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'VlYZ 是 Yang-Zhang 波动率估计量，综合了隔夜跳空方差（σo²）、日内开收方差（σc²）和 RS 方差三项，是对 Garman-Klass 在有隔夜跳空时的改进，号称"最优"OHLC 无偏估计量。',
        },
        {
            'title': '它在看什么',
            'body': '它分别量化了三种波动来源：前收到今开的跳空幅度（隔夜风险）、今开到今收的方向性漂移（日内趋势）、日内高低极值的随机游走（日内噪声）。三者加权后得到综合波动率。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '期货市场有夜盘，隔夜跳空是重要风险来源，而 GK/PK 估计量都忽略这部分。YZ 显式地捕捉了隔夜方差，因此在A股期货等夜盘活跃的品种上，YZ 能更真实地刻画总波动风险，提供更准确的波动率状态信号。',
        },
        {
            'title': '使用提醒',
            'body': 'YZ 需要连续两个 Bar 的开盘价（计算隔夜收益），缺少数据时会出现较多 NaN；权重 ω 是通过最小化均方误差推导出的，对于非正态分布市场，最优ω可能偏离理论值。',
        },
        {
            'title': '反转信号',
            'body': 'YZ 波动率的隔夜分量（σo²）突然放大，往往意味着市场在非交易时段的信息冲击强烈，第二天开盘后的价格方向可能迅速被消化然后反转；若 σo² 和 σc² 同时处于高位而 RS 偏低，说明波动主要由跳空和开收价变化贡献而不是日内平稳趋势，均值回归概率更高。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            \sigma_o^2 &:= \tfrac{1}{N-1}\sum_{t}\!\left(\ln\tfrac{O_t}{C_{t-1}}-\overline{\ln\tfrac{O}{C_{-1}}}\right)^2,\\[3pt]
            \sigma_c^2 &:= \tfrac{1}{N-1}\sum_{t}\!\left(\ln\tfrac{C_t}{O_t}-\overline{\ln\tfrac{C}{O}}\right)^2,\\[3pt]
            \omega      &:= \frac{0.34}{1.34 + (N+1)/(N-1)},\\[3pt]
            X_t         &:= \sqrt{\sigma_o^2 + \omega\,\sigma_c^2 + (1-\omega)\,\sigma_{RS}^2}.
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, N: Any = pd.Timedelta('14d'), **kwargs) -> pd.Series:
        high  = product.DAY1[DataColumn.HIGH]
        low   = product.DAY1[DataColumn.LOW]
        open_ = product.DAY1[DataColumn.OPEN]
        close = product.DAY1[DataColumn.CLOSE]

        eps = 1e-10

        # Overnight log-return: log(O_t / C_{t-1})
        log_oc_prev = np.log((open_ / (close.shift(1) + eps).replace(0, eps)).clip(lower=eps))
        # Intraday log: log(C_t / O_t)
        log_co      = np.log((close / (open_ + eps).replace(0, eps)).clip(lower=eps))
        # RS per bar
        ho = np.log((high / (open_  + eps).replace(0, eps)).clip(lower=eps))
        hc = np.log((high / (close  + eps).replace(0, eps)).clip(lower=eps))
        lo = np.log((low  / (open_  + eps).replace(0, eps)).clip(lower=eps))
        lc = np.log((low  / (close  + eps).replace(0, eps)).clip(lower=eps))
        rs_bar = hc * ho + lc * lo

        n_int = N if isinstance(N, int) else max(2, int(N / pd.Timedelta('1d')))
        w = 0.34 / (1.34 + (n_int + 1) / (n_int - 1))

        # Rolling variances (ddof=1)
        sig_o2  = log_oc_prev.rolling(N).var()
        sig_c2  = log_co.rolling(N).var()
        sig_rs2 = rs_bar.rolling(N).mean().clip(lower=0.0)

        yz_var = (sig_o2.fillna(0.0) + w * sig_c2.fillna(0.0) + (1 - w) * sig_rs2).clip(lower=0.0)
        yz_vol = yz_var.apply(np.sqrt)

        return self.sync_signal(yz_vol.fillna(0.0))

if __name__ == '__main__':
    ff = VlYZ()
    ff.clear_params()
    ff.add_params(F='1d', N='14d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
