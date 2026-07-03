"""Clearing-rule defaults declared by the LocalCNFutures data source."""

from __future__ import annotations

from tools.traderules import (
    ExchangeClearingRule,
    ExchangeTradingRule,
    register_exchange_clearing_rule,
    register_exchange_trading_rule,
)


_LOCAL_CNFUTURES_EXCHANGES: tuple[str, ...] = (
    "DCE",
    "CZCE",
    "INE",
    "SHFE",
    "CFFEX",
    "GFEX",
)

_LOCAL_CNFUTURES_DEFAULT_FIELDS: dict[str, object] = {
    # 中国期货公开保证金/手续费/逐日盯市公式通常以合约总额口径表达；
    # 具体历史费率和乘数仍由 FieldHistory/OpenCTP 等更细字段覆盖。
    "CostBasisMethod": "DailyMarkToMarket",
    "MoneyCalculationPolicy": "aggregate",
}

_LOCAL_CNFUTURES_FIELD_LABELS: dict[str, str] = {
    "CostBasisMethod": "成本法",
    "MoneyCalculationPolicy": "金额计算口径",
}

_LOCAL_CNFUTURES_FIELD_NOTES: dict[str, str] = {
    "CostBasisMethod": (
        "中国期货默认采用逐日盯市：日终按结算价重估持仓、释放旧保证金、占用新保证金，"
        "并将当日盈亏划入现金/结算准备金。"
    ),
    "MoneyCalculationPolicy": (
        "LocalCNFutures 默认按合约/持仓总额公式计算保证金、手续费和逐日盯市盈亏，"
        "再在现金/保证金账户落账时按币种精度处理；产品级或合约级历史字段优先。"
    ),
}


def register_local_cnfutures_exchange_rules() -> None:
    for exchange_id in _LOCAL_CNFUTURES_EXCHANGES:
        register_exchange_clearing_rule(
            ExchangeClearingRule(
                exchange_id=exchange_id,
                fields=_LOCAL_CNFUTURES_DEFAULT_FIELDS,
                provider="LocalCNFutures",
                label="中国期货交易所默认清算规则",
                note=(
                    "交易所级默认值只补足产品/合约历史字段缺口；费率、乘数、保证金率等"
                    "时间变化字段仍由 FieldHistory/OpenCTP 等更细来源覆盖。"
                ),
                field_labels=_LOCAL_CNFUTURES_FIELD_LABELS,
                field_notes=_LOCAL_CNFUTURES_FIELD_NOTES,
            )
        )
        register_exchange_trading_rule(
            ExchangeTradingRule(
                exchange_id=exchange_id,
                tradability_policy="valid_close_price",
                provider="LocalCNFutures",
                label="中国期货交易所默认交易状态规则",
                note=(
                    "当前 LocalCNFutures 以事件时点是否存在有效 close 估值价格作为最小可交易门槛；"
                    "后续可由停牌、涨跌停、只可平仓等更细交易状态字段覆盖。"
                ),
            )
        )


register_local_cnfutures_exchange_rules()
