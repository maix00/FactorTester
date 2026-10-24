"""Fail-closed execution settings for the NautilusTrader migration.

This is a *frozen intent* compiler, not a second matching engine.  It keeps
the old fractional-participation policy distinct from NautilusTrader's native
OHLC Bar-volume allocation and recorded-book liquidity accounting. A caller
must supply the actual feed kind and adapter capabilities before a new Job
may use the resulting venue options.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

FeedKind = Literal["bar", "quote", "trade", "l2", "l3"]
CapacityKind = Literal[
    "unconstrained", "bar_volume", "recorded_depth", "native_liquidity", "mixed",
]
DailySettlementPolicy = Literal["eligible_products", "disabled"]
PositionCostBasis = Literal["WEIGHTED_AVERAGE", "FIFO", "LIFO", "HIFO"]
_FROZEN_EXECUTION_KEYS = frozenset({
    "data_source_ref", "source_version", "product_scope_refs", "start_utc", "end_utc",
    "bar_end_timestamps", "execution_price_basis", "execution_timing",
    "fee_mode", "fee_per_contract", "fee_currency",
    "fee_schedule_ref", "venues", "strategy_venue_bindings", "account_model",
    "execution_model", "shared_market_data", "initial_capital_major", "base_currency",
    "instrument_execution_policy",
    "liquidity_mode", "participation_rate", "matching_model",
    "nt_capacity_policy", "nt_matching_policy", "nt_price_protection_points",
    "nautilus_venue",
})


class UnsupportedExecutionConfig(ValueError):
    """The requested historical execution semantics cannot be reproduced."""

    def __init__(self, field: str, reason: str) -> None:
        self.field = field
        self.reason = reason
        super().__init__(f"{field}: {reason}")


@dataclass(frozen=True, slots=True)
class FrozenInstrumentExecutionPolicy:
    """Compact, immutable defaults and exceptions for a frozen product scope.

    RunSpecs keep product-selection references, a default policy, group-level
    overrides, and only exceptional instrument overrides. The runtime expands
    this compact contract against the already-frozen product scope and rule
    snapshot; it does not persist a duplicate list of every product.
    """

    version: int
    resolution_version: str
    settlement_rule_set_ref: str | None
    daily_settlement_default: DailySettlementPolicy
    daily_settlement_scope_overrides: tuple[tuple[str, bool], ...]
    daily_settlement_instrument_overrides: tuple[tuple[str, bool], ...]
    cost_basis_default: PositionCostBasis
    cost_basis_scope_overrides: tuple[tuple[str, PositionCostBasis], ...]
    cost_basis_instrument_overrides: tuple[tuple[str, PositionCostBasis], ...]

    def manifest(self) -> dict[str, object]:
        return {
            "version": self.version,
            "resolution_version": self.resolution_version,
            "settlement_rule_set_ref": self.settlement_rule_set_ref,
            "daily_settlement": {
                "default": self.daily_settlement_default,
                "scope_overrides": {
                    scope: enabled
                    for scope, enabled in self.daily_settlement_scope_overrides
                },
                "instrument_overrides": {
                    instrument: enabled
                    for instrument, enabled in self.daily_settlement_instrument_overrides
                },
                "eligible_products_use_official_close": True,
            },
            "position_cost_basis": {
                "default": self.cost_basis_default,
                "scope_overrides": {
                    scope: basis for scope, basis in self.cost_basis_scope_overrides
                },
                "instrument_overrides": {
                    instrument: basis
                    for instrument, basis in self.cost_basis_instrument_overrides
                },
            },
            "resolution_order": [
                "default", "product_scope_override", "instrument_override",
            ],
        }

    @property
    def requires_daily_settlement_adapter(self) -> bool:
        return (
            self.daily_settlement_default == "eligible_products"
            or any(enabled for _, enabled in self.daily_settlement_scope_overrides)
            or any(enabled for _, enabled in self.daily_settlement_instrument_overrides)
        )

    def resolve_for_instrument(
        self, instrument_id: str, *, product_scope_refs: tuple[str, ...],
        daily_settlement_eligible: bool,
    ) -> dict[str, object]:
        """Expand one product's effective settings after its frozen scope is known."""
        if not instrument_id:
            raise UnsupportedExecutionConfig("instrument_id", "must be nonempty")
        settlement = (
            self.daily_settlement_default == "eligible_products"
            and daily_settlement_eligible
        )
        settlement_scopes = [
            value for scope, value in self.daily_settlement_scope_overrides
            if scope in product_scope_refs
        ]
        basis = self.cost_basis_default
        basis_scopes = [
            value for scope, value in self.cost_basis_scope_overrides
            if scope in product_scope_refs
        ]
        settlement_override = dict(self.daily_settlement_instrument_overrides).get(instrument_id)
        basis_override = dict(self.cost_basis_instrument_overrides).get(instrument_id)
        if len(set(settlement_scopes)) > 1 and settlement_override is None:
            raise UnsupportedExecutionConfig(
                "instrument_execution_policy.daily_settlement.scope_overrides",
                f"overlapping product scopes conflict for {instrument_id}; add an instrument exception",
            )
        if len(set(basis_scopes)) > 1 and basis_override is None:
            raise UnsupportedExecutionConfig(
                "instrument_execution_policy.position_cost_basis.scope_overrides",
                f"overlapping product scopes conflict for {instrument_id}; add an instrument exception",
            )
        if settlement_scopes:
            settlement = settlement_scopes[0]
        if basis_scopes:
            basis = basis_scopes[0]
        if settlement_override is not None:
            settlement = settlement_override
        if basis_override is not None:
            basis = basis_override
        if settlement and not daily_settlement_eligible:
            raise UnsupportedExecutionConfig(
                "instrument_execution_policy.daily_settlement",
                f"{instrument_id} is not eligible under its frozen exchange rule",
            )
        return {
            "instrument_id": instrument_id,
            "daily_settlement_enabled": settlement,
            "position_cost_basis": basis,
        }


