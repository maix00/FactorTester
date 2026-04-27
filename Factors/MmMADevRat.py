# =============================================================================
# Factors/MmMADevRat.py
# 均线偏离比值因子
#
# 计算过去 N 期简单移动平均与当前价格的比值的相反数：
#   MA_t(N) = (1/N) * Σ_{i=0}^{N-1} P_{t-i}
#   X_t = -MA_t(N) / P_t
# 值越大（MA/P 越小）表示价格越高于均线，即上涨动量越强。
# =============================================================================
import pandas as pd
import os, sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import DataColumnParam, TimeDeltaParam
from typing import Any

class MmMADevRat(FactorFamily): # Momemtum Moving Average Deviation Ratio
    """
    均线偏离比值因子：过去 N 日的移动平均与收盘价比值的相反数。

    .. math::
        X_t = -\\frac{MA_t(N)}{P_t}, \\quad MA_t(N) = \\frac{1}{N}\\sum_{i=0}^{N-1} P_{t-i}
    """

    params = [
        DataColumnParam('P', DataColumn.CLOSE_ADJUSTED),          # 价格列
        TimeDeltaParam('N', flag='pos', default_value='5d'),   # 移动平均窗口长度
    ]

    chinese_name = '均线偏离度'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'MmMADevRat 是一个均线偏离度因子，用来衡量当前价格相对滚动均线的偏离程度。',
        },
        {
            'title': '它在看什么',
            'body': '当价格显著高于均线时，说明市场当前交易重心高于过去一段时间的平均水平；当价格显著低于均线时，则说明市场重心下移。归一化后的偏离度能帮助比较不同价格水平资产的相对强弱。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '均线常被看作局部均衡价格。价格持续偏离均线，通常意味着一侧资金在更主动地推动价格离开均衡位置。若市场处于趋势状态，这种偏离可能继续扩大；若市场处于均值回归状态，这种偏离也常提示回归压力。',
        },
        {
            'title': '使用提醒',
            'body': '这个因子单独使用时，容易混淆“强趋势中的合理偏离”和“短期过度拉伸”。如果要直接用于交易，最好配合趋势持续性或波动率环境来判断。',
        },
        {
            'title': '反转信号',
            'body': '均线偏离度类因子的反转逻辑最为直接：当价格相对均线偏离过大时，均值回归压力上升。反转在以下情况更有效：（1）偏离度处于历史高/低分位（如超过 1.5 倍历史标准差）；（2）宽基指数与个股或个品种偏离度同向极端——系统性失衡往往触发更强回归；（3）短周期 RF 对应的偏离比长周期 N 更容易回归，时效性更强。趋势市中，均线偏离可以持续堆积，单独用偏离度做反转时建议设置最大持有期或结合波动率环境过滤。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            X_t &:= -\frac{\mathrm{RollingMean}_{N}(P)_t}{P_t}
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, N: Any = pd.Timedelta('5d'),
                        P: DataColumn = DataColumn.CLOSE_ADJUSTED, **kwargs) -> pd.Series:
        """
        计算均线偏离比值因子。

        Parameters
        ----------
        product : Product
            产品对象
        F : Any, default=pd.Timedelta('1d')
            输出频率
        N : Any, default=pd.Timedelta('5d')
            移动平均窗口长度
        P : DataColumn, default=DataColumn.CLOSE_ADJUSTED
            使用的价格列

        Returns
        -------
        pd.Series
            按频率 F 同步后的因子序列
        """
        # 1. 获取价格序列（1分钟分辨率）
        price = product.MIN1[P]

        # 2. 计算滚动窗口内的简单移动平均
        ma = price.rolling(N).mean()

        # 3. 计算 -MA/P
        ratio = -ma / price

        # 4. 处理无穷大或缺失值（例如价格为零时）
        ratio = ratio.replace([float('inf'), -float('inf')], float('nan')).fillna(0.0)

        # 5. 同步到目标频率并返回
        return self.sync_signal(ratio)
if __name__ == '__main__':
    ff = MmMADevRat()

    ff.clear_params()

    # 参数组合示例
    ff.add_params(F='1d', N='5d')           # 日频输出，5日均线偏离
    ff.add_params(F='1d', N='10d')          # 日频输出，10日均线偏离
    ff.add_params(F='1h', N='5d')           # 小时频输出，5日均线偏离（每个小时计算一次）
    ff.add_params(F='1d', N='20d')          # 日频输出，20日均线偏离
    ff.add_params(F='15m', N='2h')          # 15分钟输出，2小时均线偏离（非整数天窗口）

    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
    print(fft.products)