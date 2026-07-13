"""CashPoolModule — owns cash-pool balances and future FX movements.

StrategyBook declares which Ledger belongs to which cash pool; this module
stores the money. A private cash account is represented the same way as a
shared account: a cash pool that happens to contain one ledger. Cross-currency
movement must be represented as explicit FX trade events, not by sharing one
cash pool across currencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from tools.testers.backtest.engines.native.config import CashPoolConfig
from tools.testers.backtest.engines.native.guarded_dict import GuardedDict
from tools.testers.backtest.engines.native.ledger import Ledger
from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef


@dataclass
class CashPoolStore:
    cash_by_pool: dict[str, Any] = field(default_factory=lambda: GuardedDict(label="CashPoolStore.cash_by_pool"))
    config_by_pool: dict[str, CashPoolConfig] = field(default_factory=dict)
    _flow_contract_audit: tuple[Any, object] | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.cash_by_pool, GuardedDict):
            self.cash_by_pool = GuardedDict(self.cash_by_pool, label="CashPoolStore.cash_by_pool")

    def set_cash(self, pool_id: str, cash: Any, ref: FieldRef[Any]) -> None:
        audit = getattr(self, "_flow_contract_audit", None)
        if audit is not None:
            ctx, token = audit
            ctx.record_external_contract_write(ref, token)
        with self.cash_by_pool.unguarded_write():  # type: ignore[attr-defined]
            self.cash_by_pool[str(pool_id)] = cash

    def set_guarded_writes_enabled(self, enabled: bool) -> None:
        setter = getattr(self.cash_by_pool, "set_guarded_writes_enabled", None)
        if callable(setter):
            setter(enabled)

    def enter_flow_contract_audit(self, ctx: Any, token: object) -> tuple[Any, object] | None:
        previous = getattr(self, "_flow_contract_audit", None)
        self._flow_contract_audit = (ctx, token)
        return previous

    def restore_flow_contract_audit(self, previous: tuple[Any, object] | None) -> None:
        self._flow_contract_audit = previous


class CashPoolModule(ExecutableModule):
    key: ClassVar[str] = "cash_pool"
    label: ClassVar[str] = "现金池"
    order: ClassVar[int] = 158

    cash: ClassVar[FieldRef[Any]] = FieldRef("cash")
    initial_capital_major: ClassVar[FieldRef[float]] = FieldRef("initial_capital_major")
    base_currency: ClassVar[FieldRef[str]] = FieldRef("base_currency")
    currency_conversion_fee_rate: ClassVar[FieldRef[float]] = FieldRef("currency_conversion_fee_rate")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "initial_capital_major": FieldDefinition(
            public=True, label="初始资金", control_template="number", default=100_000_000.0, tab="capital",
            chip_template="初始资金: {value}", tab_label="资金", tab_order=50,
        ),
        "base_currency": FieldDefinition(
            public=True, label="币种", control_template="select", default="CNY", tab="capital",
            chip_template="币种: {value}", tab_label="资金", tab_order=50,
        ),
        "currency_conversion_fee_rate": FieldDefinition(
            public=True, label="换汇费率", control_template="number", default=0.0, tab="capital",
            minimum=0.0, step=0.000001,
            chip_template="换汇费率: {value}", tab_label="资金", tab_order=50,
        ),
    }


def cash_pool_store_for(state: object) -> CashPoolStore:
    store = getattr(state, "cash_pool_store", None)
    if store is None:
        store = CashPoolStore()
        setattr(state, "cash_pool_store", store)
    return store


def cash_for_ledger(state: object, ledger_state: object):
    from tools.testers.backtest.modules.strategy_book import cash_pool_id_for_ledger

    store = cash_pool_store_for(state)
    pool_id = cash_pool_id_for_ledger(state, ledger_state)
    return store.cash_by_pool.get(pool_id)


def cash_pool_config_for_ledger(state: object, ledger: str | Ledger | object) -> CashPoolConfig:
    from tools.testers.backtest.modules.strategy_book import cash_pool_id_for_ledger

    return cash_pool_store_for(state).config_by_pool.get(
        cash_pool_id_for_ledger(state, ledger),
        CashPoolConfig(),
    )


def register_cash_pool_config(
    state: object,
    cash_pool_id: str,
    config: CashPoolConfig,
    *,
    source: str,
) -> None:
    store = cash_pool_store_for(state)
    existing = store.config_by_pool.get(str(cash_pool_id))
    if existing is None:
        store.config_by_pool[str(cash_pool_id)] = config
        return
    merged = _merge_compatible_cash_pool_config(existing, config, cash_pool_id=str(cash_pool_id), source=source)
    store.config_by_pool[str(cash_pool_id)] = merged


def cash_pool_config_from_strategy_config(strategy_config: Any) -> CashPoolConfig:
    return CashPoolConfig(
        initial_capital_major=_optional_float(strategy_config.get(CashPoolModule.initial_capital_major, None)),
        base_currency=_optional_str(strategy_config.get(CashPoolModule.base_currency, None)),
        currency_conversion_fee_rate=_optional_float(
            strategy_config.get(CashPoolModule.currency_conversion_fee_rate, None)
        ),
    )


def ensure_cash_pool_config_for_strategy_ledger(
    state: object,
    strategy_config: Any,
    ledger: str | Ledger | object,
    *,
    source: str,
) -> CashPoolConfig:
    from tools.testers.backtest.modules.strategy_book import cash_pool_id_for_ledger

    pool_id = cash_pool_id_for_ledger(state, ledger)
    config = cash_pool_config_from_strategy_config(strategy_config)
    register_cash_pool_config(state, pool_id, config, source=source)
    return cash_pool_store_for(state).config_by_pool.get(pool_id, CashPoolConfig())


def set_cash_for_ledger_pool(state: object, ledger_state: object, cash: object) -> None:
    from tools.testers.backtest.modules.strategy_book import cash_pool_id_for_ledger

    cash_pool_store_for(state).set_cash(cash_pool_id_for_ledger(state, ledger_state), cash, CashPoolModule.cash)


def _merge_compatible_cash_pool_config(
    left: CashPoolConfig,
    right: CashPoolConfig,
    *,
    cash_pool_id: str,
    source: str,
) -> CashPoolConfig:
    values: dict[str, Any] = {}
    for key in ("initial_capital_major", "base_currency", "currency_conversion_fee_rate"):
        left_value = getattr(left, key)
        right_value = getattr(right, key)
        if left_value is None:
            values[key] = right_value
            continue
        if right_value is None or right_value == left_value:
            values[key] = left_value
            continue
        hint = (
            " -- a shared cash pool is one pool of money in one currency; "
            "route cross-currency movement through FX trade events instead."
            if key == "base_currency"
            else ""
        )
        raise ValueError(
            f"cash_pool {cash_pool_id!r} receives conflicting {key}: "
            f"{left_value!r} vs {right_value!r} from {source}{hint}"
        )
    return CashPoolConfig(**values)


def _optional_str(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    return float(value)  # type: ignore[arg-type]
