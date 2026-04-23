# =============================================================================
# Factors/MmYZTrend.py
# 日内 YZ 波动趋势因子
#
# 过去 N 个交易日，Yang-Zhang 波动量（隔夜+日内+RS）乘以日内方向的均值：
#   direction_s = sign(C_s - O_s)
#   YZ_s = sigma_o^2 + w*sigma_c^2 + (1-w)*sigma_RS^2 (rolling over N window)
#   X_t = YZ_vol * sign(mean(C_s - O_s over N days))
# =============================================================================
import numpy as np
import pandas as pd
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import WindowParam


class MmYZTrend(FactorFamily):
    """
    日内 YZ 波动趋势因子。

    用 Yang-Zhang 波动率（最全面的 OHLC 估计量，考虑隔夜跳空）
    乘以 N 日内日内方向的均值（趋势方向），合成"有方向的全面波动"。

    参数：
        N (Timedelta) : 回看交易日数，默认 10d
        F (Timedelta) : 输出信号频率
    """

    params = [
        WindowParam('N', default_value='10d'),
    ]

    chinese_name = 'YZ 波动趋势'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'MmYZTrend 是日内 YZ 波动趋势因子，将最全面的 Yang-Zhang 波动率（考虑隔夜跳空、日内漂移和随机游走三个分量）与 N 日内日内平均方向相乘，是趋势-波动复合型因子中信息量最丰富的版本。',
        },
        {
            'title': '它在看什么',
            'body': '它同时捕捉了三个维度：趋势方向（日内涨跌均值）、方向性波动强度（YZ 波动率）、以及波动的来源结构（是夜盘跳空为主还是日内趋势为主）。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '在期货品种中，真正的有效趋势往往同时伴随方向明确 + 波动扩张 + 夜盘支撑三个特征，YZ 趋势因子正是把这三者融合在一起，能筛出市场共识度更高、参与度更强的趋势行情。',
        },
        {
            'title': '使用提醒',
            'body': 'YZ 需要至少两个连续 Bar 计算隔夜分量，数据不完整时会产生更多 NaN；该因子是 MmRSTrend/GKTrend/PKTrend 中最复杂的版本，适合作为核心趋势信号，其他版本作为稳健性检验。',
        },
        {
            'title': '反转信号',
            'body': 'YZ 趋势因子处于极端值后，若 σo²（隔夜分量）开始快速收缩而日内分量维持高位，说明夜盘推力减弱但日内惯性仍在——这是趋势末期的经典形态，均值回归概率上升；若 YZ 趋势因子从高位快速归零，通常意味着三个分量同时弱化，趋势已全面终止，这往往是最可靠的反转信号之一。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            \sigma_{YZ}^2 &:= \sigma_o^2 + \omega\,\sigma_c^2 + (1-\omega)\,\sigma_{RS}^2, \\[4pt]
            X_t           &:= \sigma_{YZ} \cdot \overline{\text{sign}(C_s - O_s)}_N.
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, N: Any = pd.Timedelta('10d'), **kwargs) -> pd.Series:
        high  = product.DAY1[DataColumn.HIGH]
        low   = product.DAY1[DataColumn.LOW]
        open_ = product.DAY1[DataColumn.OPEN]
        close = product.DAY1[DataColumn.CLOSE]

        eps = 1e-10

        log_oc_prev = np.log((open_ / (close.shift(1) + eps).replace(0, eps)).clip(lower=eps))
        log_co      = np.log((close / (open_  + eps).replace(0, eps)).clip(lower=eps))
        ho = np.log((high / (open_ + eps).replace(0, eps)).clip(lower=eps))
        hc = np.log((high / (close + eps).replace(0, eps)).clip(lower=eps))
        lo = np.log((low  / (open_ + eps).replace(0, eps)).clip(lower=eps))
        lc = np.log((low  / (close + eps).replace(0, eps)).clip(lower=eps))
        rs_bar = hc * ho + lc * lo

        n_int = N if isinstance(N, int) else max(2, int(N / pd.Timedelta('1d')))
        w = 0.34 / (1.34 + (n_int + 1) / (n_int - 1))

        sig_o2  = log_oc_prev.rolling(N).var().fillna(0.0)
        sig_c2  = log_co.rolling(N).var().fillna(0.0)
        sig_rs2 = rs_bar.rolling(N).mean().clip(lower=0.0).fillna(0.0)

        yz_vol = ((sig_o2 + w * sig_c2 + (1 - w) * sig_rs2).clip(lower=0.0)).apply(np.sqrt)

        # direction = mean of sign(C-O) over N days
        direction = (close - open_).apply(np.sign).rolling(N).mean().fillna(0.0)
        factor    = yz_vol * direction

        return self.sync_signal(factor.fillna(0.0))

if __name__ == '__main__':
    ff = MmYZTrend()
    ff.clear_params()
    ff.add_params(F='1d', N='10d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
