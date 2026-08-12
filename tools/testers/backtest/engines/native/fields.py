"""Core field/module primitives for the event-driven backtest engine
(issue-114). Lives in `engines/native/` (not `modules/`) specifically so
`flow.py` can import `FieldRef` without going through `modules/__init__.py`'s
eager imports of every concrete module (fee.py, margin.py, ...), which would
otherwise create a circular import the moment any of those modules defines
an ExecutableModule subclass (`__init_subclass__` needs `Flow`, `flow.py`
needs `FieldRef`).

`FieldRef` replaces bare string field names so typos are caught statically;
`FieldDefinition` replaces the old tuple-of-dict `setting_definitions`
mechanism and drives both Flow dependency wiring and frontend rendering.
`ExecutableModule` auto-fills `FieldRef.owner`/`Flow.owner` for any FieldRef
or Flow assigned as a class attribute on a subclass — that's what lets
external code write `LedgerModule.cash` instead of a magic string.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Generic, TypeVar

if TYPE_CHECKING:
    from tools.testers.registry import Module

T = TypeVar("T")


@dataclass(frozen=True)
class FieldRef(Generic[T]):
    name: str
    owner: str = ""  # auto-filled by ExecutableModule.__init_subclass__, not hand-written

    @property
    def qualified_name(self) -> str:
        return f"{self.owner}.{self.name}"

    def __repr__(self) -> str:
        return self.qualified_name

    def __hash__(self) -> int:
        return hash((self.owner, self.name))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FieldRef):
            return NotImplemented
        return self.owner == other.owner and self.name == other.name


@dataclass(frozen=True)
class FieldDefinition:
    """One declaration drives both the Flow dependency graph and frontend
    rendering — replaces the old `setting_definitions` tuple-of-dict
    mechanism entirely, not alongside it."""
    public: bool = False          # whether the user can configure this in the frontend/CLI
    default: Any = None
    frontend_only_default: bool = False  # `default` is a UI-display suggestion
        # only, not a real backend fallback -- if a strategy that activates
        # this field's owning module's Flows doesn't actually supply a value
        # for it, strategy_config_builder.build_strategy_configs must raise,
        # not silently substitute `default`. False (the common case) means
        # `default` IS a legitimate backend fallback when the value is absent.
    default_enabled: bool = True  # only meaningful for public fields
    # The following mirror the old setting_definitions rendering contract;
    # field names kept identical so the frontend ChipRenderer/tab rendering
    # logic doesn't need to change:
    label: str = ""
    tab: str = ""
    control_template: str = ""           # "select"/"number"/"date"/"boolean"/...
    chip_template: str = ""
    tab_label: str = ""
    tab_order: int | None = None
    tab_layout_template: str = "settings-grid"
    tab_default_mount_points: tuple[str, ...] = ()
    tab_summary_template: str | None = None
    tab_summary_keys: tuple[str, ...] = ()
    tab_content_adapter: str = "settings"
    tab_content_options: dict[str, Any] | None = None
    adapter_managed: bool = False
    show_chip: bool = True
    execution_policy: str = "include"
    scope_policy: str = "overridable"
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    help_text: str = ""
    info_overlay: dict[str, Any] | None = None
    instance_class: type | str | None = None
    serialization: dict[str, Any] | None = None
    visible_when: dict[str, tuple[Any, ...]] | None = None
    editable_when: dict[str, tuple[Any, ...]] | None = None  # field is always
        # shown; the control is only editable when this condition holds.
        # When disabled, the control shows this field's declared default
        # (optionally selected by `default_when`), not a user override.
    default_when: dict[str, dict[Any, Any]] | None = None
    options: tuple[tuple[str, str], ...] = ()  # (value, label) pairs for select controls
    display_offset: int = 0  # presentation-only numeric offset declared by the field owner
    display_value_kind: str | None = None  # Field-value display renderer hint owned by the field definition


class ExecutableModule:
    """Base for all executable modules in the new Event/Order/Flow engine.

    A module contributes some combination of: FieldRef-typed fields (via
    `fields: ClassVar[dict[str, FieldDefinition]]`) and Flow registrations (via
    `flows: ClassVar[tuple[Flow | FlowBinding, ...]]`). It has no
    independent page/URL — see `as_module_node()` for the CLI-navigation
    adapter that wraps one of these as a `Module` node without making it a
    `Module` subclass.
    """

    key: ClassVar[str] = ""
    label: ClassVar[str] = ""
    order: ClassVar[int] = 100
    fields: ClassVar[dict[str, FieldDefinition]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        from tools.testers.backtest.engines.native.flow import Flow, FlowBinding, FlowDefinition  # local import:
            # flow.py imports FieldRef from this module; importing Flow at
            # module level here would be circular.
        for value in vars(cls).values():
            if isinstance(value, FieldRef) and not value.owner:
                object.__setattr__(value, "owner", cls.__name__)
            elif isinstance(value, Flow) and not value.owner:
                object.__setattr__(value, "owner", cls.__name__)
            elif isinstance(value, FlowDefinition) and not value.owner:
                object.__setattr__(value, "owner", cls.__name__)
            elif isinstance(value, FlowBinding) and not value.owner:
                object.__setattr__(value.definition, "owner", cls.__name__)


def as_module_node(cls: type[ExecutableModule], *, order: int = 0) -> "Module":
    """Wrap an ExecutableModule subclass as a Module node purely for
    CLI/tree navigation — has-many, not is-a. `app`/`sub_registry` are left
    unset; callers that select this node should read `cls.fields`, not try
    to access an `app`."""
    from tools.testers.registry import Module

    return Module(key=getattr(cls, "key", cls.__name__), label=getattr(cls, "label", ""), order=order)
