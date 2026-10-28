"""Source-owned feed discovery with explicit NautilusTrader adapter admission.

The product catalog declares what a server can supply.  An NT adapter is a
separate, tested conversion contract: a visible feed does not automatically
become executable.  Discovery is lazy so importing Manager never scans local
market-data files or imports NautilusTrader.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Any

from server.services.nautilus_bridge.native_configuration import NAUTILUS_BOOK_TYPES
from traderesearch_data.nautilus import NautilusAdapterContract as AdapterContract

_NAUTILUS_BOOK_TYPES = frozenset(NAUTILUS_BOOK_TYPES)


class UnsupportedNautilusSource(ValueError):
    """A declared source cannot yet be converted without guessing semantics."""


@dataclass(frozen=True, slots=True)
class SourceCapability:
    family_key: str
    member_key: str
    frequency: str
    sampling_mode: str
    data_kind: str
    market_depth: str
    delivery_mode: str
    mode_available: bool
    timezone: str
    layout: str
    naming_scheme: str
    time_columns: tuple[tuple[str, str], ...]
    data_columns: tuple[tuple[str, str], ...]
    adapter_id: str | None
    reason: str
    instrument_scope: str = "unspecified"
    bar_time_semantics: str = "unspecified"
    raw_timestamp_unit: str = "unspecified"
    supported_book_types: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResolvedSource:
    capability: SourceCapability
    adapter: AdapterContract
    execution_provider: Any
    member: Any
    bundle_related_members: tuple[str, ...] = ()


def _items(value: Any) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((str(k), str(v)) for k, v in dict(value or {}).items()))


def _member_metadata(family_key: str, member: Any) -> SourceCapability:
    mode = member.mode.as_dict()
    provider = member.execution_provider
    return SourceCapability(
        family_key=str(family_key), member_key=str(member.key),
        frequency=str(member.frequency or ""),
        sampling_mode=str(mode.get("sampling_mode") or ""),
        data_kind=str(mode.get("data_kind") or ""),
        market_depth=str(mode.get("market_depth") or ""),
        delivery_mode=str(mode.get("delivery_mode") or ""),
        mode_available=mode.get("available") is True,
        timezone=str(member.timezone or ""),
        layout=str(getattr(provider, "contract_data_layout", "") or ""),
        naming_scheme=str(member.naming_scheme or ""),
        time_columns=_items(member.time_columns),
        data_columns=_items(member.data_columns),
        adapter_id=None, reason="no verified NautilusTrader adapter",
        instrument_scope=str(getattr(member, "instrument_scope", "unspecified")),
        bar_time_semantics=str(getattr(member, "bar_time_semantics", "unspecified")),
        raw_timestamp_unit=str(getattr(member, "raw_timestamp_unit", "unspecified")),
    )


def _contract_matches(capability: SourceCapability, contract: AdapterContract) -> bool:
    return all((
        capability.member_key == contract.member_key,
        capability.frequency == contract.frequency,
        capability.sampling_mode == contract.sampling_mode,
        capability.data_kind == contract.data_kind,
        capability.market_depth == contract.market_depth,
        capability.delivery_mode == contract.delivery_mode,
        capability.mode_available,
        capability.timezone == contract.timezone,
        capability.layout == contract.layout,
        capability.naming_scheme == contract.naming_scheme,
        set(contract.required_time_columns).issubset(capability.time_columns),
        set(contract.required_data_columns).issubset(capability.data_columns),
        bool(contract.clock_policy), bool(contract.product_scope),
        bool(contract.adapter_id),
        capability.instrument_scope == contract.instrument_scope,
        capability.bar_time_semantics == contract.bar_time_semantics,
        capability.raw_timestamp_unit == contract.raw_timestamp_unit,
        bool(contract.supported_book_types),
        set(contract.supported_book_types).issubset(_NAUTILUS_BOOK_TYPES),
    ))


class NautilusSourceRegistry:
    """Project all declared server feeds; admit only exact adapter contracts."""

    def __init__(
        self, declarations: Iterable[Any], adapters: Iterable[AdapterContract] = (),
        bundle_related: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self._bundle_related = dict(bundle_related or {})
        bindings: dict[str, AdapterContract] = {}
        for adapter in adapters:
            if not adapter.member_key or adapter.member_key in bindings:
                raise ValueError(f"duplicate or empty adapter key: {adapter.member_key!r}")
            bindings[adapter.member_key] = adapter
        members: dict[str, tuple[SourceCapability, Any]] = {}
        admitted_bindings: dict[str, AdapterContract] = {}
        for declaration in declarations:
            for member in declaration.members:
                capability = _member_metadata(declaration.key, member)
                if not capability.member_key or capability.member_key in members:
                    raise ValueError(f"duplicate or empty source member: {capability.member_key!r}")
                source_binding = getattr(member, "nautilus_adapter", None)
                if source_binding is not None and not isinstance(source_binding, AdapterContract):
                    raise TypeError(
                        f"{capability.member_key}: nautilus_adapter must be a "
                        "NautilusAdapterContract"
                    )
                injected_binding = bindings.get(capability.member_key)
                if source_binding is not None and injected_binding is not None:
                    if source_binding != injected_binding:
                        raise ValueError(
                            f"conflicting Nautilus adapter declarations for {capability.member_key}"
                        )
                binding = source_binding or injected_binding
                if binding is not None:
                    if binding.member_key != capability.member_key:
                        raise ValueError(
                            f"{capability.member_key}: adapter declares member {binding.member_key}"
                        )
                    previous = admitted_bindings.get(capability.member_key)
                    if previous is not None and previous != binding:
                        raise ValueError(
                            f"conflicting Nautilus adapter declarations for {capability.member_key}"
                        )
                    admitted_bindings[capability.member_key] = binding
                if binding is not None:
                    if _contract_matches(capability, binding) and member.execution_provider is not None:
                        capability = replace(
                            capability, adapter_id=binding.adapter_id, reason="",
                            supported_book_types=binding.supported_book_types,
                        )
                    else:
                        capability = replace(
                            capability, reason="adapter contract differs from source declaration",
                        )
                members[capability.member_key] = capability, member
        unknown_bindings = bindings.keys() - members.keys()
        if unknown_bindings:
            raise ValueError(f"adapter has no declared source: {sorted(unknown_bindings)}")
        self._members = members
        self._bindings = admitted_bindings

    def capabilities(self) -> tuple[SourceCapability, ...]:
        """Metadata only: never probe files or call a source's product predicate."""
        return tuple(value[0] for value in self._members.values())

    def adapter_for(
        self, *, source_key: str, frequency: str,
        instrument_scope: str = "physical_contract",
    ) -> AdapterContract:
        """Resolve one source-declared adapter by family/member and frequency."""
        selected = str(source_key or "").strip()
        matches = [
            (capability, self._bindings[member_key])
            for member_key, (capability, _member) in self._members.items()
            if capability.adapter_id is not None
            and capability.frequency == str(frequency).upper()
            and capability.instrument_scope == instrument_scope
            and selected in {capability.family_key, capability.member_key}
        ]
        if len(matches) == 1:
            return matches[0][1]
        if len(matches) > 1:
            keys = sorted(capability.member_key for capability, _ in matches)
            raise UnsupportedNautilusSource(
                f"{selected}: ambiguous {frequency} adapters: {', '.join(keys)}"
            )
        source_members = [
            capability for capability, _member in self._members.values()
            if selected in {capability.family_key, capability.member_key}
        ]
        if not source_members:
            raise UnsupportedNautilusSource(f"unknown server data source: {selected!r}")
        declared = sorted({capability.frequency for capability in source_members})
        raise UnsupportedNautilusSource(
            f"{selected}: no verified {frequency} Nautilus adapter "
            f"for {instrument_scope}; declared frequencies: {', '.join(declared) or 'none'}"
        )

    def resolve(self, member_key: str, *, frequency: str, product: Any) -> ResolvedSource:
        """Resolve exactly one source and product, without source/frequency fallback."""
        entry = self._members.get(str(member_key or ""))
        if entry is None:
            raise UnsupportedNautilusSource(f"unknown server source member: {member_key!r}")
        capability, member = entry
        if capability.frequency != frequency:
            raise UnsupportedNautilusSource(
                f"{member_key}: requested {frequency}, declared {capability.frequency}"
            )
        if capability.adapter_id is None:
            raise UnsupportedNautilusSource(f"{member_key}: {capability.reason}")
        if product is None or not member.supports_product(product):
            raise UnsupportedNautilusSource(f"{member_key}: product is outside source catalog")
        if not member.has_available_data(product):
            raise UnsupportedNautilusSource(f"{member_key}: product data is unavailable")
        return ResolvedSource(
            capability=capability,
            adapter=self._bindings[member_key],
            execution_provider=member.execution_provider,
            member=member,
            bundle_related_members=self._bundle_related.get(str(member_key), ()),
        )


def from_server_sources(
    *, adapters: Iterable[AdapterContract] = (),
) -> NautilusSourceRegistry:
    """Project currently registered feeds without enumerating product files.

    An adapter contract for a not-yet-registered member remains dormant.  A
    request to resolve that member fails closed. Source declaration hooks own
    their adapters and register without enumerating contracts or importing
    price services.
    """
    from sources.registry import installed_bundles, load_all_sources
    from tools.data.source_catalog import data_source_declarations

    load_all_sources()
    declarations = data_source_declarations()
    registered = {member.key for declaration in declarations for member in declaration.members}
    bundle_related = {
        member.id: tuple(member.related_members)
        for bundle in installed_bundles()
        for member in bundle.members
    }
    return NautilusSourceRegistry(
        declarations, (adapter for adapter in adapters if adapter.member_key in registered),
        bundle_related=bundle_related,
    )
