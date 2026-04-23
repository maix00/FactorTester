# =============================================================================
# Factors/MmUpRatio.py
# 涨幅占比因子（上行强度因子）
#
# 在过去 N 个 RF 周期内，累计上涨幅度与总涨跌变动幅度的比值：
#   r_t = (P_t - P_{t-RF}) / P_{t-RF}
#   X_t = Σmax(r_s,0) / Σ|r_s|，s ∈ [t-N+1, t]
# 值域 [0, 1]：接近 1 表示几乎全部变动均为上涨，接近 0 表示持续下跌。
# =============================================================================
import pandas as pd
import os, sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import DataColumnParam, TimeDeltaParam, WindowParam
from typing import Any

class MmUpRatio(FactorFamily):
    """
    涨幅占比因子：过去 N 日内，累计上涨幅度与总累计涨跌变动幅度的比值。

    .. math::
        r_t = \\frac{P_t - P_{t-RF}}{P_{t-RF}}

        X_t = \\frac{\\sum_{s=t-N+1}^{t} \\max(r_s, 0)}{\\sum_{s=t-N+1}^{t} |r_s|}
    """

    params = [
        DataColumnParam('P', DataColumn.CLOSE),          # 价格列
        WindowParam('N', default_value='5d'),             # 窗口长度
        WindowParam('RF', default_value='1d'),            # 收益率计算频率
    ]

    chinese_name = '上涨贡献占比'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'MmUpRatio 是上涨贡献占比因子，计算最近窗口里正收益之和占绝对收益总和的比例。',
        },
        {
            'title': '它在看什么',
            'body': '如果价格上涨主要来自许多正向波动，因子接近 1；如果下跌波动占主导，因子接近 0；若涨跌力量相对均衡，则因子处在中间区域。它比“上涨次数占比”更进一步，因为它同时考虑了涨跌的幅度。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '一个真正健康的趋势，通常不仅上涨次数多，而且上涨贡献在总波动里占据更大份额。这个因子因此可以描述行情的“方向质量”，区分平滑推进的走势和剧烈拉锯的走势。',
        },
        {
            'title': '使用提醒',
            'body': '若窗口内出现单次极端大波动，因子会被明显拉偏；因此它适合和稳健的波动率或去极值处理一起使用。',
        },
        {
            'title': '反转信号',
            'body': '上涨贡献占比在以下情况更容易出现反转：（1）因子值连续多期维持高位且成交量下降——动量质量表面强但缺乏增量力量；（2）单期出现极端大阳线把因子值推至高位，但之后样本重新分布，因子会快速回落；（3）与上涨次数占比（MmPosPct）产生背离时：上涨贡献高但上涨次数不多，说明行情由少数大波动驱动，可持续性存疑。反转在窗口较短、市场波动率高的环境中更为频繁；长周期因子因为平滑效果，反转更滞后但也更有意义。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            r_t &:= \frac{P_t - P_{t-RF}}{P_{t-RF}} \\[5pt]
            X_t &:= \frac{\sum_{s=t-N+1}^{t} \max(r_s, 0)}{\sum_{s=t-N+1}^{t} |r_s|}
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, N: Any = pd.Timedelta('5d'), RF: Any = pd.Timedelta('1d'),
                        P: DataColumn = DataColumn.CLOSE, **kwargs) -> pd.Series:
        """
        计算涨幅占比因子。

        Parameters
        ----------
        product : Product
            产品对象
        F : Any, default=pd.Timedelta('1d')
            输出频率
        N : Any, default=pd.Timedelta('5d')
            滚动窗口长度
        RF : Any, default=pd.Timedelta('1d')
            收益率计算频率
        P : DataColumn, default=DataColumn.CLOSE
            使用的价格列

        Returns
        -------
        pd.Series
            按频率 F 同步后的因子序列
        """
        # 1. 计算收益率序列（基于1分钟数据）
        price = product.MIN1[P]
        ret = price.pct_change(RF)                     # 收益率 r_t

        # 2. 计算滚动窗口内的正向和与绝对值和
        pos_sum = ret.clip(lower=0).rolling(N).sum()    # 累计上涨幅度
        abs_sum = ret.abs().rolling(N).sum()            # 总累计涨跌变动幅度

        # 避免除零
        ratio = pos_sum / abs_sum
        ratio = ratio.fillna(0.0)                      # 窗口内无数据时填充0

        # 3. 同步到目标频率并返回
        return self.sync_signal(ratio)
if __name__ == '__main__':
    # 示例：创建因子实例并添加参数组合
    ff = MmUpRatio()

    ff.clear_params()

    # 参数组合说明：
    # - 通常因子窗口 N 应不小于输出频率 F 的周期，避免细粒度同步整数天窗口时的潜在问题。
    # - 若需要输出高频因子（如15m），建议 N 使用交易时段内的自然时长（如 '6h40m'）或指定 K 线数量。
    # - 以下组合以日频输出为主，窗口使用自然日，符合常见回测场景。
    ff.add_params(F='1d', N='5d', RF='1d')
    ff.add_params(F='1d', N='10d', RF='1d')
    ff.add_params(F='1d', N='5d', RF='5m')
    ff.add_params(F='1d', N='10d', RF='1h')
    ff.add_params(F='1h', N='6h', RF='5m')      # 小时输出，窗口使用6小时（非整数天）
    ff.add_params(F='15m', N='2h', RF='5m')     # 15分钟输出，窗口使用2小时（非整数天）

    # 测试（需要实际数据环境）
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
    print(fft.products)