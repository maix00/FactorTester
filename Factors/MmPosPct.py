import pandas as pd
import os, sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.products.Product import Product
from tools import DataColumn
from tools.factors.Factor import FactorFamily
from tools.parameters.Parameter import DataColumnParam, TimeDeltaParam
from typing import Sequence, Any

class MmPosPct(FactorFamily):  # 上涨天数占比（胜率）

    params = [
        DataColumnParam('P', DataColumn.CLOSE),
        TimeDeltaParam('WF', flag='pos', default_value='2h'),      # 时间窗口长度
        TimeDeltaParam('RF', flag='pos', default_value='5m'),      # 计算频率（Return Frequency）
    ]

    math_expr = '''
        \\begin{aligned}
            r_t &:= \\frac{P_t - P_{t-RF}}{P_{t-RF}}, \\\\[5pt]
            X_t &:= \\frac{1}{WF}\\sum_{t-WF \\leq s \\leq t} \\mathbf{1}_{r_s > 0}.
        \\end{aligned}
    '''

    def func(self, products: Sequence[Product], F: Any = pd.Timedelta('5m'),
             WF: Any = pd.Timedelta('2h'), RF: Any = pd.Timedelta('1D'),
             P: DataColumn = DataColumn.CLOSE, **kwargs) -> pd.DataFrame:
        factors = {}
        for product in products:
            ret = product.MIN1[P].pct_change(RF)
            pos_ratio = (ret > 0).rolling(WF).mean()
            factors[product] = product.MIN1.sync_signal(pos_ratio, F)
        return pd.concat(factors, axis=1)

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
    # ff.add_params(F='1d', RF='1d', WF='10d')
    ff.add_params(F='2d', RF='2d', WF='10d')

    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
    print(fft.products)