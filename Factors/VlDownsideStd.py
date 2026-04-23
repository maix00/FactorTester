# =============================================================================
# Factors/VlDownsideStd.py
# 下行波动率因子（Downside Deviation）
#
# 只统计负收益部分的滚动标准差，即半标准差：
#   X_t = std({r_s | r_s < 0}, N)
# 与普通波动率（VlRetStd）的比值可衡量下行风险相对总风险的占比。
# =============================================================================
import pandas as pd
import numpy as np
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class VlDownsideStd(FactorFamily):
    """
    下行波动率因子（Downside Standard Deviation）。

    仅计算负收益的标准差（半标准差），衡量下行风险。
    高值表示经常出现大幅下跌；低值表示下行冲击小。

    参数：
        P  (DataColumn) : 价格列，默认 CLOSE
        N  (Timedelta)  : 滚动窗口，默认 20d
        RF (Timedelta)  : 收益率步长，默认 1d
        F  (Timedelta)  : 输出信号频率
    """

    params = [
        DataColumnParam('P', DataColumn.CLOSE),
        WindowParam('N',  default_value='20d'),
        WindowParam('RF', default_value='1d'),
    ]

    chinese_name = '下行波动率'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'VlDownsideStd 是下行波动率因子，只统计负收益部分的波动强度，用来专门刻画“坏波动”而不是全部波动。',
        },
        {
            'title': '它在看什么',
            'body': '如果最近窗口里的负收益更频繁、更剧烈，下行标准差就会升高；若负收益较少或较温和，则因子较低。它强调的是下跌风险聚集程度。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '市场参与者通常对下跌风险更敏感，因此下行波动往往比对称波动更能代表风险厌恶、止损压力和流动性脆弱性。很多时候，未来收益和风险补偿与“坏波动”关系比与总波动关系更紧。',
        },
        {
            'title': '使用提醒',
            'body': '在长期单边上涨市场中，下行样本可能偏少，统计量会变得不稳定。',
        },
        {
            'title': '反转信号',
            'body': '下行波动率因子与反转的关联：（1）下行波动率急速扩大（集中大幅下跌）后，市场常常出现超卖反弹——恐慌性抛售后买盘重新入场；（2）下行波动率高但均值收益接近 0（不创新低）——与之前的急跌相比上涨阻力减小，反转时机更接近；（3）下行波动率明显高于上行波动率（不对称），说明市场参与者普遍处于恐慌状态，这类状态历史上常为阶段底部。反转在以下情况更有效：下行波动率处于数月高点且成交量开始萎缩；多个资产的下行波动率同步飙升（系统性恐慌后的反弹通常更有力）。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            X_t &:= \sqrt{\frac{1}{N}\sum_{s:\,r_s < 0} r_s^2}
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, N: Any = pd.Timedelta('20d'), RF: Any = pd.Timedelta('1d'),
                        P: DataColumn = DataColumn.CLOSE, **kwargs) -> pd.Series:
        price = product.MIN1[P]
        ret = price.pct_change(RF)
        neg_ret = ret.clip(upper=0)  # 非负归零，仅保留负值

        def _downside_std(x: np.ndarray) -> float:
            sq_mean = (x ** 2).mean()
            return float(np.sqrt(sq_mean)) if sq_mean > 0 else 0.0

        factor = neg_ret.rolling(N).apply(_downside_std, raw=True)
        factor = factor.fillna(0.0)
        return self.sync_signal(factor)
if __name__ == '__main__':
    ff = VlDownsideStd()
    ff.clear_params()
    ff.add_params(F='1d', N='20d', RF='1d')
    ff.add_params(F='1d', N='10d', RF='1d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
