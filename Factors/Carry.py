"""Annualized futures term-carry factor.

The factor is a signal only.  Position state and paired-leg execution belong
to ``TermCarryStrategyModule``.
"""

from tools.factors import FactorFamily, term_carry_annualized
from tools.parameters import DataColumnParam


class Carry(FactorFamily):
    """Annualized rank-0 versus rank-1 futures curve carry."""

    @staticmethod
    def factor_expr():
        price = DataColumnParam("P", default_value="C")
        return term_carry_annualized(0, 1, price)

    desc = "年化期限 Carry"
    description = """
## 定义
使用同一品种期限结构中排名 0 和排名 1 的合约，计算
`(近月价格 / 远月价格 - 1) * 365 / 到期日间隔`。

## 方向
正值表示 backwardation，负值表示 contango。

## 边界
这是信号，不持有仓位。双腿方向、入场、退出、换月和权重由
Term Carry 策略负责。期限结构必须按信号时点可见信息构造。
"""


if __name__ == "__main__":
    family = Carry()
    family.add_params(**{"P": "C", "$F": "1d"})