def freeze_instrument_execution_policy(
    *, preset: str,
    settlement_rule_set_ref: str | None = None,
    daily_settlement_default: str | None = None,
    daily_settlement_scope_overrides: Mapping[str, object] | None = None,
    daily_settlement_instrument_overrides: Mapping[str, object] | None = None,
    cost_basis_default: object | None = None,
    cost_basis_scope_overrides: Mapping[str, object] | None = None,
    cost_basis_instrument_overrides: Mapping[str, object] | None = None,
) -> FrozenInstrumentExecutionPolicy:
    """Compile a UI preset into compact RunSpec policy defaults and exceptions.

    ``preset`` is intentionally consumed here and is not part of the frozen
    policy. The result contains only runtime rules, immutable rule-source
    references, product-selection overrides, and sparse contract exceptions.
    """
    mode = str(preset or "").strip().lower()
    if mode not in {"basic", "auto", "custom", "exact"}:
        raise UnsupportedExecutionConfig(
            "engine_mode", "must be Basic, Auto, Custom, or Exact before RunSpec freezing",
        )

    settlement_default = (
        str(daily_settlement_default).strip().lower()
        if daily_settlement_default not in (None, "") else None
    )
    if settlement_default in {"enabled", "true"}:
        settlement_default = "eligible_products"
    if settlement_default in {"false", "off"}:
        settlement_default = "disabled"
    if settlement_default not in (None, "eligible_products", "disabled"):
        raise UnsupportedExecutionConfig(
            "daily_settlement_default", "must be eligible_products or disabled",
        )
    basis_default = (
        _normalize_cost_basis(cost_basis_default, "cost_basis_default")
        if cost_basis_default not in (None, "") else None
    )
    settlement_scope = _boolean_overrides(
        daily_settlement_scope_overrides,
        "daily_settlement_scope_overrides",
    )
    settlement_instrument = _boolean_overrides(
        daily_settlement_instrument_overrides,
        "daily_settlement_instrument_overrides",
    )
    basis_scope = _cost_basis_overrides(
        cost_basis_scope_overrides, "cost_basis_scope_overrides",
    )
    basis_instrument = _cost_basis_overrides(
        cost_basis_instrument_overrides, "cost_basis_instrument_overrides",
    )

    if mode == "basic":
        if any((settlement_default == "eligible_products", settlement_scope,
                any(enabled for _, enabled in settlement_instrument), basis_scope,
                basis_instrument, basis_default not in (None, "WEIGHTED_AVERAGE"))):
            raise UnsupportedExecutionConfig(
                "engine_mode", "Basic fixes DMTM off and weighted-average cost basis",
            )
        settlement_default = "disabled"
        basis_default = "WEIGHTED_AVERAGE"
    elif mode == "auto":
        if any((settlement_default == "disabled", settlement_scope,
                settlement_instrument, basis_scope, basis_instrument,
                basis_default not in (None, "WEIGHTED_AVERAGE"))):
            raise UnsupportedExecutionConfig(
                "engine_mode", "Auto uses exchange eligibility and weighted-average basis; use Custom for overrides",
            )
        settlement_default = "eligible_products"
        basis_default = "WEIGHTED_AVERAGE"
    elif mode == "custom":
        settlement_default = settlement_default or "eligible_products"
        basis_default = basis_default or "WEIGHTED_AVERAGE"
    else:  # exact
        if settlement_default is None or basis_default is None:
            raise UnsupportedExecutionConfig(
                "engine_mode",
                "Exact requires explicit DMTM and cost-basis defaults before freezing",
            )

    if settlement_rule_set_ref not in (None, ""):
        settlement_rule_set_ref = _nonempty_text(
            settlement_rule_set_ref, "settlement_rule_set_ref",
        )

    return FrozenInstrumentExecutionPolicy(
        version=1,
        resolution_version="factor-tester.execution-policy.v1",
        settlement_rule_set_ref=settlement_rule_set_ref,
        daily_settlement_default=settlement_default,
        daily_settlement_scope_overrides=settlement_scope,
        daily_settlement_instrument_overrides=settlement_instrument,
        cost_basis_default=basis_default,
        cost_basis_scope_overrides=basis_scope,
        cost_basis_instrument_overrides=basis_instrument,
    )


def parse_frozen_instrument_execution_policy(
    value: object,
) -> FrozenInstrumentExecutionPolicy:
    """Validate a compact policy already serialized in an immutable RunSpec."""
    if not isinstance(value, Mapping):
        raise UnsupportedExecutionConfig(
            "instrument_execution_policy", "must be a frozen policy object",
        )
    expected = {"version", "resolution_version", "settlement_rule_set_ref",
                "daily_settlement", "position_cost_basis", "resolution_order"}
    if set(value) != expected:
        raise UnsupportedExecutionConfig(
            "instrument_execution_policy", "policy fields do not match schema version 1",
        )
    if value.get("version") != 1 or value.get("resolution_version") != "factor-tester.execution-policy.v1":
        raise UnsupportedExecutionConfig(
            "instrument_execution_policy.version", "unsupported policy resolution version",
        )
    settlement = value.get("daily_settlement")
    basis = value.get("position_cost_basis")
    if not isinstance(settlement, Mapping) or not isinstance(basis, Mapping):
        raise UnsupportedExecutionConfig(
            "instrument_execution_policy", "daily_settlement and position_cost_basis are required",
        )
    if set(settlement) != {"default", "scope_overrides", "instrument_overrides",
                           "eligible_products_use_official_close"}:
        raise UnsupportedExecutionConfig(
            "instrument_execution_policy.daily_settlement", "fields do not match schema version 1",
        )
    if set(basis) != {"default", "scope_overrides", "instrument_overrides"}:
        raise UnsupportedExecutionConfig(
            "instrument_execution_policy.position_cost_basis", "fields do not match schema version 1",
        )
    if settlement.get("default") not in {"eligible_products", "disabled"}:
        raise UnsupportedExecutionConfig(
            "instrument_execution_policy.daily_settlement.default", "must be eligible_products or disabled",
        )
    if settlement.get("eligible_products_use_official_close") is not True:
        raise UnsupportedExecutionConfig(
            "instrument_execution_policy.daily_settlement", "must use official settlement closes",
        )
    settlement_scope_overrides = _boolean_overrides(
        settlement.get("scope_overrides"), "daily_settlement.scope_overrides",
    )
    settlement_instrument_overrides = _boolean_overrides(
        settlement.get("instrument_overrides"), "daily_settlement.instrument_overrides",
    )
    settlement_ref = value.get("settlement_rule_set_ref")
    enabled_settlement_override = any(
        enabled for _, enabled in (*settlement_scope_overrides, *settlement_instrument_overrides)
    )
    if settlement_ref is not None:
        settlement_ref = _nonempty_text(settlement_ref, "settlement_rule_set_ref")
    if value.get("resolution_order") != [
        "default", "product_scope_override", "instrument_override",
    ]:
        raise UnsupportedExecutionConfig(
            "instrument_execution_policy.resolution_order", "unsupported policy precedence",
        )
    return FrozenInstrumentExecutionPolicy(
        version=1,
        resolution_version="factor-tester.execution-policy.v1",
        settlement_rule_set_ref=settlement_ref,
        daily_settlement_default=settlement["default"],
        daily_settlement_scope_overrides=settlement_scope_overrides,
        daily_settlement_instrument_overrides=settlement_instrument_overrides,
        cost_basis_default=_required_cost_basis(basis.get("default"), "position_cost_basis.default"),
        cost_basis_scope_overrides=_cost_basis_overrides(
            basis.get("scope_overrides"), "position_cost_basis.scope_overrides",
        ),
        cost_basis_instrument_overrides=_cost_basis_overrides(
            basis.get("instrument_overrides"), "position_cost_basis.instrument_overrides",
        ),
    )


