"""Metadata-only requirements and node-local source binding.

No discovery, network I/O, plugin imports, permissions, or market-data reads.
Manager passes only authorized offers from its existing service projection.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json


def _text(value: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 2048:
        raise ValueError("identity/semantic fields must be non-empty text")


def _ref(kind: str, value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return kind + ":" + hashlib.sha256(encoded.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class BarRequirement:
    """RunSpec input semantics, independent of any node, Bundle or provider.

    bar_spec is the source-declared canonical instrument-independent Bar spec,
    e.g. 1-MINUTE-LAST-EXTERNAL, not merely a display label such as MIN1.
    UTC nanoseconds describe the required input interval (including warmup).
    """
    product_ref: str
    bar_spec: str
    price_basis: str
    time_semantics: str
    fields: tuple[str, ...]
    start_ns: int
    end_ns: int

    def __post_init__(self) -> None:
        for value in (self.product_ref, self.bar_spec, self.price_basis, self.time_semantics):
            _text(value)
        _fields(self.fields)
        _interval(self.start_ns, self.end_ns)

    @property
    def equivalence_ref(self) -> str:
        """Interchangeable semantics, never a claim of identical market bytes."""
        return _ref("bar-semantics", [self.product_ref, self.bar_spec,
                                      self.price_basis, self.time_semantics])

    @property
    def requirement_ref(self) -> str:
        payload = asdict(self)
        payload["fields"] = sorted(self.fields)
        return _ref("bar-requirement", payload)


def _fields(values: tuple[str, ...]) -> None:
    if not isinstance(values, tuple) or not values or len(set(values)) != len(values):
        raise ValueError("fields must be a non-empty unique tuple")
    for value in values:
        _text(value)


def _interval(start: int, end: int) -> None:
    if type(start) is not int or type(end) is not int or start > end:
        raise ValueError("interval must be ordered integer UTC nanoseconds")


@dataclass(frozen=True, slots=True)
class BundleInstallation:
    """One independently installed Bundle on one execution node.

    Identity survives package upgrades. The same package on two nodes is two
    installations even when both nodes use one machine or shared cache files.
    """
    authority: str
    node_id: str
    installation_id: str
    bundle_id: str
    bundle_version: str
    bundle_fingerprint: str
    owner: str

    def __post_init__(self) -> None:
        for value in asdict(self).values():
            _text(value)
        digest = self.bundle_fingerprint.removeprefix("sha256:")
        if not self.bundle_fingerprint.startswith("sha256:") or len(digest) != 64:
            raise ValueError("Bundle metadata fingerprint must be sha256")
        try:
            int(digest, 16)
        except ValueError as exc:
            raise ValueError("Bundle metadata fingerprint must be sha256") from exc

    @property
    def installation_ref(self) -> str:
        return _ref("bundle-installation", [self.authority, self.owner, self.node_id,
                                            self.installation_id, self.bundle_id])

    def source_ref(self, member_id: str) -> str:
        _text(member_id)
        return _ref("installed-source", [self.installation_ref, member_id])


@dataclass(frozen=True, slots=True)
class ServiceDeployment:
    """Execution target; endpoint/IP/port are separately managed routing metadata."""
    manager_id: str
    node_id: str
    service_id: str
    deployment_ref: str
    test_types: tuple[str, ...]

    def __post_init__(self) -> None:
        for value in (self.manager_id, self.node_id, self.service_id, self.deployment_ref):
            _text(value)
        _fields(self.test_types)


@dataclass(frozen=True, slots=True)
class BarOffer:
    installation: BundleInstallation
    member_id: str
    product_ref: str
    bar_spec: str
    price_basis: str
    time_semantics: str
    fields: tuple[str, ...]
    coverage_start_ns: int | None
    coverage_end_ns: int | None
    available: bool

    def __post_init__(self) -> None:
        for value in (self.member_id, self.product_ref, self.bar_spec,
                      self.price_basis, self.time_semantics):
            _text(value)
        _fields(self.fields)
        if type(self.available) is not bool:
            raise ValueError("available must be a boolean")
        if (self.coverage_start_ns is None) != (self.coverage_end_ns is None):
            raise ValueError("coverage requires both endpoints or neither")
        if self.coverage_start_ns is not None:
            _interval(self.coverage_start_ns, self.coverage_end_ns)

    @property
    def source_ref(self) -> str:
        return self.installation.source_ref(self.member_id)

    def matches(self, requirement: BarRequirement) -> bool:
        # Metadata coverage is a preliminary bound, not proof that no gaps exist.
        return (
            self.available
            and self.product_ref == requirement.product_ref
            and self.bar_spec == requirement.bar_spec
            and self.price_basis == requirement.price_basis
            and self.time_semantics == requirement.time_semantics
            and set(requirement.fields).issubset(self.fields)
            and self.coverage_start_ns is not None
            and self.coverage_start_ns <= requirement.start_ns
            and self.coverage_end_ns >= requirement.end_ns
        )


@dataclass(frozen=True, slots=True)
class BoundBarInput:
    """ExecutionPlan binding; original source-independent requirement is retained."""
    requirement: BarRequirement
    target: ServiceDeployment
    offer: BarOffer

    def revalidate(self, target: ServiceDeployment, offer: BarOffer) -> None:
        """Check current authorized deployment metadata before source loading.

        Market revision is deliberately not compared: mutable sources own that
        policy. Their observed revision belongs in the per-run read receipt.
        """
        if target != self.target:
            raise ValueError("execution deployment changed; replan required")
        if (offer.installation != self.offer.installation
                or offer.member_id != self.offer.member_id
                or not offer.matches(self.requirement)):
            raise ValueError("selected source installation changed or is unavailable")


def compatible_bar_offers(
    requirement: BarRequirement, target: ServiceDeployment, offers: tuple[BarOffer, ...],
) -> tuple[BarOffer, ...]:
    """Filter already-authorized metadata; never probes remote source files."""
    return tuple(offer for offer in offers
                 if offer.installation.authority == target.manager_id
                 and offer.installation.node_id == target.node_id
                 and offer.matches(requirement))


def bind_bar_input(
    requirement: BarRequirement, target: ServiceDeployment, *, test_type: str,
    offers: tuple[BarOffer, ...], selected_source_ref: str,
) -> BoundBarInput:
    """Bind an explicit choice. Missing/ambiguous selections never fall back."""
    if test_type not in target.test_types:
        raise ValueError("test type is unavailable on selected deployment")
    selected = tuple(offer for offer in compatible_bar_offers(requirement, target, offers)
                     if offer.source_ref == selected_source_ref)
    if len(selected) != 1:
        raise ValueError("selected source is missing, ambiguous or incompatible")
    return BoundBarInput(requirement, target, selected[0])
