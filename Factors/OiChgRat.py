# =============================================================================
# Factors/OiChgRat.py
# 持仓量变动率因子
#
# 在过去 N 个 RF 周期内，持仓量的变动率：
#   X_t = (OI_t - OI_{t-N}) / OI_{t-N}
# 持仓量增加通常表示新资金进场，结合价格方向可判断多空力量。
# =============================================================================
import pandas as pd
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import WindowParam


class OiChgRat(FactorFamily):
    """
    持仓量变动率因子。

    计算 N 期前到现在持仓量的变化幅度。
    持仓增加（正值）代表新资金建仓，持仓减少（负值）代表平仓离场。

    参数：
        N  (Timedelta) : 回看窗口，默认 5d
        RF (Timedelta) : 单期步长，默认 1d
        F  (Timedelta) : 输出信号频率
    """

    params = [
        WindowParam('N',  default_value='5d'),
        WindowParam('RF', default_value='1d'),
    ]

    chinese_name = '持仓量变化率'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'OiChgRat 是持仓量变化率因子，用最近 N 期持仓量相对 N 期前的变化来衡量市场参与者是否在持续增仓或减仓。',
        },
        {
            'title': '它在看什么',
            'body': '持仓量上升通常意味着新的头寸在进入市场，持仓量下降则意味着旧头寸在退出。这个因子关注的不是成交有多活跃，而是未平仓合约总量到底在扩张还是收缩。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '在期货市场里，价格变化如果伴随持仓扩张，往往说明趋势背后有新增资金持续参与，趋势的可持续性更强；若价格变化伴随持仓收缩，则更像旧仓平仓带来的被动波动。持仓变化因此能提供比价格本身更贴近资金结构的信息。',
        },
        {
            'title': '使用提醒',
            'body': '持仓量的解释需要结合价格方向一起看。单独看持仓扩张并不能区分是多头增仓还是空头增仓。',
        },
        {
            'title': '反转信号',
            'body': '持仓量变化率因子的反转场景：（1）持仓量在高价位快速增加（多单持续增仓）后若价格停止上涨甚至开始下跌，往往是多头被套的信号，容易引发强制平仓和反转加速；（2）持仓量在低价位快速减少（空单持续平仓），若减仓后价格仍下跌，则空头平仓力量可能耗尽，下一步方向存疑；（3）价格与持仓量出现持续背离（价格上涨但持仓量连续萎缩），通常意味着做多参与度不足，上涨动能存疑。반转在以下情况更有效：市场持仓接近历史极端（过高或过低）；临近交割时持仓量集中平仓；宏观事件后市场共识转变引发单边大幅平仓。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            X_t &:= \frac{OI_t - OI_{t-N}}{OI_{t-N}}
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, N: Any = pd.Timedelta('5d'), RF: Any = pd.Timedelta('1d'),
                        **kwargs) -> pd.Series:
        oi = product.MIN1[DataColumn.OPEN_INTEREST]
        if isinstance(N, pd.Timedelta) and isinstance(RF, pd.Timedelta):
            steps = max(1, int(N / RF))
        else:
            steps = int(N) if not isinstance(N, pd.Timedelta) else 1
        chg_rat = oi.pct_change(steps)
        chg_rat = chg_rat.fillna(0.0)
        return self.sync_signal(chg_rat)
if __name__ == '__main__':
    ff = OiChgRat()
    ff.clear_params()
    ff.add_params(F='1d', N='5d',  RF='1d')
    ff.add_params(F='1d', N='10d', RF='1d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
