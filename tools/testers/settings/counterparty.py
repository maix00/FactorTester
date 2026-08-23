"""CounterParty templates for building ledger-owned rule settings.

CounterPartyProfile is a saved template, not a runtime dependency. Applying a
profile resolves directly to ledger-owned LedgerConfig fields before the native
engine starts; event replay flows read ledger rules from the ledger, not from
StrategyConfig and not from this registry.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, cast

from tools.testers.backtest.engines.native.fields import FieldRef


@dataclass(frozen=True)
class CounterPartyProfile:
    id: str
    label: str
    field_defaults: dict[FieldRef, Any] = field(default_factory=dict)


_COUNTERPARTY_PROFILES: dict[str, CounterPartyProfile] = {}


def register_counterparty_profile(profile: CounterPartyProfile) -> CounterPartyProfile:
    if not profile.id:
        raise ValueError("counterparty profile id is required")
    _COUNTERPARTY_PROFILES[profile.id] = profile
    return profile


def counterparty_profile(profile_id: object) -> CounterPartyProfile | None:
    return _COUNTERPARTY_PROFILES.get(str(profile_id))


def registered_counterparty_profiles() -> dict[str, CounterPartyProfile]:
    return dict(_COUNTERPARTY_PROFILES)


def resolve_counterparty_profiles_by_ledger(
    resolved_settings_by_alias: Mapping[str, Mapping[str, Any]],
    *,
    strategy_book: object | None = None,
    ledger_ids_by_alias: Mapping[str, tuple[str, ...]] | None = None,
    counterparty: str | CounterPartyProfile | None = None,
    counterparty_by_strategy: Mapping[str, str | CounterPartyProfile | None] | None = None,
    counterparty_by_ledger: Mapping[str, str | CounterPartyProfile | None] | None = None,
) -> dict[str, str]:
    """Resolve CounterParty input to ledger-level profiles.

    Existing settings are per-strategy because StrategyConfig is per-strategy.
    Real CounterParty semantics are per-ledger: two strategies sharing one
    ledger cannot disagree on fee/margin/accounting terms. Per-ledger input is
    the explicit override; per-strategy values that collide on the same ledger
    raise instead of silently picking one.
    """
    from tools.testers.backtest.modules.strategy_book import StrategyBookSimple

    book = cast(Any, strategy_book or StrategyBookSimple())
    aliases = tuple(str(alias) for alias in resolved_settings_by_alias)
    resolved_ledger_ids_by_alias = dict(ledger_ids_by_alias or {})
    if not resolved_ledger_ids_by_alias:
        resolved_ledger_ids_by_alias = {
            alias: _ledger_ids_from_strategy_book_alias(book, alias)
            for alias in aliases
        }
    result: dict[str, str] = {}

    unified_profile = _profile_id(counterparty)
    if unified_profile:
        for ledger_ids in resolved_ledger_ids_by_alias.values():
            for ledger_id in ledger_ids:
                result.setdefault(ledger_id, unified_profile)

    strategy_overrides = counterparty_by_strategy or {}
    for alias, settings in resolved_settings_by_alias.items():
        raw_profile = strategy_overrides.get(str(alias), settings.get("counterparty_profile"))
        profile_id = _profile_id(raw_profile)
        if not profile_id:
            continue
        for ledger_id in resolved_ledger_ids_by_alias[str(alias)]:
            _put_counterparty_profile(
                result,
                ledger_id,
                profile_id,
                source=f"strategy {alias!r}",
            )

    for ledger_id, raw_profile in (counterparty_by_ledger or {}).items():
        profile_id = _profile_id(raw_profile)
        if profile_id:
            result[str(ledger_id)] = profile_id
    return result


def _ledger_ids_from_strategy_book_alias(book: object, alias: str) -> tuple[str, ...]:
    alias_text = str(alias)
    mapping = getattr(book, "strategy_ledger_ids_by_alias", {})
    ledger_ids = mapping.get(alias_text)
    if ledger_ids:
        return tuple(str(value) for value in ledger_ids)
    default_mapping = getattr(book, "default_ledger_id_by_alias", {})
    default = default_mapping.get(alias_text)
    if default:
        return (str(default),)
    return (f"private:{alias_text}",)


def unregister_counterparty_profile(profile_id: str) -> None:
    """Remove a profile and its injected `default_if` entries. Mainly for
    test isolation (this registry is process-global mutable state, same as
    `traderules`'s exchange-rule registries) -- production code registers
    profiles once at import time and never unregisters them."""
    profile = _COUNTERPARTY_PROFILES.pop(profile_id, None)
    if profile is None:
        return
    for ref in profile.field_defaults:
        _remove_default_if(ref, profile_id)
    _refresh_counterparty_profile_options()


def _profile_id(profile: str | CounterPartyProfile | None) -> str | None:
    if profile in (None, ""):
        return None
    if isinstance(profile, CounterPartyProfile):
        register_counterparty_profile(profile)
        return profile.id
    profile_id = str(profile)
    if profile_id and profile_id not in _COUNTERPARTY_PROFILES:
        raise ValueError(f"unknown counterparty profile: {profile_id!r}")
    return profile_id or None


def _put_counterparty_profile(result: dict[str, str], ledger_id: str, profile: object, *, source: str) -> None:
    profile_id = _profile_id(profile) if isinstance(profile, (str, CounterPartyProfile)) or profile is None else str(profile)
    if not profile_id:
        return
    existing = result.get(ledger_id)
    if existing is not None and existing != profile_id:
        raise ValueError(
            f"ledger {ledger_id!r} has conflicting counterparty profiles: "
            f"{existing!r} vs {profile_id!r} from {source}"
        )
    result[ledger_id] = profile_id


def _remove_default_if(ref: FieldRef, profile_id: str) -> None:
    from tools.testers.backtest.modules.registry import _ALL_MODULE_CLASSES

    for cls in _ALL_MODULE_CLASSES:
        for field_name, fd in cls.fields.items():
            if getattr(cls, field_name, None) != ref:
                continue
            if fd.default_if is not None:
                fd.default_if.get("counterparty_profile", {}).pop(profile_id, None)
            return


def apply_counterparty_profile_defaults() -> None:
    """Inject every registered profile's field defaults into each target
    field's own `default_if["counterparty_profile"]` dict, and refresh
    `EngineModule.counterparty_profile`'s select options. Called once from
    `register_all_module_settings`, after all profiles have been registered
    by their source modules -- mirrors
    `refresh_custom_product_field_definitions`'s timing."""
    for profile in _COUNTERPARTY_PROFILES.values():
        for ref, value in profile.field_defaults.items():
            _inject_default_if(ref, profile.id, value)
    _refresh_counterparty_profile_options()


def _inject_default_if(ref: FieldRef, profile_id: str, value: Any) -> None:
    from tools.testers.backtest.modules.registry import _ALL_MODULE_CLASSES

    for cls in _ALL_MODULE_CLASSES:
        for field_name, fd in cls.fields.items():
            if getattr(cls, field_name, None) != ref:
                continue
            if fd.default_if is not None:
                fd.default_if.setdefault("counterparty_profile", {})[profile_id] = value
            else:
                cls.fields[field_name] = replace(
                    fd, default_if={"counterparty_profile": {profile_id: value}})
            return
    raise ValueError(f"counterparty profile field {ref.qualified_name!r} is not a registered field")


def _refresh_counterparty_profile_options() -> None:
    from tools.testers.backtest.modules.engine import EngineModule

    fd = EngineModule.fields["counterparty_profile"]
    EngineModule.fields["counterparty_profile"] = replace(
        fd,
        options=(("", "不使用预设"),) + tuple(
            (profile.id, profile.label) for profile in _COUNTERPARTY_PROFILES.values()
        ),
    )


def _register_default_counterparty_profiles() -> None:
    """Seed a single placeholder profile equivalent to engine_mode="auto"'s
    own defaults, expressed through the counterparty_profile channel instead
    -- proves the mechanism end to end without inventing a real broker's
    fee/margin numbers. Real named presets (e.g. a specific futures company's
    published markup) get registered here once there's a real source for
    them."""
    from tools.testers.backtest.modules.fee import FeeModule
    from tools.testers.backtest.modules.margin import MarginModule
    from tools.testers.backtest.modules.trading_rule import TradingRuleModule

    register_counterparty_profile(CounterPartyProfile(
        id="exchange_base",
        label="交易所基准（不加价）",
        field_defaults={
            FeeModule.fee_mode: "auto",
            FeeModule.transaction_fee_source: "exchange",
            MarginModule.margin_mode: "auto",
            TradingRuleModule.accounting_mode: "Auto",
            TradingRuleModule.use_int_position: "true",
        },
    ))
    register_counterparty_profile(CounterPartyProfile(
        id="openctp_broker",
        label="OpenCTP经纪商费率",
        field_defaults={
            FeeModule.fee_mode: "auto",
            FeeModule.transaction_fee_source: "openctp",
            MarginModule.margin_mode: "auto",
            TradingRuleModule.accounting_mode: "Auto",
            TradingRuleModule.use_int_position: "true",
        },
    ))


_register_default_counterparty_profiles()