def _boolean_overrides(value: Mapping[str, object] | None, field: str) -> tuple[tuple[str, bool], ...]:
    if value is None:
        return ()
    if not isinstance(value, Mapping):
        raise UnsupportedExecutionConfig(field, "must map product-scope or instrument refs to booleans")
    result = []
    for ref, enabled in value.items():
        key = _nonempty_text(ref, field)
        if not isinstance(enabled, bool):
            raise UnsupportedExecutionConfig(field, f"{key} must have an explicit boolean")
        result.append((key, enabled))
    return tuple(sorted(result))


def _cost_basis_overrides(
    value: Mapping[str, object] | None, field: str,
) -> tuple[tuple[str, PositionCostBasis], ...]:
    if value is None:
        return ()
    if not isinstance(value, Mapping):
        raise UnsupportedExecutionConfig(field, "must map product-scope or instrument refs to cost bases")
    result = []
    for ref, basis in value.items():
        key = _nonempty_text(ref, field)
        result.append((key, _required_cost_basis(basis, field)))
    return tuple(sorted(result))


def _required_cost_basis(value: object, field: str) -> PositionCostBasis:
    normalized = _normalize_cost_basis(value, field)
    if normalized is None:
        raise UnsupportedExecutionConfig(field, "must be an explicit weighted-average, FIFO, LIFO, or HIFO value")
    return normalized


def _strict_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise UnsupportedExecutionConfig(field, "values must be explicit booleans")
    return value


def resolve_instrument_execution_settings(
    policy: FrozenInstrumentExecutionPolicy, *,
    product_scopes_by_instrument: Mapping[str, tuple[str, ...]],
    daily_settlement_eligibility: Mapping[str, bool],
) -> dict[str, object]:
    """Expand the compact RunSpec policy into NT's sparse per-instrument maps.

    Product membership and settlement eligibility must come from the frozen
    product-selection and exchange-rule snapshots. This is called once before
    engine construction, not from the order/bar hot path.
    """
    if not isinstance(product_scopes_by_instrument, Mapping) or not product_scopes_by_instrument:
        raise UnsupportedExecutionConfig(
            "product_scopes_by_instrument", "requires the resolved products from frozen product scopes",
        )
    if set(product_scopes_by_instrument) != set(daily_settlement_eligibility):
        raise UnsupportedExecutionConfig(
            "daily_settlement_eligibility", "must cover exactly the resolved instrument set",
        )
    scope_refs = {
        _nonempty_text(scope, "product_scopes_by_instrument")
        for refs in product_scopes_by_instrument.values()
        for scope in refs
    }
    configured_scope_refs = {
        ref for ref, _ in (*policy.daily_settlement_scope_overrides,
                           *policy.cost_basis_scope_overrides)
    }
    missing_scope_refs = configured_scope_refs - scope_refs
    if missing_scope_refs:
        raise UnsupportedExecutionConfig(
            "instrument_execution_policy.scope_overrides",
            "override references are outside the frozen product scope: "
            + ", ".join(sorted(missing_scope_refs)),
        )
    resolved_instruments = set(product_scopes_by_instrument)
    configured_instruments = {
        ref for ref, _ in (*policy.daily_settlement_instrument_overrides,
                           *policy.cost_basis_instrument_overrides)
    }
    missing_instruments = configured_instruments - resolved_instruments
    if missing_instruments:
        raise UnsupportedExecutionConfig(
            "instrument_execution_policy.instrument_overrides",
            "override references are outside the frozen product scope: "
            + ", ".join(sorted(missing_instruments)),
        )

    settlement_enabled: list[str] = []
    cost_basis_overrides: dict[str, str] = {}
    resolved_count = 0
    for instrument_id, scopes in sorted(product_scopes_by_instrument.items()):
        eligibility = daily_settlement_eligibility[instrument_id]
        if not isinstance(eligibility, bool):
            raise UnsupportedExecutionConfig(
                "daily_settlement_eligibility", f"{instrument_id} must have an explicit boolean",
            )
        item = policy.resolve_for_instrument(
            instrument_id, product_scope_refs=tuple(scopes),
            daily_settlement_eligible=eligibility,
        )
        resolved_count += 1
        if item["daily_settlement_enabled"] is True:
            settlement_enabled.append(instrument_id)
        if item["position_cost_basis"] != policy.cost_basis_default:
            cost_basis_overrides[instrument_id] = str(item["position_cost_basis"])
    return {
        "daily_settlement_instrument_ids": settlement_enabled,
        "position_cost_basis_by_instrument": cost_basis_overrides,
        "resolved_instrument_count": resolved_count,
    }


@dataclass(frozen=True, slots=True)
class CapacityPlan:
    """A serializable declaration of the assumptions passed to a NT venue."""

    kind: CapacityKind
    feed_kind: FeedKind
    liquidity_consumption: bool
    price_protection_points: int
    bar_volume_weights_bps: tuple[int, int, int, int] | None
    bar_volume_remainder_to: Literal["open", "high", "low", "close"]
    assumptions: tuple[str, ...]

    def venue_options(self) -> dict[str, object]:
        """Only options supported by the pinned ``BacktestVenueConfig``."""
        options: dict[str, object] = {
            "liquidity_consumption": self.liquidity_consumption,
            "price_protection_points": self.price_protection_points,
        }
        if self.bar_volume_weights_bps is not None:
            options["bar_volume_weights_bps"] = list(self.bar_volume_weights_bps)
            options["bar_volume_remainder_to"] = self.bar_volume_remainder_to
        return options

    def manifest(self) -> dict[str, object]:
        return {
            "capacity_kind": self.kind,
            "feed_kind": self.feed_kind,
            "venue_options": None if self.kind == "mixed" else self.venue_options(),
            "ohlc_volume_allocation": (
                {
                    "bar_volume_weights_bps": (
                        list(self.bar_volume_weights_bps)
                        if self.bar_volume_weights_bps is not None else None
                    ),
                    "bar_volume_remainder_to": self.bar_volume_remainder_to,
                }
                if self.kind == "bar_volume" else None
            ),
            "assumptions": list(self.assumptions),
        }


