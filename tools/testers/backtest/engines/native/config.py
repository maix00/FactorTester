"""Native backtest configuration value objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from tools.testers.backtest.engines.native.fields import FieldRef
    from tools.testers.backtest.engines.native.strategy import Strategy


@dataclass(frozen=True)
class CashPoolConfig:
    """Cash-pool owned capital configuration."""

    initial_capital_major: float | None = None
    base_currency: str | None = None
    currency_conversion_fee_rate: float | None = None
    target_margin_utilization: float | None = None
    max_margin_utilization: float | None = None
    margin_utilization_tolerance: float | None = None


@dataclass(frozen=True)
class LedgerConfig:
    """Ledger-owned accounting and execution-rule configuration."""

    account_currency: str | None = None
    fee_mode: str | None = None
    transaction_fee_source: str | None = None
    fixed_fee_rate: float | None = None
    margin_mode: str | None = None
    fixed_margin_ratio: float | None = None
    margin_call_mode: str | None = None
    liquidation_target_buffer: float | None = None
    accounting_mode: str | None = None
    daily_mark_to_market_enabled: bool | None = None
    cost_basis_method: str | None = None
    use_int_position: bool | None = None
    tradability_policy: str | None = None
    clearing_rounding_policy: str | None = None
    cash_reserve_ratio: float | None = None
    cash_reserve_major: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


def ledger_config_from_mapping(raw: Mapping[str, Any] | LedgerConfig | None) -> LedgerConfig:
    if raw is None:
        return LedgerConfig()
    if isinstance(raw, LedgerConfig):
        return raw
    known = {
        "account_currency",
        "fee_mode",
        "transaction_fee_source",
        "fixed_fee_rate",
        "margin_mode",
        "fixed_margin_ratio",
        "margin_call_mode",
        "liquidation_target_buffer",
        "accounting_mode",
        "daily_mark_to_market_enabled",
        "cost_basis_method",
        "use_int_position",
        "tradability_policy",
        "clearing_rounding_policy",
        "cash_reserve_ratio",
        "cash_reserve_major",
    }
    return LedgerConfig(
        account_currency=_optional_str(raw.get("account_currency")),
        fee_mode=_optional_str(raw.get("fee_mode")),
        transaction_fee_source=_optional_str(raw.get("transaction_fee_source")),
        fixed_fee_rate=_optional_float(raw.get("fixed_fee_rate")),
        margin_mode=_optional_str(raw.get("margin_mode")),
        fixed_margin_ratio=_optional_float(raw.get("fixed_margin_ratio")),
        margin_call_mode=_optional_str(raw.get("margin_call_mode")),
        liquidation_target_buffer=_optional_float(raw.get("liquidation_target_buffer")),
        accounting_mode=_optional_str(raw.get("accounting_mode")),
        daily_mark_to_market_enabled=_optional_bool(raw.get("daily_mark_to_market_enabled")),
        cost_basis_method=_optional_str(raw.get("cost_basis_method")),
        use_int_position=_optional_bool(raw.get("use_int_position")),
        tradability_policy=_optional_str(raw.get("tradability_policy")),
        clearing_rounding_policy=_optional_str(raw.get("clearing_rounding_policy")),
        cash_reserve_ratio=_optional_float(raw.get("cash_reserve_ratio")),
        cash_reserve_major=_optional_float(raw.get("cash_reserve_major")),
        metadata={str(key): value for key, value in raw.items() if key not in known},
    )


def merge_ledger_configs(*configs: LedgerConfig) -> LedgerConfig:
    merged: dict[str, Any] = {}
    metadata: dict[str, Any] = {}
    for config in configs:
        for field_name in (
            "account_currency",
            "fee_mode",
            "transaction_fee_source",
            "fixed_fee_rate",
            "margin_mode",
            "fixed_margin_ratio",
            "margin_call_mode",
            "liquidation_target_buffer",
            "accounting_mode",
            "daily_mark_to_market_enabled",
            "cost_basis_method",
            "use_int_position",
            "tradability_policy",
            "clearing_rounding_policy",
            "cash_reserve_ratio",
            "cash_reserve_major",
        ):
            value = getattr(config, field_name)
            if value is not None:
                merged[field_name] = value
        metadata.update(config.metadata)
    return LedgerConfig(**merged, metadata=metadata)


def ledger_config_field_values(config: LedgerConfig) -> dict[str, Any]:
    return {
        key: value
        for key in (
            "account_currency",
            "fee_mode",
            "transaction_fee_source",
            "fixed_fee_rate",
            "margin_mode",
            "fixed_margin_ratio",
            "margin_call_mode",
            "liquidation_target_buffer",
            "accounting_mode",
            "daily_mark_to_market_enabled",
            "cost_basis_method",
            "use_int_position",
            "tradability_policy",
            "clearing_rounding_policy",
            "cash_reserve_ratio",
            "cash_reserve_major",
        )
        if (value := getattr(config, key)) is not None
    }


@dataclass(frozen=True)
class StrategyConfig:
    strategy: "Strategy"
    active_flow_names: frozenset[str] = field(default_factory=frozenset)
    field_values: dict["FieldRef", Any] = field(default_factory=dict)

    def get(self, ref: "FieldRef", default: Any = None) -> Any:
        return self.field_values.get(ref, default)

    def uses_flow(self, flow_name: str) -> bool:
        return flow_name in self.active_flow_names


def _optional_str(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    return float(value)  # type: ignore[arg-type]


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"", "auto", "automatic"}:
            return None
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    raise ValueError(f"invalid tri-state boolean value: {value!r}")
