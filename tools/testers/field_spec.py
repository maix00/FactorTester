"""Lifecycle-aware value descriptors shared by tester field projections.

The descriptor deliberately describes the value before describing how a
particular client edits it.  ``SettingDefinition``, ``FieldDefinition`` and
``RunFieldDefinition`` keep their lifecycle-specific metadata, while this
module provides the common value contract and a narrow legacy adapter.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, ClassVar


VALUE_TYPES = frozenset({
    "boolean", "integer", "number", "string", "date", "time", "duration",
    "enum", "reference", "object", "array", "grid", "source_file",
    "output_request",
})
CARDINALITIES = frozenset({"one", "many"})


@dataclass(frozen=True, slots=True)
class ValueDescriptor:
    """Canonical shape of a field value, independent of its lifecycle."""

    value_type: str
    cardinality: str = "one"
    editor: str = "input"
    format: str = ""
    unit: str = ""
    option_source: str = ""
    resolver: str = ""
    item_type: str = ""
    ref_kind: str = ""
    schema: dict[str, Any] = field(default_factory=dict)
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None

    def __post_init__(self) -> None:
        if self.value_type not in VALUE_TYPES:
            raise ValueError(f"unknown field value type: {self.value_type}")
        if self.cardinality not in CARDINALITIES:
            raise ValueError(f"unknown field cardinality: {self.cardinality}")
        if self.cardinality == "many" and not (
            self.item_type or self.value_type in {"array", "grid", "output_request"}
        ):
            raise ValueError("multi-value fields require item_type or a collection type")
        if self.minimum is not None and self.maximum is not None:
            if self.minimum > self.maximum:
                raise ValueError("field minimum cannot exceed maximum")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SettingRole:
    scope_policy: str
    template_policy: str = "include"


@dataclass(frozen=True, slots=True)
class RuntimeRole:
    owner: str = ""
    execution_policy: str = "include"


@dataclass(frozen=True, slots=True)
class RunRole:
    request_location: str
    freeze_target: str
    placement: str
    template_policy: str = "exclude"


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """Canonical field identity with explicit lifecycle roles.

    Role metadata is optional only when the role is absent.  This prevents a
    run-only field from accidentally receiving template or Flow properties
    merely because all definitions share one Python class in the future.
    """

    key: str
    value: ValueDescriptor
    roles: frozenset[str] = frozenset()
    setting: SettingRole | None = None
    runtime: RuntimeRole | None = None
    run: RunRole | None = None
    _ROLES: ClassVar[frozenset[str]] = frozenset({"setting", "runtime", "run"})

    def __post_init__(self) -> None:
        unknown = set(self.roles) - self._ROLES
        if unknown:
            raise ValueError(f"unknown field roles: {sorted(unknown)}")
        metadata = {
            "setting": self.setting,
            "runtime": self.runtime,
            "run": self.run,
        }
        for role, value in metadata.items():
            if (role in self.roles) != (value is not None):
                raise ValueError(f"field role {role} metadata does not match roles")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("_ROLES", None)
        value["roles"] = sorted(self.roles)
        return value


def _duration_format(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    units = ("ns", "us", "µs", "ms", "s", "m", "h", "d", "w")
    number = text[:-1] if text.endswith(units) else ""
    if text.endswith("us") or text.endswith("µs") or text.endswith("ms"):
        number = text[:-2]
    return "duration" if number and _is_number(number) else ""


def _is_number(value: str) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def infer_value_descriptor(
    control_template: str,
    default: Any = None,
    *,
    field_key: str = "",
    options: tuple[Any, ...] = (),
    serialization: dict[str, Any] | None = None,
    minimum: float | None = None,
    maximum: float | None = None,
    step: float | None = None,
    instance_class: type | str | None = None,
) -> ValueDescriptor:
    """Map the current registration vocabulary to the typed contract.

    This is intentionally an adapter, not the long-term authoring API.  New
    fields should provide an explicit descriptor once the registry migration
    is complete; existing fields remain executable without edits.
    """

    template = str(control_template or "text")
    key = str(field_key or "")
    serial = serialization or {}
    kind = str(serial.get("kind", ""))
    is_many = bool(serial.get("multi")) or kind.endswith("_list")
    dynamic_reference_keys = {
        "factor",
        "category",
        "data_source",
        "frequency",
        "counterparty_profile",
        "base_currency",
        "product_path_selection",
    }
    option_source = str(
        serial.get("option_source")
        or serial.get("catalog_endpoint")
        or (f"catalog.{key}" if key in dynamic_reference_keys else "")
    )
    resolver = str(
        serial.get("resolver")
        or serial.get("native_catalog_action")
        or ""
    )
    if template == "boolean":
        return ValueDescriptor("boolean")
    if template == "number":
        integer = isinstance(default, int) and not isinstance(default, bool)
        return ValueDescriptor(
            "integer" if integer else "number", minimum=minimum, maximum=maximum,
            step=step,
        )
    if template == "date":
        return ValueDescriptor("date", editor="date")
    if template == "time":
        return ValueDescriptor("time", editor="time")
    if template == "ic_horizon_grid" or template == "ic_delay_grid" \
            or template == "ic_decay_grid":
        return ValueDescriptor("grid", editor="grid", item_type="integer")
    if template == "factor_role_bindings":
        return ValueDescriptor("object", editor="role_binding")
    if template == "custom_product_overrides":
        return ValueDescriptor("array", editor="custom_product_overrides", item_type="object")
    if template in {"profile", "service_port"}:
        return ValueDescriptor("reference", editor=template, ref_kind=template)
    if template == "artifact_output_picker":
        return ValueDescriptor(
            "output_request", cardinality="many", editor="output_picker",
            item_type="reference", ref_kind="artifact",
        )
    if template == "select":
        reference_kind = ""
        if (
            instance_class is not None
            or key in dynamic_reference_keys
            or "selection" in kind
            or "candidate" in kind
        ):
            reference_kind = kind or "catalog"
        if reference_kind:
            return ValueDescriptor(
                "reference", editor="catalog", ref_kind=reference_kind,
                format="frequency" if key in {"frequency", "signal_freq", "calendar_frequency"} else "",
                cardinality="many" if is_many else "one",
                item_type="reference" if is_many else "",
                option_source=option_source,
                resolver=resolver,
            )
        return ValueDescriptor(
            "enum",
            editor="select",
            format="frequency" if key in {"frequency", "signal_freq", "calendar_frequency"} else "",
            option_source="manifest.options" if not options else "",
        )
    if template == "custom":
        if "selection" in kind or "candidate" in kind or is_many:
            return ValueDescriptor(
                "reference", cardinality="many" if is_many else "one",
                editor="catalog", ref_kind=kind or "catalog",
                item_type="reference" if is_many else "",
                option_source=option_source or f"catalog.{kind or 'selection'}",
                resolver=resolver,
            )
        duration = _duration_format(default)
        if duration:
            return ValueDescriptor("duration", editor="input", format=duration)
        return ValueDescriptor(
            "object" if isinstance(default, dict) or default is None else "string",
            editor="json",
        )
    if template == "text":
        duration = _duration_format(default)
        if duration:
            return ValueDescriptor("duration", editor="input", format=duration)
        return ValueDescriptor("string", editor="input")
    return ValueDescriptor("string", editor="input")
