# =============================================================================
# Factors/MmRSI.py
# 相对强弱指数因子（RSI）
#
# 在过去 N 个 RF 周期内，计算 RSI：
#   r_t = (P_t - P_{t-RF}) / P_{t-RF}
#   RS_t = Σ max(r_s, 0) / Σ |min(r_s, 0)|，s ∈ [t-N+1, t]
#   X_t = RS_t / (1 + RS_t)  ∈ [0, 1]
# 高值表示近期上涨动能强，低值表示下跌动能强。
# =============================================================================
import pandas as pd
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class MmRSI(FactorFamily):
    """
    相对强弱指数因子（RSI）。

    在过去 N 个 RF 周期内，计算上涨平均幅度和下跌平均幅度的比值：
      RS  = avg_gain / avg_loss
      RSI = RS / (1 + RS)

    参数：
        P  (DataColumn) : 价格列，默认 CLOSE
        N  (Timedelta)  : 滚动窗口长度
        RF (Timedelta)  : 单期收益率计算步长
        F  (Timedelta)  : 输出信号频率
    """

    params = [
        DataColumnParam('P', DataColumn.CLOSE_ADJUSTED),
        WindowParam('N', default_value='14d'),
        WindowParam('RF', default_value='1d'),
    ]

    chinese_name = '相对强弱指数'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'MmRSI 是相对强弱指标类因子，用上涨幅度与下跌幅度的相对比例来衡量近期价格是更偏向持续抬升，还是更偏向持续走弱。',
        },
        {
            'title': '它在看什么',
            'body': '它不是单纯看累计收益，而是把正向变化和负向变化分开统计，再计算二者的相对强弱。因此，一个总收益不大但连续小涨的市场，RSI 仍可能很高。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': 'RSI 抓的是“上涨力量是否系统性压过下跌力量”。在趋势环境中，这反映了买盘主导；在超买超卖分析中，极端 RSI 也常被当成拥挤和透支的信号。它因此兼具趋势和反转两种解释空间。',
        },
        {
            'title': '使用提醒',
            'body': 'RSI 的解释高度依赖市场状态。强趋势里高 RSI 可能意味着趋势健康；震荡市场里高 RSI 反而更像短期过热。',
        },
        {
            'title': '反转信号',
            'body': 'RSI 因子先天就兼具趋势和反转两种解读，关键在于市场状态：（1）RSI 进入超买区（>70）或超卖区（<30）后，在震荡市中是经典反转信号；（2）顶/底背离是 RSI 反转最有效的形态：价格创新高但 RSI 未创新高，或价格创新低但 RSI 未创新低；（3）超买后 RSI 无法继续向上（连续三根出现高位盘整），往往是下跌启动的前兆。反转在以下情况更有效：市场近期波动率处于历史中高位（均值回归力量更强）；无明确单边利多/利空宏观环境；成交量在超买/超卖处快速萎缩。强趋势期 RSI 可长期维持极端值，此时反转信号很容易被打爆。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            r_t &:= \frac{P_t - P_{t-RF}}{P_{t-RF}} \\[5pt]
            RS_t &:= \frac{\sum_{s} \max(r_s,0)}{\sum_{s} |\min(r_s,0)|} \\[5pt]
            X_t &:= \frac{RS_t}{1 + RS_t}
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, N: Any = pd.Timedelta('14d'), RF: Any = pd.Timedelta('1d'),
                        P: DataColumn = DataColumn.CLOSE_ADJUSTED, **kwargs) -> pd.Series:
        price = product.MIN1[P]
        ret = price.pct_change(RF)
        gain = ret.clip(lower=0).rolling(N).mean()
        loss = (-ret).clip(lower=0).rolling(N).mean()
        rs = gain / loss.replace(0, float('nan'))
        rsi = rs / (1 + rs)
        rsi = rsi.fillna(0.5)
        return self.sync_signal(rsi)
if __name__ == '__main__':
    ff = MmRSI()
    ff.clear_params()
    ff.add_params(F='1d', N='14d', RF='1d')
    ff.add_params(F='1d', N='7d', RF='1d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
