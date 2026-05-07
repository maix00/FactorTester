# =============================================================================
# Factors/VlYZ.py
# Yang-Zhang 波动率因子
#
# FactorFamily 表达式驱动版本。
# sigma_o^2  = Var(log(O_t / C_{t-1}), N)
# sigma_c^2  = Var(log(C_t / O_t), N)
# sigma_rs^2 = MA(RS_bar, N)      where RS_bar = hc*ho + lc*lo
# w = 0.34 / (1.34 + (n+1)/(n-1)), n = int(N / 1d)
# X = sqrt(sigma_o^2 + w * sigma_c^2 + (1-w) * sigma_rs^2)
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import FactorFamily
from tools.parameters import DataColumnParam, WindowParam
from tools.factors.FactorExpr import FactorExpr

class VlYZ(FactorFamily):
    """Yang-Zhang 波动率。"""


    @staticmethod
    def factor_expr():
        N = WindowParam('N', default_value='14d')
        H = DataColumnParam('H', default_value='HA')
        L = DataColumnParam('L', default_value='LA')
        O = DataColumnParam('O', default_value='OA')
        C = DataColumnParam('C', default_value='CA')
        eps = 1e-10

        h = H.shift(0)
        l = L.shift(0)
        o = O.shift(0)
        c = C.shift(0)

        # Overnight log-return: log(O_t / C_{t-1})
        log_oc_prev = (o / (c.shift(1) + eps)).log()
        # Intraday log-return: log(C_t / O_t)
        log_co = (c / (o + eps)).log()
        # RS bar: hc*ho + lc*lo
        ho = (h / (o + eps)).log()
        hc = (h / (c + eps)).log()
        lo = (l / (o + eps)).log()
        lc = (l / (c + eps)).log()
        rs_bar = hc * ho + lc * lo

        # Rolling variances
        sig_o2 = log_oc_prev.rolling_var(N).as_intermediate('SIG_O2')
        sig_c2 = log_co.rolling_var(N).as_intermediate('SIG_C2')
        sig_rs2 = rs_bar.rolling_mean(N).max(0.0).as_intermediate('SIG_RS2')

        # Weight: w = 0.34 / (1.34 + (n+1)/(n-1)), n = int(N/1d)
        # w is computed during evaluation because it depends on N/1d ratio
        # We use a DynamicWeight expression
        yz_var = (sig_o2 + _DynamicWeight(N) * sig_c2 + (1.0 - _DynamicWeight(N)) * sig_rs2).as_intermediate('SIG_YZ2')
        return yz_var.max(0.0).sqrt()

    desc = 'Yang-Zhang 波动率'
    description = """
## 这是什么
VlYZ 是 Yang-Zhang 波动率估计量，综合了隔夜跳空方差、日内开收方差和 RS 方差三项，是对 Garman-Klass 在有隔夜跳空时的改进。

## 它在看什么
分别量化三种波动来源：前收到今开的跳空幅度（隔夜风险）、今开到今收的方向性漂移（日内趋势）、日内高低极值的随机游走（日内噪声）。

## 为什么这个因子可能行得通
期货市场有夜盘，隔夜跳空是重要风险来源，而 GK/PK 估计量都忽略这部分。YZ 显式地捕捉了隔夜方差。

## 使用提醒
YZ 需要连续两个 Bar 的开盘价（计算隔夜收益），缺少数据时会出现较多 NaN。

## 反转信号
YZ 波动率的隔夜分量突然放大，往往意味着市场在非交易时段的信息冲击强烈。
"""


class _DynamicWeight(FactorExpr):
    """动态权重：w = 0.34 / (1.34 + (n+1)/(n-1))，其中 n = int(N / 1d)。

    继承 RollingOp 以复用 window 解析和 _resolve_expr_params 统一分发。

    求值时从参数字典中取 N 的解析值计算 n 和 w，返回标量。
    """
    def __init__(self, window_param):
        from tools.parameters.Parameter import Parameter
        self._window_param = window_param
        self.window = window_param  # 兼容 RollingOp 的 window 属性
        self._cached_value = None

    @property
    def dependencies(self):
        return set()

    @property
    def param_deps(self):
        from tools.parameters.Parameter import Parameter
        if isinstance(self._window_param, Parameter):
            return {self._window_param}
        return set()

    def _collect_params_ordered(self, seen, result):
        from tools.parameters.Parameter import Parameter
        if isinstance(self._window_param, Parameter) and self._window_param not in seen:
            seen.add(self._window_param)
            result.append(self._window_param)

    def evaluate(self, products, freq, source=None, cache=None):
        if self._cached_value is not None:
            return self._cached_value

        n_int = _resolve_bars_or_default(self._window_param, freq, 14)
        n = max(2, n_int)
        self._cached_value = 0.34 / (1.34 + (n + 1) / (n - 1))
        return self._cached_value

    @property
    def op_name(self):
        return "DYNW"

    def _to_latex(self, subst: dict | None = None):
        return "\\omega"

    def _get_alias(self):
        return "dynw"

    def __repr__(self):
        return f"DynamicWeight({self._window_param})"


def _resolve_bars_or_default(w, freq, default):
    """将 Timedelta 转为 bar 数，失败返回 default。"""
    try:
        from tools.factors.FactorExpr import _resolve_bars
        return _resolve_bars(w, freq)
    except Exception:
        return default


if __name__ == '__main__':
    ff = VlYZ()