@dataclass(frozen=True, slots=True)
class NautilusVenueSettings:
    """Serializable native venue kwargs currently exposed by the bridge."""

    bar_volume_weights_bps: tuple[int, int, int, int] | None = None
    bar_volume_remainder_to: Literal["open", "high", "low", "close"] = "close"

    def manifest(self) -> dict[str, object]:
        return {
            "bar_volume_weights_bps": (
                list(self.bar_volume_weights_bps)
                if self.bar_volume_weights_bps is not None else None
            ),
            "bar_volume_remainder_to": self.bar_volume_remainder_to,
        }


def freeze_nautilus_venue_settings(value: object = None) -> dict[str, object]:
    """Expand the current editor input to explicit Nautilus-named RunSpec fields."""
    return parse_nautilus_venue_settings(value).manifest()


def parse_nautilus_venue_settings(value: object) -> NautilusVenueSettings:
    if value is None:
        return NautilusVenueSettings()
    if not isinstance(value, Mapping):
        raise UnsupportedExecutionConfig(
            "nautilus_venue", "must be an object of Nautilus venue options",
        )
    allowed = {"bar_volume_weights_bps", "bar_volume_remainder_to"}
    unknown = set(value) - allowed
    if unknown:
        raise UnsupportedExecutionConfig(
            "nautilus_venue",
            "unmapped Nautilus venue options: " + ", ".join(sorted(map(str, unknown))),
        )
    weights, remainder = _nautilus_bar_volume_allocation(value)
    return NautilusVenueSettings(weights, remainder)


def compile_capacity_plan(
    settings: Mapping[str, Any], *, feed_kind: FeedKind,
) -> CapacityPlan:
    """Validate legacy capacity controls and choose an explicit native policy.

    ``volume_participation`` meant a fixed fraction of the *execution bar's*
    completed volume, shared among orders in a ledger.  It cannot be inferred
    from NT's native per-price-level liquidity consumption. ``bar_volume`` is
    an explicit different model: NT allocates reported OHLC volume across its
    synthetic open/high/low/close matching legs, and consumption is shared at
    each leg. An AT_THE_OPEN order can only consume the open-leg allocation;
    later bar volume is not visible at the open without look-ahead.
    """
    if feed_kind not in {"bar", "quote", "trade", "l2", "l3"}:
        raise UnsupportedExecutionConfig("feed_kind", f"unknown feed kind {feed_kind!r}")

    legacy_mode = str(settings.get("liquidity_mode", "infinite") or "infinite")
    matching = str(settings.get("matching_model", "auto") or "auto")
    if legacy_mode == "volume_participation" or matching == "bar_volume_limited":
        _participation_rate(settings.get("participation_rate", 0.1))
        raise UnsupportedExecutionConfig(
            "liquidity_mode",
            "legacy execution-bar volume participation is not equivalent to "
            "NautilusTrader recorded-book liquidity consumption; retain the "
            "legacy run or choose an explicitly documented depth-data policy",
        )
    if legacy_mode != "infinite":
        raise UnsupportedExecutionConfig("liquidity_mode", f"unknown mode {legacy_mode!r}")
    if matching not in {"auto", "next_bar_full_fill"}:
        raise UnsupportedExecutionConfig("matching_model", f"unknown model {matching!r}")

    # These are explicit Nautilus policies, never reinterpretations of legacy
    # defaults. ATO orders only access the open-leg share of a Bar's volume.
    nt_policy = str(settings.get("nt_capacity_policy", "unconstrained") or "unconstrained")
    if nt_policy == "bar_volume":
        if feed_kind != "bar":
            raise UnsupportedExecutionConfig(
                "nt_capacity_policy",
                "bar_volume requires Nautilus OHLC Bar input",
            )
        if matching == "next_bar_full_fill":
            raise UnsupportedExecutionConfig(
                "matching_model",
                "next_bar_full_fill conflicts with native Bar-volume-limited fills",
            )
        if settings.get("nt_matching_policy") not in (None, "bar_volume"):
            raise UnsupportedExecutionConfig(
                "nt_matching_policy",
                "bar_volume requires the native Bar-volume matching policy",
            )
        points = _nonnegative_int(
            settings.get("nt_price_protection_points", 0), "nt_price_protection_points",
        )
        if points:
            raise UnsupportedExecutionConfig(
                "nt_price_protection_points",
                "price protection requires an explicit recorded-depth policy",
            )
        venue_settings = parse_nautilus_venue_settings(settings.get("nautilus_venue"))
        weights = venue_settings.bar_volume_weights_bps
        remainder = venue_settings.bar_volume_remainder_to
        return CapacityPlan(
            kind="bar_volume", feed_kind=feed_kind,
            liquidity_consumption=True, price_protection_points=0,
            bar_volume_weights_bps=weights,
            bar_volume_remainder_to=remainder,
            assumptions=(
                (
                    "Nautilus uses its native OHLC Bar-volume allocation."
                    if weights is None else
                    "OHLC Bar volume is split by the frozen integer basis-point weights; each size is rounded down to the instrument increment and the remainder goes to the selected leg."
                ),
                "Liquidity consumption shares each leg's size across orders; an AT_THE_OPEN order only sees the open-leg allocation, so later volume is not used at the open.",
                "This is total Bar-volume allocation, not a configurable participation-rate fraction or opening-auction depth estimate.",
            ),
        )
    venue_settings = parse_nautilus_venue_settings(settings.get("nautilus_venue"))
    if venue_settings.bar_volume_weights_bps is not None:
        raise UnsupportedExecutionConfig(
            "nautilus_venue.bar_volume_weights_bps",
            "requires nt_capacity_policy=bar_volume",
        )
    if nt_policy not in {"unconstrained", "recorded_depth"}:
        raise UnsupportedExecutionConfig("nt_capacity_policy", f"unknown policy {nt_policy!r}")
    points = _nonnegative_int(
        settings.get("nt_price_protection_points", 0), "nt_price_protection_points",
    )

    if nt_policy == "recorded_depth":
        if feed_kind not in {"l2", "l3"}:
            raise UnsupportedExecutionConfig(
                "nt_capacity_policy",
                "recorded-depth capacity requires real L2/L3 size; bar, quote, "
                "and trade feeds do not prove book depth or queue priority",
            )
        if matching == "next_bar_full_fill":
            raise UnsupportedExecutionConfig(
                "matching_model",
                "next_bar_full_fill conflicts with recorded-depth partial fills",
            )
        if settings.get("nt_matching_policy") != "recorded_book":
            raise UnsupportedExecutionConfig(
                "nt_matching_policy",
                "must explicitly select recorded_book; legacy auto means next-bar full fill",
            )
        return CapacityPlan(
            kind="recorded_depth", feed_kind=feed_kind,
            liquidity_consumption=True, price_protection_points=points,
            bar_volume_weights_bps=None, bar_volume_remainder_to="close",
            assumptions=(
                "Historical book levels stay immutable; NT tracks simulated consumed size per level until fresh depth arrives.",
                "Observed displayed size is not queue priority or a fixed participation rate.",
            ),
        )

    if points:
        raise UnsupportedExecutionConfig(
            "nt_price_protection_points",
            "price protection requires an explicit recorded-depth policy",
        )
    if settings.get("nt_matching_policy") not in (None, "unconstrained"):
        raise UnsupportedExecutionConfig(
            "nt_matching_policy", "recorded_book requires the recorded-depth policy",
        )
    return CapacityPlan(
        kind="unconstrained", feed_kind=feed_kind,
        liquidity_consumption=False, price_protection_points=0,
        bar_volume_weights_bps=None, bar_volume_remainder_to="close",
        assumptions=(
            "No participation cap is applied. NT's own fill-price and residual rules still apply.",
        ),
    )


