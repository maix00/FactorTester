# =============================================================================
# Factors/VlVolRatio.py
# 波动率比值因子（近期波动 / 远期波动）
#
# 近期波动率与远期波动率的比值，衡量波动率的趋势：
#   vol_s = std(ret, Ns)
#   vol_l = std(ret, Nl)
#   X_t = vol_s / vol_l
# 比值 > 1 表示近期波动放大（风险上升）；< 1 表示波动衰减（市场趋于平稳）。
# =============================================================================
import pandas as pd
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class VlVolRatio(FactorFamily):
    """
    波动率比值因子（近期波动率 / 远期波动率）。

    衡量波动率的时序趋势，大于1表示波动放大，小于1表示趋于平静。
    可结合方向性因子使用（放大时动量更可靠）。

    参数：
        P  (DataColumn) : 价格列，默认 CLOSE
        Ns (Timedelta)  : 短期波动率窗口，默认 5d
        Nl (Timedelta)  : 长期波动率窗口，默认 20d
        RF (Timedelta)  : 收益率步长，默认 1d
        F  (Timedelta)  : 输出信号频率
    """

    params = [
        DataColumnParam('P', DataColumn.CLOSE_ADJUSTED),
        WindowParam('Ns', default_value='5d'),
        WindowParam('Nl', default_value='20d'),
        WindowParam('RF', default_value='1d'),
    ]

    chinese_name = '量比（短长均量比）'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'VlVolRatio 是短长波动率比值因子，用短窗口波动率除以长窗口波动率，衡量市场波动是在快速放大还是逐渐收敛。',
        },
        {
            'title': '它在看什么',
            'body': '当短期波动显著高于长期波动时，比值会上升，说明风险环境正在升温；当短期波动低于长期背景时，比值会下降，说明市场进入相对平静状态。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '绝对波动水平有时不足以说明状态切换，真正重要的是当前波动相对历史背景的变化速度。短长波动率比正是在捕捉这种“波动 regime 的边际变化”，对识别突破、恐慌和冷却阶段都很有帮助。',
        },
        {
            'title': '使用提醒',
            'body': '如果长窗口过短，比值会失去“相对历史背景”的意义；若长窗口过长，又可能对结构性变化反应太慢。',
        },
        {
            'title': '反转信号',
            'body': '短/长期成交量比值因子的反转逻辑：（1）短期成交量相对长期均值急速放大（Ns/Nl 比值飙升），往往伴随价格的单次大波动——此类"量能冲顶"后若价格未能进一步推进，反转概率很高；（2）量比处于历史低位时，市场成交清淡，价格容易被操纵或出现技术性反弹；（3）量比和价格趋势背离——量缩但价格继续创新高，是趋势即将衰竭的经典信号。反转信号在以下情况更可靠：量比仅在单期急升而非持续放量；或量比急升时对应的价格变动明显低于历史同等放量时的涨幅（量效比下降）。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            r_t &:= \frac{P_t - P_{t-RF}}{P_{t-RF}} \\[4pt]
            \sigma_s(t) &:= \mathrm{RollingSTD}_{N_s}(r)_t,\quad
            \sigma_l(t) := \mathrm{RollingSTD}_{N_l}(r)_t \\[4pt]
            X_t &:= \frac{\mathrm{RollingSTD}_{N_s}(r)_t}{\mathrm{RollingSTD}_{N_l}(r)_t}
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, Ns: Any = pd.Timedelta('5d'),
                        Nl: Any = pd.Timedelta('20d'),
                        RF: Any = pd.Timedelta('1d'),
                        P: DataColumn = DataColumn.CLOSE_ADJUSTED, **kwargs) -> pd.Series:
        price   = product.MIN1[P]
        ret     = price.pct_change(RF)
        vol_s   = ret.rolling(Ns).std()
        vol_l   = ret.rolling(Nl).std().replace(0, float('nan'))
        factor  = vol_s / vol_l
        factor  = factor.fillna(1.0)
        return self.sync_signal(factor)
if __name__ == '__main__':
    ff = VlVolRatio()
    ff.clear_params()
    ff.add_params(F='1d', Ns='5d', Nl='20d', RF='1d')
    ff.add_params(F='1d', Ns='3d', Nl='10d', RF='1d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
