"""Clearing-rule defaults declared by the LocalCNFutures data source."""

from __future__ import annotations

from tools.traderules import ExchangeClearingRule, register_exchange_clearing_rule


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
    "MoneyCalculationPolicy": "aggregate",
}


def register_local_cnfutures_exchange_rules() -> None:
    for exchange_id in _LOCAL_CNFUTURES_EXCHANGES:
        register_exchange_clearing_rule(
            ExchangeClearingRule(
                exchange_id=exchange_id,
                fields=_LOCAL_CNFUTURES_DEFAULT_FIELDS,
                provider="LocalCNFutures",
                label="中国期货交易所默认清算规则",
            )
        )


register_local_cnfutures_exchange_rules()