@dataclass(frozen=True, slots=True)
class FrozenExecutionPlan:
    """Minimal immutable run contract before NT objects are constructed.

    An adapter capability is a tested implementation at the business service,
    not a statement that NT provides the behavior by itself.  This compiler is
    intentionally stricter than the legacy editor: old defaults cannot be
    interpreted as a new fee model or as a next-open execution guarantee.
    """

    data_source_ref: str
    source_version: str | None
    product_scope_refs: tuple[str, ...]
    start_utc: str
    end_utc: str
    bar_end_timestamps: bool
    timing: Literal["next_bar_open"]
    fee: Literal["per_venue"]
    fee_details: tuple[tuple[str, str], ...]
    capacity: CapacityPlan
    venue_capacity: tuple[dict[str, object], ...]
    nautilus_venue: NautilusVenueSettings
    instrument_execution_policy: FrozenInstrumentExecutionPolicy
    venues: tuple[dict[str, Any], ...]
    strategy_venue_bindings: tuple[dict[str, Any], ...]

    def manifest(self) -> dict[str, object]:
        return {
            "data_source_ref": self.data_source_ref,
            "source_version": self.source_version,
            "source_versioned": self.source_version is not None,
            "product_scope_refs": list(self.product_scope_refs),
            "start_utc": self.start_utc,
            "end_utc": self.end_utc,
            "bar_end_timestamps": self.bar_end_timestamps,
            "timing": self.timing,
            "fee": {
                "mode": self.fee,
                "venue_models": {
                    str(venue["name"]): str(venue["native_config"]["fee_model"]["type"])
                    for venue in self.venues
                },
                **dict(self.fee_details),
            },
            "nautilus_venue": self.nautilus_venue.manifest(),
            "capacity": self.capacity.manifest(),
            "venue_capacity": list(self.venue_capacity),
            "instrument_execution_policy": self.instrument_execution_policy.manifest(),
            "venues": list(self.venues),
            "strategy_venue_bindings": list(self.strategy_venue_bindings),
            "account_model": "one_account_per_venue",
            "execution_model": "one_backtest_engine_per_run",
            "shared_market_data": True,
            "daily_settlement": {
                "policy": self.instrument_execution_policy.daily_settlement_default,
                "eligibility_source": "immutable_rule_set",
                "rule_set_ref": self.instrument_execution_policy.settlement_rule_set_ref,
                "event": "NautilusTrader InstrumentCloseType::DailySettlement",
            },
        }


