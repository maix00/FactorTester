# =============================================================================
# Factors/VlGK.py
# Garman-Klass 波动率因子
#
# 结合日内高低点和开收价的波动率估计量：
#   GK_bar = 0.5*ln(H/L)^2 - (2*ln2-1)*ln(C/O)^2
#   X_t = sqrt((1/N) * sum(GK_bar))
# =============================================================================
import numpy as np
import pandas as pd
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import WindowParam


class VlGK(FactorFamily):
    """
    Garman-Klass 波动率因子。

    比单纯收益率方差估计效率更高，同时利用了 OHLC 四价信息。

    参数：
        N (Timedelta) : 滚动窗口，默认 14d
        F (Timedelta) : 输出信号频率
    """

    params = [
        WindowParam('N', default_value='14d'),
    ]

    chinese_name = 'Garman-Klass 波动率'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'VlGK 是 Garman-Klass 波动率估计量，综合利用日内高低点区间和开收价变化，理论上比纯收益率估计效率提升约 7 倍。',
        },
        {
            'title': '它在看什么',
            'body': '它将高低点之差（刻画日内最大波动范围）和开收价之差（刻画价格漂移方向）结合，给出一个更低方差的波动率估计。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '传统收益率标准差只用到收盘价，丢失了日内的振幅信息。GK 估计量利用了全部四价，在样本量相同的情况下能更准确地刻画波动率环境，进而更敏感地捕捉风险状态切换。',
        },
        {
            'title': '使用提醒',
            'body': 'GK 估计量假设无隔夜跳空（连续 Brownian Motion），在期货频繁出现夜盘跳空的品种上，估计偏差会比 YZ 或 RS 更大。',
        },
        {
            'title': '反转信号',
            'body': 'GK 波动率从极高位快速回落，代表日内扩张行情正在收缩，是等待方向选择而非追趋势的时机；GK 长期处于低位后突然放大，往往是方向性启动的前兆，原有盘整可能被打破。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            GK_t &:= \tfrac{1}{2}\ln\!\left(\tfrac{H_t}{L_t}\right)^2
                     - (2\ln 2 - 1)\ln\!\left(\tfrac{C_t}{O_t}\right)^2, \\[4pt]
            X_t  &:= \sqrt{\frac{1}{N}\sum_{s=t-N+1}^{t} GK_s}.
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, N: Any = pd.Timedelta('14d'), **kwargs) -> pd.Series:
        high  = product.DAY1[DataColumn.HIGH]
        low   = product.DAY1[DataColumn.LOW]
        open_ = product.DAY1[DataColumn.OPEN]
        close = product.DAY1[DataColumn.CLOSE]

        eps = 1e-10
        hl  = np.log((high / (low   + eps).replace(0, eps)).clip(lower=eps))
        co  = np.log((close / (open_ + eps).replace(0, eps)).clip(lower=eps))

        gk_bar = 0.5 * hl ** 2 - (2 * np.log(2) - 1) * co ** 2
        gk_var = gk_bar.rolling(N).mean().clip(lower=0.0)
        gk_vol = gk_var.apply(np.sqrt)

        return self.sync_signal(gk_vol.fillna(0.0))

if __name__ == '__main__':
    ff = VlGK()
    ff.clear_params()
    ff.add_params(F='1d', N='14d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
