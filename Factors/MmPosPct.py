# =============================================================================
# Factors/MmPosPct.py
# 上涨天数占比因子（胜率因子）
#
# 在过去 WF 个周期内，统计收益率为正的周期占比：
#   r_t = (P_t - P_{t-RF}) / P_{t-RF}
#   X_t = (1/WF) * Σ_{s=t-WF+1}^{t} 1_{r_s > 0}
# =============================================================================
import pandas as pd
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import DataColumnParam, WindowParam

class MmPosPct(FactorFamily):
    """
    上涨天数占比因子（胜率因子）。

    统计过去 WF 个 RF 周期内价格上涨的比例，值域 [0, 1]。
    高值表示近期持续上涨，低值表示持续下跌。

    参数：
        P  (DataColumn) : 价格列，默认 CLOSE
        WF (Timedelta)  : 滚动窗口长度（计算占比的回溯期）
        RF (Timedelta)  : 单期收益率计算频率
        F  (Timedelta)  : 输出信号频率（继承自 FactorFamily）
    """

    params = [DataColumnParam('P', DataColumn.CLOSE), WindowParam('WF', default_value='10m'), WindowParam('RF', default_value='1m')]

    chinese_name = '上涨占比（胜率）'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'MmPosPct 是一个上涨占比因子，统计最近窗口中正收益出现的比例。它关注的是“涨的次数”，而不是“总共涨了多少”。',
        },
        {
            'title': '它在看什么',
            'body': '如果一个市场在过去一段时间里多数周期都收正，即使单次涨幅不大，因子也会偏高；若多数周期收负，则因子偏低。它刻画的是走势的连续性和胜率特征。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '稳定趋势往往表现为很多小幅同向推进，而不是少数几次大涨把总收益堆出来。上涨占比因此能区分“路径平滑的强势”与“靠极少数大阳线撑出来的表面强势”。在期货和高频场景里，这类路径质量信息往往比单纯累计收益更稳。',
        },
        {
            'title': '使用提醒',
            'body': '若样本窗口太短，胜率本身会很不稳定；若窗口太长，又可能掩盖市场已经切换状态的事实。',
        },
        {
            'title': '反转信号',
            'body': '上涨占比因子出现以下情况时，反转信号的可信度上升：（1）连续多个窗口上涨占比维持在高位（如 >0.7），却伴随成交量持续下滑——胜率高但资金不再增量支持，动能可能耗尽；（2）上涨占比突然从高位快速下滑至中位以下，常意味着多头被迫减仓或趋势破坏；（3）窗口内收益分布极度集中于少数几次大涨而非均匀分布，总胜率数字本身可能具有误导性。反转在高频（如分钟级 RF）场景中更为常见，胜率高但持续时间短；日线级别的上涨占比持续性更强，反转相对更滞后。',
        },
    ]

    math_expr = '''
        \\begin{aligned}
            r_t &:= \\frac{P_t - P_{t-RF}}{P_{t-RF}}, \\\\[5pt]
            X_t &:= \\frac{1}{WF}\\sum_{t-WF \\leq s \\leq t} \\mathbf{1}_{r_s > 0}.
        \\end{aligned}
    '''

    def func_timeseries(self, product: Product, WF: Any = 1, RF: Any = 1, P: DataColumn = DataColumn.CLOSE, **kwargs):
        """
        计算单品种上涨天数占比因子。

        参数：
            product : 品种对象
            F       : 输出信号频率
            WF      : 滚动窗口大小
            RF      : 单期收益率计算步长
            P       : 价格列

        返回：
            按频率 F 同步后的 pd.Series
        """
        # 计算 RF 步长的收益率
        ret = product.MIN1[P].pct_change(RF)
        # 在 WF 窗口内统计收益率 > 0 的比例
        pos_ratio = (ret > 0).rolling(WF).mean()  # 反转逻辑由全局参数 $D 控制
        # 对齐到信号时间点并返回
        return self.sync_signal(pos_ratio)
if __name__ == '__main__':
    ff = MmPosPct()

    ff.clear_params()
    # ff.add_params(F='5m', RF='1m', WF='5m')
    # ff.add_params(F='15m', RF='1m', WF='15m')
    # ff.add_params(F='15m', RF='5m', WF='15m')
    # ff.add_params(F='30m', RF='5m', WF='30m')
    # ff.add_params(F='1d', RF='1d', WF='1d')
    # ff.add_params(F='1d', RF='10min', WF='1d')
    # ff.add_params(F='2d', RF='1d', WF='2d')
    # ff.add_params(F='2d', RF='10min', WF='2d')
    # ff.add_params(F='10d', RF='2d', WF='10d')
    ff.add_params(F='1d', RF='1d', WF='10d')
    # ff.add_params(F='2d', RF='2d', WF='10d')

    fft = ff.test(start_calc_point='2024-02-03 09:00:00', timezone='Asia/Shanghai')
    # print(fft.products)