def compile_frozen_execution_plan(
    settings: Mapping[str, Any], *,
    feed_kind: FeedKind,
    adapter_capabilities: frozenset[str] = frozenset(),
) -> FrozenExecutionPlan:
    """Reject configurations whose semantics are not implemented and frozen.

    Required keys describe *resolved* input, after the editor's ``auto`` and
    preset expansion.  It can be stored with a RunSpec, then handed to a
    separate NT object builder.  Merely creating this plan does not execute a
    Job or assert that a real market adapter is connected.
    """
    unknown = sorted(set(settings) - _FROZEN_EXECUTION_KEYS)
    if unknown:
        raise UnsupportedExecutionConfig(
            "settings", f"unmapped execution fields: {', '.join(unknown)}",
        )
    source = _nonempty_text(settings.get("data_source_ref"), "data_source_ref")
    version_value = settings.get("source_version")
    version = None if version_value is None else _nonempty_text(version_value, "source_version")
    raw_scopes = settings.get("product_scope_refs")
    if not isinstance(raw_scopes, (list, tuple)) or not raw_scopes:
        raise UnsupportedExecutionConfig(
            "product_scope_refs", "requires frozen product-selection references, not an expanded product list",
        )
    scopes = tuple(_nonempty_text(item, "product_scope_refs") for item in raw_scopes)
    if len(scopes) != len(set(scopes)):
        raise UnsupportedExecutionConfig("product_scope_refs", "duplicate product-selection references")
    start = _aware_utc(settings.get("start_utc"), "start_utc")
    end = _aware_utc(settings.get("end_utc"), "end_utc")
    if start >= end:
        raise UnsupportedExecutionConfig("end_utc", "must be after start_utc")
    if settings.get("bar_end_timestamps") is not True:
        raise UnsupportedExecutionConfig(
            "bar_end_timestamps", "must explicitly confirm source bar timestamps denote completed bars",
        )

    venues = _parse_native_venues(
        settings.get("venues"),
        base_currency=settings.get("base_currency"),
        initial_capital=settings.get("initial_capital_major"),
        legacy_settings=settings,
    )
    capacity, venue_capacity = _compile_venue_capacity(venues, feed_kind=feed_kind)
    try:
        nautilus_venue = parse_nautilus_venue_settings(settings.get("nautilus_venue"))
    except UnsupportedExecutionConfig:
        raise
    basis = str(settings.get("execution_price_basis", "") or "")
    if basis != "open":
        raise UnsupportedExecutionConfig(
            "execution_price_basis", "this migration slice only supports next-bar open execution",
        )
    if settings.get("execution_timing") != "next_bar_open":
        raise UnsupportedExecutionConfig(
            "execution_timing", "must explicitly request next_bar_open",
        )
    if feed_kind != "bar":
        raise UnsupportedExecutionConfig(
            "feed_kind", "next_bar_open currently requires native OHLC Bar execution",
        )
    if "native_bar_open_market_orders" not in adapter_capabilities:
        raise UnsupportedExecutionConfig(
            "execution_timing",
            "the pinned Nautilus matching engine must support AT_THE_OPEN market orders "
            "on the next native Bar open leg",
        )
    if (any(item["capacity_kind"] == "bar_volume" for item in venue_capacity)
            and "native_bar_volume_consumption" not in adapter_capabilities):
        raise UnsupportedExecutionConfig(
            "venues.native_config.liquidity_consumption",
            "the run adapter must verify Nautilus OHLC Bar-volume allocation and shared consumption",
        )
    fee_types = {
        str(item["native_config"]["fee_model"]["type"])
        for item in venues
    }
    if fee_types & {"unconfigured", "inherit"}:
        raise UnsupportedExecutionConfig(
            "venues.native_config.fee_model",
            "Nautilus requires an explicit FeeModel for every Venue; choose one in each Venue configuration",
        )
    if "historical_schedule" in fee_types and "historical_fee_schedule" not in adapter_capabilities:
        raise UnsupportedExecutionConfig(
            "venues.native_config.fee_model.schedule_ref",
                "historical fee changes require a registered effective-time adapter for a Nautilus FeeModel",
        )
    fee_details: tuple[tuple[str, str], ...] = ()

    instrument_policy = parse_frozen_instrument_execution_policy(
        settings.get("instrument_execution_policy"),
    )
    if (instrument_policy.requires_daily_settlement_adapter
            and instrument_policy.settlement_rule_set_ref is None):
        raise UnsupportedExecutionConfig(
            "instrument_execution_policy.settlement_rule_set_ref",
            "no versioned exchange settlement-rule source is registered for this data scope",
        )
    if (instrument_policy.requires_daily_settlement_adapter
            and "daily_settlement" not in adapter_capabilities):
        raise UnsupportedExecutionConfig(
            "instrument_execution_policy.daily_settlement",
            "eligible-product DMTM is frozen; "
            "the run adapter must schedule official settlement events",
        )

    if settings.get("account_model") != "one_account_per_venue":
        raise UnsupportedExecutionConfig(
            "account_model", "must configure one Nautilus account per Venue",
        )
    if settings.get("execution_model") != "one_backtest_engine_per_run":
        raise UnsupportedExecutionConfig(
            "execution_model", "all venues and strategies in a RunSpec use one BacktestEngine",
        )
    if settings.get("shared_market_data") is not True:
        raise UnsupportedExecutionConfig(
            "shared_market_data", "the RunSpec must load one shared market-data stream",
        )
    strategy_venue_bindings = _parse_strategy_venue_bindings(
        settings.get("strategy_venue_bindings"), venues, scopes,
    )
    return FrozenExecutionPlan(
        data_source_ref=source,
        source_version=version,
        product_scope_refs=scopes,
        start_utc=start,
        end_utc=end,
        bar_end_timestamps=True,
        timing="next_bar_open",
        fee="per_venue",
        fee_details=fee_details,
        capacity=capacity,
        venue_capacity=venue_capacity,
        nautilus_venue=nautilus_venue,
        instrument_execution_policy=instrument_policy,
        venues=venues,
        strategy_venue_bindings=strategy_venue_bindings,
    )


def _parse_native_venues(
    value: object, *, base_currency: object, initial_capital: object,
    legacy_settings: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], ...]:
    field = "venues"
    if not isinstance(value, list) or not value:
        raise UnsupportedExecutionConfig(field, "requires at least one configured Nautilus Venue")
    currency = _nonempty_text(base_currency, "base_currency").upper()
    capital = _nonnegative_decimal(initial_capital, "initial_capital_major")
    if capital <= 0:
        raise UnsupportedExecutionConfig("initial_capital_major", "must be greater than zero")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    total = Decimal(0)
    for item in value:
        if not isinstance(item, Mapping):
            raise UnsupportedExecutionConfig(field, "entries must be objects")
        if set(item) - {
            "name", "account_type", "oms_type", "starting_balances", "base_currency",
            "native_config",
        }:
            raise UnsupportedExecutionConfig(field, "entry contains fields outside the frozen Nautilus schema")
        name = _nonempty_text(item.get("name"), "venues.name").upper()
        if name in seen:
            raise UnsupportedExecutionConfig("venues.name", f"duplicate Venue {name}")
        account_type = _nonempty_text(item.get("account_type"), "venues.account_type").upper()
        if account_type not in {"CASH", "MARGIN", "BETTING"}:
            raise UnsupportedExecutionConfig("venues.account_type", "must be CASH, MARGIN, or BETTING")
        oms_type = _nonempty_text(item.get("oms_type"), "venues.oms_type").upper()
        if oms_type not in {"NETTING", "HEDGING"}:
            raise UnsupportedExecutionConfig("venues.oms_type", "must be NETTING or HEDGING")
        base = _nonempty_text(item.get("base_currency"), "venues.base_currency").upper()
        if base != currency:
            raise UnsupportedExecutionConfig("venues.base_currency", "must match RunSpec base_currency")
        balances = item.get("starting_balances")
        if not isinstance(balances, list) or not balances:
            raise UnsupportedExecutionConfig("venues.starting_balances", "must be a nonempty Money string array")
        normalized_balances: list[str] = []
        balance_currencies: set[str] = set()
        for balance in balances:
            if not isinstance(balance, str):
                raise UnsupportedExecutionConfig("venues.starting_balances", "entries must be Nautilus Money strings")
            parts = balance.strip().replace(",", "").rsplit(None, 1)
            if len(parts) != 2:
                raise UnsupportedExecutionConfig("venues.starting_balances", "format must be '<amount> <currency>'")
            amount = _nonnegative_decimal(parts[0], "venues.starting_balances.amount")
            if amount <= 0:
                raise UnsupportedExecutionConfig("venues.starting_balances.amount", "must be greater than zero")
            balance_currency = _nonempty_text(parts[1], "venues.starting_balances.currency").upper()
            if balance_currency in balance_currencies:
                raise UnsupportedExecutionConfig("venues.starting_balances", f"duplicate currency {balance_currency}")
            if balance_currency != currency:
                raise UnsupportedExecutionConfig(
                    "venues.starting_balances.currency",
                    "cross-currency total capital is not yet valued by the FactorTester RunSpec adapter",
                )
            balance_currencies.add(balance_currency)
            normalized_balances.append(f"{amount} {balance_currency}")
            total += amount
        normalized_balances.sort()
        from server.services.nautilus_bridge.native_configuration import freeze_native_venue_config

        native_input = item.get("native_config")
        if native_input is None:
            native_input = _legacy_native_venue_config(legacy_settings or {}, base)

        try:
            native_config = freeze_native_venue_config(native_input)
        except UnsupportedExecutionConfig:
            raise
        except ValueError as exc:
            raise UnsupportedExecutionConfig("venues.native_config", str(exc)) from exc
        if native_config["fee_model"]["type"] in {"unconfigured", "inherit"}:
            native_config["fee_model"] = _legacy_native_fee_model(
                legacy_settings or {}, native_config["fee_model"], base,
            )
        fee_model = native_config["fee_model"]
        if fee_model.get("type") in {"fixed", "per_contract"}:
            fee_currency = str(fee_model["commission"]).rsplit(" ", 1)[-1]
            if fee_currency != base:
                raise UnsupportedExecutionConfig(
                    "venues.native_config.fee_model.commission",
                    f"fee currency {fee_currency} must match Venue base currency {base}",
                )
        result.append({
            "name": name, "account_type": account_type, "oms_type": oms_type,
            "starting_balances": normalized_balances, "base_currency": base,
            "native_config": native_config,
        })
        seen.add(name)
    if total != capital:
        raise UnsupportedExecutionConfig(
            "venues.starting_balances", "Venue balances must sum to initial_capital_major; cash is not implicitly shared",
        )
    return tuple(sorted(result, key=lambda item: item["name"]))


