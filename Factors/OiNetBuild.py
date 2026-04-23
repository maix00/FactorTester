# =============================================================================
# Factors/OiNetBuild.py
# 净建仓方向因子
#
# 同时看持仓量变化方向与价格变化方向，推断多空净建仓方向：
#   ΔOI_t > 0 且 ΔP_t > 0  →  多头净建仓  (+1)
#   ΔOI_t > 0 且 ΔP_t < 0  →  空头净建仓  (-1)
#   ΔOI_t < 0              →  净平仓       (0)
#   X_t = rolling mean(signal, N)
# =============================================================================
import pandas as pd
import numpy as np
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class OiNetBuild(FactorFamily):
    """
    净建仓方向因子。

    根据持仓量变化和价格方向联合推断：
      - 持仓增加 + 价格上涨 → 多头建仓（+1）
      - 持仓增加 + 价格下跌 → 空头建仓（−1）
      - 持仓减少 → 平仓（0）
    在 N 期窗口内取均值作为净建仓倾向。

    参数：
        P  (DataColumn) : 价格列，默认 CLOSE
        N  (Timedelta)  : 均值窗口，默认 10d
        RF (Timedelta)  : 单期步长，默认 1d
        F  (Timedelta)  : 输出信号频率
    """

    params = [
        DataColumnParam('P', DataColumn.CLOSE),
        WindowParam('N',  default_value='10d'),
        WindowParam('RF', default_value='1d'),
    ]

    chinese_name = '净建仓因子'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'OiNetBuild 是净增仓方向因子。它只在持仓量上升时记录价格方向，并在窗口内做平均，用来刻画“新增仓位大致是顺着哪一边的价格方向在建立”。',
        },
        {
            'title': '它在看什么',
            'body': '如果持仓增加时价格也更多在上涨，说明更像是顺着上涨方向的新仓在建立；如果持仓增加时价格更多在下跌，则更像是顺着下跌方向的新仓在建立。持仓不增加时，该期贡献会被弱化或置零。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '与纯价格动量不同，这个因子要求“价格方向”和“新增仓位”同时出现，才认为信号更可信。它试图过滤掉单纯平仓造成的价格波动，把注意力集中在真正有新增资金推动的行情上。',
        },
        {
            'title': '使用提醒',
            'body': '它更适合期货这类持仓量信息有意义的市场。若持仓统计存在跨合约切换或主力迁移效应，需要留意数据连续性。',
        },
        {
            'title': '反转信号',
            'body': '净建仓因子的反转逻辑来自持仓结构的失衡：（1）价格上涨但净建仓为负（持仓量在下降）——趋势由平仓驱动而非新建仓支撑，可持续性弱，反转可能较快；（2）价格快速上涨伴随持仓量快速增加（净建仓大幅为正），追涨情绪浓，一旦价格停涨，多头被套引发的抛压使反转更剧烈；（3）价格与净建仓方向长期背离后的修复，通常以价格向持仓方向靠拢（反转）的方式完成。持仓驱动的反转在期货市场中往往比股票更加急速，需要控制好持有时间。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            s_t &:=
            \begin{cases}
                +1 & \Delta OI_t > 0 \text{ and } \Delta P_t > 0 \\
                -1 & \Delta OI_t > 0 \text{ and } \Delta P_t < 0 \\
                0  & \Delta OI_t \leq 0
            \end{cases} \\[5pt]
            X_t &:= \frac{1}{N}\sum_{s} s_s
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, N: Any = pd.Timedelta('10d'), RF: Any = pd.Timedelta('1d'),
                        P: DataColumn = DataColumn.CLOSE, **kwargs) -> pd.Series:
        price = product.MIN1[P]
        oi    = product.MIN1[DataColumn.OPEN_INTEREST]
        d_price = price.diff(RF)
        d_oi    = oi.diff(RF)
        signal = np.where(
            d_oi > 0,
            np.sign(d_price),   # 持仓增，看价格方向
            0.0                  # 持仓减或不变，不判断方向
        )
        signal = pd.Series(signal, index=price.index)
        factor = signal.rolling(N).mean()
        factor = factor.fillna(0.0)
        return self.sync_signal(factor)
if __name__ == '__main__':
    ff = OiNetBuild()
    ff.clear_params()
    ff.add_params(F='1d', N='10d', RF='1d')
    ff.add_params(F='1d', N='5d',  RF='1d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
