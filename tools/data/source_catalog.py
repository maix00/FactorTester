"""Source-owned market-data catalog declarations.

Execution providers and live connectors have different implementations, but
the product catalog needs one small interface for both.  Source modules own
these declarations; catalog and UI code only project them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Callable

from tools.data.availability.schema import availability_dimensions


ProductPredicate = Callable[[Any], bool]
MemberLoader = Callable[[], tuple["DataSourceMember", ...]]


@dataclass(frozen=True, slots=True)
class DataSourceMode:
    """One orthogonal market-data capability declared by a source."""

    key: str
    title_zh: str
    sampling_mode: str
    frequency: Any | None
    data_kind: str
    market_depth: str
    delivery_mode: str
    available: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.key,
            "title_zh": self.title_zh,
            "available": self.available,
            **availability_dimensions(
                sampling_mode=self.sampling_mode,
                frequency=self.frequency,
                data_kind=self.data_kind,
                market_depth=self.market_depth,
                delivery_mode=self.delivery_mode,
            ),
        }


@dataclass(frozen=True, slots=True)
class DataSourceMember:
    """A catalog-visible feed offered by one data source."""

    key: str
    label: str
    supports: ProductPredicate
    available: ProductPredicate
    mode: DataSourceMode
    timezone: str = ""
    time_columns: dict[str, str] = field(default_factory=dict)
    data_columns: dict[str, str] = field(default_factory=dict)
    execution_provider: Any | None = field(default=None, repr=False, compare=False)
    naming_scheme: str = "canonical"

    @property
    def frequency(self) -> str:
        return str(self.mode.as_dict().get("frequency") or "")

    @property
    def dimensions(self) -> dict[str, Any]:
        value = self.mode.as_dict()
        return {
            key: value[key]
            for key in (
                "sampling_mode", "frequency", "data_kind",
                "market_depth", "delivery_mode",
            )
        }

    def supports_product(self, product: Any) -> bool:
        return _safe_predicate(self.supports, product)

    def has_available_data(self, product: Any) -> bool:
        return _safe_predicate(self.available, product)


@dataclass(frozen=True, slots=True)
class DataSourceDeclaration:
    """Server-runtime catalog declaration owned by a source module.

    Client-owned connectors use the separate local-source manifest contract and
    are deliberately never registered in this process-wide registry.
    """

    key: str
    label: str
    provider_kind: str
    member_loader: MemberLoader
    empty_status: str = "empty"
    connector_key: str | None = None

    @property
    def members(self) -> tuple[DataSourceMember, ...]:
        return tuple(self.member_loader())

    def supports_product(self, product: Any) -> bool:
        return any(member.supports_product(product) for member in self.members)

    def has_available_data(self, product: Any) -> bool:
        return any(member.has_available_data(product) for member in self.members)

    def execution_providers(self) -> tuple[Any, ...]:
        return tuple(
            member.execution_provider
            for member in self.members
            if member.execution_provider is not None
        )

    def modes(self) -> tuple[DataSourceMode, ...]:
        result: list[DataSourceMode] = []
        identities: set[tuple[Any, ...]] = set()
        for member in self.members:
            mode = member.mode
            identity = tuple(mode.as_dict().get(key) for key in (
                "sampling_mode", "frequency", "data_kind",
                "market_depth", "delivery_mode",
            ))
            if identity not in identities:
                identities.add(identity)
                result.append(mode)
        return tuple(result)


_DECLARATIONS: dict[str, DataSourceDeclaration] = {}
_LOCK = RLock()


def register_data_source(declaration: DataSourceDeclaration) -> None:
    """Register a source declaration without replacing another source."""
    with _LOCK:
        current = _DECLARATIONS.get(declaration.key)
        if current is not None and current is not declaration:
            raise ValueError(f"data source is already registered: {declaration.key}")
        _DECLARATIONS[declaration.key] = declaration


def data_source_declarations() -> tuple[DataSourceDeclaration, ...]:
    with _LOCK:
        return tuple(_DECLARATIONS.values())


def data_source_declaration(key: str) -> DataSourceDeclaration | None:
    with _LOCK:
        return _DECLARATIONS.get(str(key or ""))


def historical_source_declaration(
    *,
    key: str,
    label: str,
    providers: Callable[[], tuple[Any, ...]],
) -> DataSourceDeclaration:
    """Adapt registered bar providers to the common catalog interface."""

    def load_members() -> tuple[DataSourceMember, ...]:
        return tuple(_historical_member(provider) for provider in providers())

    return DataSourceDeclaration(
        key=key,
        label=label,
        provider_kind="historical_bundle",
        member_loader=load_members,
    )


def _historical_member(provider: Any) -> DataSourceMember:
    frequency = getattr(provider, "freq", None)
    frequency_name = str(getattr(frequency, "name", frequency) or "")
    mode = DataSourceMode(
        key=f"historical_{frequency_name.lower()}",
        title_zh=f"历史 {frequency_name} K线",
        sampling_mode="bar",
        frequency=frequency,
        data_kind="ohlcv_bar",
        market_depth="not_applicable",
        delivery_mode="historical_snapshot",
    )

    def supports(product: Any) -> bool:
        checker = getattr(provider, "supports_product", None)
        return bool(checker(product) if callable(checker) else product in provider)

    def available(product: Any) -> bool:
        return bool(product in provider)

    return DataSourceMember(
        key=str(getattr(provider, "key", "")),
        label=str(getattr(provider, "label", "") or getattr(provider, "key", "")),
        supports=supports,
        available=available,
        mode=mode,
        timezone=str(getattr(provider, "timezone", "") or ""),
        time_columns=dict(getattr(provider, "time_cols_mapping", {}) or {}),
        data_columns=dict(getattr(provider, "data_cols_mapping", {}) or {}),
        execution_provider=provider,
        naming_scheme=str(
            getattr(provider, "naming_scheme", "canonical") or "canonical"
        ),
    )


def _safe_predicate(predicate: ProductPredicate, product: Any) -> bool:
    try:
        return bool(predicate(product))
    except Exception:
        return False