def _legacy_native_venue_config(settings: Mapping[str, Any], base_currency: str) -> dict[str, Any]:
    """Translate only old draft defaults into the new per-Venue Nautilus contract."""
    native: dict[str, Any] = {}
    capacity = str(settings.get("nt_capacity_policy") or "unconstrained")
    if capacity in {"bar_volume", "recorded_depth"}:
        native["liquidity_consumption"] = True
    if capacity == "recorded_depth":
        native["book_type"] = "L2_MBP"
    native["price_protection_points"] = settings.get("nt_price_protection_points", 0)
    options = settings.get("nautilus_venue")
    if isinstance(options, Mapping):
        native["bar_volume_weights_bps"] = options.get("bar_volume_weights_bps")
        native["bar_volume_remainder_to"] = options.get("bar_volume_remainder_to", "close")
    native["fee_model"] = _legacy_native_fee_model(
        settings, {"type": "unconfigured"}, base_currency,
    )
    return native


def _legacy_native_fee_model(
    settings: Mapping[str, Any], current: Mapping[str, Any], base_currency: str,
) -> dict[str, Any]:
    if current.get("type") not in {"unconfigured", "inherit"}:
        return dict(current)
    mode = str(settings.get("fee_mode") or "").strip().lower()
    if mode == "zero":
        return {"type": "zero"}
    if mode == "per_contract":
        amount = _nonnegative_decimal(settings.get("fee_per_contract"), "fee_per_contract")
        currency = _nonempty_text(settings.get("fee_currency") or base_currency, "fee_currency").upper()
        return {"type": "per_contract", "commission": f"{amount} {currency}"}
    if mode == "historical_schedule":
        schedule_ref = _nonempty_text(settings.get("fee_schedule_ref"), "fee_schedule_ref")
        return {"type": "historical_schedule", "schedule_ref": schedule_ref}
    return {"type": "unconfigured"}


def _compile_venue_capacity(
    venues: tuple[dict[str, Any], ...], *, feed_kind: FeedKind,
) -> tuple[CapacityPlan, tuple[dict[str, object], ...]]:
    """Summarize native capacity behavior without reinterpreting legacy global toggles."""
    details: list[dict[str, object]] = []
    for venue in venues:
        native = venue["native_config"]
        consumes = bool(native["liquidity_consumption"])
        book_type = str(native["book_type"])
        if not consumes:
            kind = "unconstrained"
        elif book_type in {"L2_MBP", "L3_MBO"}:
            expected = "l2" if book_type == "L2_MBP" else "l3"
            if feed_kind != expected:
                raise UnsupportedExecutionConfig(
                    f"venues.{venue['name']}.native_config.book_type",
                    f"{book_type} liquidity consumption requires {expected.upper()} market data; received {feed_kind}",
                )
            kind = "recorded_depth"
        elif feed_kind == "bar" and native["bar_execution"]:
            kind = "bar_volume"
        else:
            kind = "native_liquidity"
        details.append({
            "venue": venue["name"],
            "capacity_kind": kind,
            "book_type": book_type,
            "liquidity_consumption": consumes,
            "price_protection_points": int(native["price_protection_points"]),
            "bar_volume_weights_bps": native["bar_volume_weights_bps"],
            "bar_volume_remainder_to": native["bar_volume_remainder_to"],
        })
    kinds = {str(item["capacity_kind"]) for item in details}
    policies = {
        (
            str(item["capacity_kind"]), str(item["book_type"]),
            bool(item["liquidity_consumption"]), int(item["price_protection_points"]),
            tuple(item["bar_volume_weights_bps"] or ()),
            str(item["bar_volume_remainder_to"]),
        )
        for item in details
    }
    single_kind = next(iter(kinds)) if len(kinds) == 1 and len(policies) == 1 else "mixed"
    first = details[0]
    weights = first["bar_volume_weights_bps"] if single_kind == "bar_volume" else None
    summary = CapacityPlan(
        kind=single_kind, feed_kind=feed_kind,
        liquidity_consumption=any(bool(item["liquidity_consumption"]) for item in details),
        price_protection_points=max(int(item["price_protection_points"]) for item in details),
        bar_volume_weights_bps=(tuple(weights) if weights is not None else None),
        bar_volume_remainder_to=str(first["bar_volume_remainder_to"]),
        assumptions=("Per-Venue Nautilus matching and liquidity parameters are authoritative.",),
    )
    return summary, tuple(details)


