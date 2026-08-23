"""CashPoolModule — owns account balances grouped by cash pool.

StrategyBook declares which Ledger belongs to which cash pool; this module
stores each ledger's money independently. A cash pool supplies the common
valuation currency and buying-power boundary; it never makes different account
currencies share one ``DataMoney`` object.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, ClassVar

from tools.data.types.currency import FxRateProvider, default_fx_rate_provider, normalize_currency
from tools.testers.backtest.engines.native.config import CashPoolConfig
from tools.testers.backtest.engines.native.guarded_dict import GuardedDict
from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef


@dataclass
class CashPoolStore:
    cash_by_ledger: dict[str, Any] = field(default_factory=lambda: GuardedDict(label="CashPoolStore.cash_by_pool"))
    reserve_by_pool: dict[str, Any] = field(default_factory=lambda: GuardedDict(label="CashPoolStore.reserve_by_pool"))
    config_by_pool: dict[str, CashPoolConfig] = field(default_factory=dict)
    fx_rate_cache: dict[tuple[str, str, Any, int], float] = field(default_factory=dict)
    fx_rate_provider: FxRateProvider = default_fx_rate_provider
    _flow_contract_audit: tuple[Any, object] | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.cash_by_ledger, GuardedDict):
            self.cash_by_ledger = GuardedDict(self.cash_by_ledger, label="CashPoolStore.cash_by_pool")
        if not isinstance(self.reserve_by_pool, GuardedDict):
            self.reserve_by_pool = GuardedDict(self.reserve_by_pool, label="CashPoolStore.reserve_by_pool")

    @property
    def cash_by_pool(self) -> dict[str, Any]:
        """Deprecated compatibility view for old guard/audit callers."""
        return self.cash_by_ledger

    def set_cash(self, ledger_id: str, cash: Any, ref: FieldRef[Any]) -> None:
        audit = getattr(self, "_flow_contract_audit", None)
        if audit is not None:
            ctx, token = audit
            ctx.record_external_contract_write(ref, token)
        with self.cash_by_ledger.unguarded_write():  # type: ignore[attr-defined]
            self.cash_by_ledger[str(ledger_id)] = cash

    def set_reserve(self, pool_id: str, cash: Any, ref: FieldRef[Any]) -> None:
        audit = getattr(self, "_flow_contract_audit", None)
        if audit is not None:
            ctx, token = audit
            ctx.record_external_contract_write(ref, token)
        with self.reserve_by_pool.unguarded_write():  # type: ignore[attr-defined]
            self.reserve_by_pool[str(pool_id)] = cash

    def set_guarded_writes_enabled(self, enabled: bool) -> None:
        for values in (self.cash_by_ledger, self.reserve_by_pool):
            setter = getattr(values, "set_guarded_writes_enabled", None)
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
        "cash": FieldDefinition(public=False, display_value_kind="cash"),
        "initial_capital_major": FieldDefinition(
            public=True, label="初始资金", editor="number", default=100_000_000.0, tab="capital",
            chip_template="初始资金: {value}", tab_label="资金", tab_order=50,
        ),
        "base_currency": FieldDefinition(
            public=True, label="资金池基准币种", editor="select", default="CNY", tab="capital",
            options=(
                ("CNY", "人民币（CNY）"),
                ("USD", "美元（USD）"),
                ("HKD", "港币（HKD）"),
                ("JPY", "日元（JPY）"),
                ("EUR", "欧元（EUR）"),
            ),
            chip_template="资金池基准币种: {value}", tab_label="资金", tab_order=50,
        ),
        "currency_conversion_fee_rate": FieldDefinition(
            public=True, label="换汇费率", editor="number", default=0.0, tab="capital",
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
    store = cash_pool_store_for(state)
    ledger_id = str(getattr(ledger_state, "ledger_id", getattr(ledger_state, "ledger", ledger_state)))
    return store.cash_by_ledger.get(ledger_id)


def set_cash_for_ledger_pool(state: object, ledger_state: object, cash: object) -> None:
    ledger_id = str(getattr(ledger_state, "ledger_id", getattr(ledger_state, "ledger", ledger_state)))
    cash_pool_store_for(state).set_cash(ledger_id, cash, CashPoolModule.cash)


def account_cash_or_zero(state: object, ledger_state: object):
    from tools.data.types.data_money import DataMoney

    cash = cash_for_ledger(state, ledger_state)
    if cash is not None:
        return cash
    return DataMoney.from_major(
        0.0,
        currency=normalize_currency(getattr(ledger_state, "base_currency", None)),
        use_minor_units=False,
    )


def cash_pool_cash_major(
    state: object,
    ledger_state: object,
    *,
    timestamp: Any,
    rate_provider: FxRateProvider | None = None,
    include_conversion_cost: bool = False,
) -> float:
    """Value every account balance in one pool's base currency.

    FX lookups are memoized by pool, currency pair, timestamp and provider so
    cash, margin and equity consumers share one causal observation.
    """
    from tools.testers.backtest.modules.strategy_book import cash_pool_id_for_ledger

    store = cash_pool_store_for(state)
    rate_provider = rate_provider or store.fx_rate_provider
    pool_id = cash_pool_id_for_ledger(state, ledger_state)
    config = store.config_by_pool.get(pool_id, CashPoolConfig())
    base_currency = normalize_currency(config.base_currency)
    fee_rate = max(0.0, float(config.currency_conversion_fee_rate or 0.0))
    balances = list(_cash_balances_for_pool(state, pool_id))
    reserve = store.reserve_by_pool.get(pool_id)
    if reserve is not None:
        balances.append(reserve)
    total = 0.0
    for cash in balances:
        amount = float(cash.to_major())
        currency = normalize_currency(cash.currency)
        if currency != base_currency:
            amount *= _cached_fx_rate(
                store, pool_id, currency, base_currency, timestamp, rate_provider,
            )
            if include_conversion_cost:
                amount -= abs(amount) * fee_rate
        total += amount
    return total


def cash_amount_to_pool_base(
    state: object,
    ledger_state: object,
    amount: float,
    *,
    timestamp: Any,
    rate_provider: FxRateProvider | None = None,
    include_conversion_cost: bool = False,
) -> float:
    """Convert one account-currency amount into its pool valuation currency."""
    from tools.testers.backtest.modules.strategy_book import cash_pool_id_for_ledger

    store = cash_pool_store_for(state)
    rate_provider = rate_provider or store.fx_rate_provider
    pool_id = cash_pool_id_for_ledger(state, ledger_state)
    config = store.config_by_pool.get(pool_id, CashPoolConfig())
    base_currency = normalize_currency(config.base_currency)
    currency = normalize_currency(getattr(ledger_state, "base_currency", base_currency))
    value = float(amount)
    if currency == base_currency:
        return value
    value *= _cached_fx_rate(
        store, pool_id, currency, base_currency, timestamp, rate_provider,
    )
    if include_conversion_cost:
        value -= abs(value) * max(0.0, float(config.currency_conversion_fee_rate or 0.0))
    return value


def cash_pool_money(state: object, ledger_state: object, *, timestamp: Any, include_conversion_cost: bool = False):
    """Return the pool cash value as base-currency ``DataMoney``."""
    from tools.data.types.data_money import DataMoney
    from tools.testers.backtest.modules.strategy_book import cash_pool_id_for_ledger

    store = cash_pool_store_for(state)
    pool_id = cash_pool_id_for_ledger(state, ledger_state)
    config = store.config_by_pool.get(pool_id, CashPoolConfig())
    return DataMoney.from_major(
        cash_pool_cash_major(
            state, ledger_state, timestamp=timestamp,
            include_conversion_cost=include_conversion_cost,
        ),
        currency=normalize_currency(config.base_currency),
        use_minor_units=False,
    )


def _cash_balances_for_pool(state: object, pool_id: str):
    from tools.testers.backtest.modules.strategy_book import cash_pool_id_for_ledger

    for ledger in getattr(state, "ledgers", {}).values():
        if cash_pool_id_for_ledger(state, ledger) != pool_id:
            continue
        cash = cash_for_ledger(state, ledger)
        if cash is not None:
            yield cash


def _cached_fx_rate(
    store: CashPoolStore,
    pool_id: str,
    currency: str,
    base_currency: str,
    timestamp: Any,
    rate_provider: FxRateProvider,
) -> float:
    cache_key = (pool_id, currency, timestamp, id(rate_provider))
    cached = store.fx_rate_cache.get(cache_key)
    if cached is not None:
        return cached
    resolved = rate_provider(currency, base_currency, timestamp)
    rate = float(resolved) if resolved is not None else float("nan")
    if not math.isfinite(rate) or rate <= 0:
        raise ValueError(f"Missing FX rate {currency}->{base_currency} at {timestamp}")
    store.fx_rate_cache[cache_key] = rate
    return rate


from .cash_pool_impl.config import (  # noqa: E402,F401
    cash_pool_config_for_ledger,
    cash_pool_config_from_strategy_config,
    ensure_cash_pool_config_for_strategy_ledger,
    register_cash_pool_config,
)