def _parse_strategy_venue_bindings(
    value: object, venues: tuple[dict[str, Any], ...], scopes: tuple[str, ...],
) -> tuple[dict[str, Any], ...]:
    field = "strategy_venue_bindings"
    if not isinstance(value, list) or not value:
        raise UnsupportedExecutionConfig(field, "requires one route for every strategy instance")
    venue_names = {item["name"] for item in venues}
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    referenced_venues: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping):
            raise UnsupportedExecutionConfig(field, "entries must be objects")
        if set(item) - {"strategy_id", "venue_ids", "product_scope_refs"}:
            raise UnsupportedExecutionConfig(field, "entry contains fields outside the frozen route schema")
        strategy_id = _nonempty_text(item.get("strategy_id"), f"{field}.strategy_id")
        if strategy_id in seen:
            raise UnsupportedExecutionConfig(f"{field}.strategy_id", f"duplicate strategy {strategy_id}")
        venue_ids = item.get("venue_ids")
        if not isinstance(venue_ids, list) or not venue_ids:
            raise UnsupportedExecutionConfig(f"{field}.venue_ids", f"strategy {strategy_id} needs one or more venues")
        normalized_venues = sorted({_nonempty_text(name, f"{field}.venue_ids").upper() for name in venue_ids})
        unknown = set(normalized_venues) - venue_names
        if unknown:
            raise UnsupportedExecutionConfig(f"{field}.venue_ids", f"unknown Venue(s): {', '.join(sorted(unknown))}")
        raw_scopes = item.get("product_scope_refs")
        if not isinstance(raw_scopes, list) or not raw_scopes:
            raise UnsupportedExecutionConfig(f"{field}.product_scope_refs", f"strategy {strategy_id} needs frozen product scopes")
        strategy_scopes = sorted({_nonempty_text(ref, f"{field}.product_scope_refs") for ref in raw_scopes})
        if not set(strategy_scopes).issubset(scopes):
            raise UnsupportedExecutionConfig(f"{field}.product_scope_refs", f"strategy {strategy_id} references an unfrozen product scope")
        result.append({
            "strategy_id": strategy_id,
            "venue_ids": normalized_venues,
            "product_scope_refs": strategy_scopes,
        })
        seen.add(strategy_id)
        referenced_venues.update(normalized_venues)
    if referenced_venues != venue_names:
        raise UnsupportedExecutionConfig(
            field, "every configured Venue must be referenced by at least one strategy",
        )
    return tuple(sorted(result, key=lambda item: item["strategy_id"]))


def _nonempty_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UnsupportedExecutionConfig(field, "must be a nonempty string")
    return value.strip()


def _aware_utc(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise UnsupportedExecutionConfig(field, "must be an ISO timestamp with UTC offset")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise UnsupportedExecutionConfig(field, "must be an ISO timestamp with UTC offset") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise UnsupportedExecutionConfig(field, "must include a UTC offset")
    return parsed.astimezone(timezone.utc).isoformat()


def _nonnegative_decimal(value: object, field: str) -> Decimal:
    if isinstance(value, bool):
        raise UnsupportedExecutionConfig(field, "must be a finite nonnegative number")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise UnsupportedExecutionConfig(field, "must be a finite nonnegative number") from exc
    if not amount.is_finite() or amount < 0:
        raise UnsupportedExecutionConfig(field, "must be a finite nonnegative number")
    return amount


def _participation_rate(value: object) -> Decimal:
    if isinstance(value, bool):
        raise UnsupportedExecutionConfig("participation_rate", "must be between 0 and 1")
    try:
        rate = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise UnsupportedExecutionConfig("participation_rate", "must be between 0 and 1") from exc
    if not rate.is_finite() or rate <= 0 or rate > 1:
        raise UnsupportedExecutionConfig("participation_rate", "must be in (0, 1]")
    return rate


def _daily_mark_to_market_request(value: object) -> Literal["auto", "enabled", "disabled"]:
    """Normalize the RunSpec intent; eligibility is resolved per product later."""
    if value is None or value == "":
        return "auto"
    if value is True:
        return "enabled"
    if value is False:
        return "disabled"
    text = str(value).strip().lower()
    if text in {"auto", "automatic"}:
        return "auto"
    if text in {"1", "true", "yes", "on", "enabled"}:
        return "enabled"
    if text in {"0", "false", "no", "off", "disabled"}:
        return "disabled"
    raise UnsupportedExecutionConfig(
        "daily_mark_to_market_enabled", "must be auto, true, or false",
    )


def _normalize_cost_basis(value: object, field: str) -> str | None:
    if value is None or value == "":
        return None
    normalized = str(value).strip().upper().replace("-", "_").replace(" ", "_")
    aliases = {
        "WEIGHTAVERAGE": "WEIGHTED_AVERAGE",
        "WEIGHTEDAVERAGE": "WEIGHTED_AVERAGE",
        "WEIGHTED_AVERAGE": "WEIGHTED_AVERAGE",
        "FIFO": "FIFO",
        "LIFO": "LIFO",
        "HIFO": "HIFO",
    }
    if normalized in {"AUTO", "AUTOMATIC"}:
        return None
    if normalized not in aliases:
        raise UnsupportedExecutionConfig(
            field,
            "must be auto, WeightAverage, FIFO, LIFO, or HIFO",
        )
    return aliases[normalized]


def _nonnegative_int(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise UnsupportedExecutionConfig(field, "must be a nonnegative integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise UnsupportedExecutionConfig(field, "must be a nonnegative integer") from exc
    if str(value).strip() != str(parsed) or parsed < 0:
        raise UnsupportedExecutionConfig(field, "must be a nonnegative integer")
    return parsed


def _nautilus_bar_volume_allocation(
    value: object,
) -> tuple[tuple[int, int, int, int] | None, Literal["open", "high", "low", "close"]]:
    """Validate Nautilus' native OHLC volume kwargs; ``None`` preserves its defaults."""
    if value is None:
        return None, "close"
    field = "nautilus_venue"
    if not isinstance(value, Mapping):
        raise UnsupportedExecutionConfig(
            field, "must be an object of Nautilus venue options",
        )
    allowed = {"bar_volume_weights_bps", "bar_volume_remainder_to"}
    unknown = set(value) - allowed
    if unknown:
        raise UnsupportedExecutionConfig(
            field, "unmapped Nautilus venue options: " + ", ".join(sorted(map(str, unknown))),
        )
    raw_weights = value.get("bar_volume_weights_bps")
    weights = None
    if raw_weights is not None:
        if not isinstance(raw_weights, (list, tuple)) or len(raw_weights) != 4:
            raise UnsupportedExecutionConfig(
                "nautilus_venue.bar_volume_weights_bps", "must contain O/H/L/C weights",
            )
        normalized: list[int] = []
        for weight in raw_weights:
            if isinstance(weight, bool) or not isinstance(weight, int) or weight < 0:
                raise UnsupportedExecutionConfig(
                    "nautilus_venue.bar_volume_weights_bps", "must contain nonnegative integers",
                )
            normalized.append(weight)
        if sum(normalized) != 10_000:
            raise UnsupportedExecutionConfig(
                "nautilus_venue.bar_volume_weights_bps", "must sum to 10000 basis points",
            )
        weights = (normalized[0], normalized[1], normalized[2], normalized[3])
    remainder = value.get("bar_volume_remainder_to", "close")
    if remainder not in {"open", "high", "low", "close"}:
        raise UnsupportedExecutionConfig(
            "nautilus_venue.bar_volume_remainder_to", "must be open, high, low, or close",
        )
    return weights, remainder
