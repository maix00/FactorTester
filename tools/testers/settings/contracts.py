"""Canonical setting schema returned to every backtest frontend."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from tools.testers.field_spec import (
    FieldRules,
    FieldSpec,
    RunRole,
    RuntimeRole,
    SettingRole,
    ValueDescriptor,
    infer_value_descriptor,
)


class SettingScope(str, Enum):
    LOCAL = "local"
    GROUP = "group"


class ScopePolicy(str, Enum):
    LOCAL_ONLY = "local_only"
    GROUP_ONLY = "group_only"
    OVERRIDABLE = "overridable"


class TabMountPoint(str, Enum):
    LOCAL_SETTINGS = "local-settings"
    GROUP_SETTINGS = "group-settings"


@dataclass(frozen=True, slots=True)
class SettingModule:
    key: str
    label: str
    layer: str
    order: int = 100
    help_text: str = ""
    execution_stage: str = ""
    sharing_scope: str = ""
    trace_policy: str = ""
    capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.key or not self.label or not self.layer:
            raise ValueError("setting module requires key, label, and layer")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SettingOption:
    value: str
    label: str


@dataclass(frozen=True, slots=True)
class SettingDefinition:
    key: str
    label: str
    tab: str
    editor: str
    default: Any
    scope_policy: ScopePolicy
    module: str = ""
    options: tuple[SettingOption, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    chip_template: str | None = None
    # 点击 chip 打开的信息 overlay 配置：
    #   {'type': 'desc',   'desc': '...'}  —— 用统一的通用 overlay 解释该字段值的含义
    #   {'type': 'custom', 'overlay': '<name>', 'desc': '...'}  —— 用注册的特殊组件
    info_overlay: dict[str, Any] | None = None
    # 与 info_overlay 平行：该设置字段的值在后端对应的"页内活对象"类（如 ProductPathSelection /
    # Category）。可为类对象，或点分路径字符串（跨层时用字符串，避免 tools→server 依赖）。
    # 仅用于服务端（不进 JSON manifest）：instance-info 接口据此到统一的 page_runtime 注册表
    # 里按 (kind, id) 取已存活对象并序列化——不在前端用值重建对象。
    instance_class: type | str | None = None
    help_text: str = ""
    engine_defaults: dict[str, Any] = field(default_factory=dict)
    disabled_values: dict[str, tuple[str, ...]] = field(default_factory=dict)
    visible_if: dict[str, tuple[Any, ...]] = field(default_factory=dict)
    editable_if: dict[str, tuple[Any, ...]] = field(default_factory=dict)
    default_if: dict[str, dict[Any, Any]] = field(default_factory=dict)
    serialization: dict[str, Any] = field(default_factory=dict)
    tab_label: str = ""
    tab_order: int | None = None
    tab_layout_template: str = "settings-grid"
    tab_default_mount_points: tuple[TabMountPoint, ...] = ()
    tab_summary_template: str | None = None
    tab_summary_keys: tuple[str, ...] = ()
    tab_content_adapter: str = "settings"
    tab_content_options: dict[str, Any] = field(default_factory=dict)
    adapter_managed: bool = False
    show_chip: bool = True
    execution_policy: str = "include"
    value_descriptor: ValueDescriptor | None = None
    runtime_role: RuntimeRole | None = None

    def __post_init__(self) -> None:
        if not self.key or not self.label or not self.tab or not self.editor:
            raise ValueError("setting definition requires key, label, tab, and template")
        if not self.module:
            raise ValueError("setting definition requires a backend module owner")
        if self.execution_policy not in ("include", "authoring_only"):
            raise ValueError(
                f"setting execution policy is invalid: {self.execution_policy}"
            )
        if self.value_descriptor is None:
            object.__setattr__(
                self,
                "value_descriptor",
                infer_value_descriptor(
                    self.editor,
                    self.default,
                    field_key=self.key,
                    options=tuple((option.value, option.label) for option in self.options),
                    serialization=self.serialization,
                    minimum=self.minimum,
                    maximum=self.maximum,
                    step=self.step,
                    instance_class=self.instance_class,
                ),
            )

    def field_spec(self) -> FieldSpec:
        """Return the lifecycle-neutral contract for this reusable setting."""
        assert self.value_descriptor is not None
        roles = {"setting"}
        if self.runtime_role is not None:
            roles.add("runtime")
        return FieldSpec(
            key=self.key,
            value=self.value_descriptor,
            label=self.label,
            help_text=self.help_text,
            info_overlay=self.info_overlay,
            roles=frozenset(roles),
            setting=SettingRole(
                scope_policy=self.scope_policy.value,
                default=self.default,
                rules=FieldRules.from_registration(
                    visible_if=self.visible_if,
                    editable_if=self.editable_if,
                    default_if=self.default_if,
                    disabled_values=self.disabled_values,
                    engine_defaults=self.engine_defaults,
                ),
            ),
            runtime=(
                self.runtime_role
                if self.runtime_role is not None
                else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key in (
            "editor", "minimum", "maximum", "step",
            "engine_defaults", "disabled_values",
            "visible_if", "editable_if", "default_if", "options",
        ):
            value.pop(key, None)
        value["scope_policy"] = self.scope_policy.value
        value["tab_default_mount_points"] = [
            mount.value for mount in self.tab_default_mount_points
        ]
        # instance_class 是 Python 类，不能进 JSON manifest；只暴露"是否有实例信息"。
        value.pop("instance_class", None)
        value["has_instance"] = self.instance_class is not None
        value["value_descriptor"] = self.value_descriptor.to_dict()
        value["rules"] = self.field_spec().setting.rules.to_dict()  # type: ignore[union-attr]
        return value


@dataclass(frozen=True, slots=True)
class ChipDefinition:
    key: str
    label: str
    category: str
    chip_template: str
    source_keys: tuple[str, ...]
    module: str = ""
    target_tab: str = ""
    order: int = 100
    inherit_from_root: bool = False
    value_resolvers: dict[str, str] = field(default_factory=dict)
    clickable: bool = False
    # 该 chip 是否显示在策略批次头部；批次边界由每次添加操作产生的
    # batch_id 冻结，不再由字段值或配置三元组推导。
    batch_owned: bool = False
    source_adapter: str = ""
    # global chips belong to the shared settings summary.  Strategy-scoped
    # chips depend on one concrete strategy row and must be rendered there.
    display_scope: str = "global"
    # Optional backend-owned action for opening the existing catalog detail
    # surface in a view-only overlay. The client resolves the target from the
    # declared source key rather than maintaining a second action map.
    detail_overlay: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.key or not self.label or not self.category or not self.chip_template:
            raise ValueError("chip definition requires key, label, category, and template")
        if not self.module:
            raise ValueError("chip definition requires a backend module owner")
        if not self.target_tab:
            raise ValueError("chip definition requires a target settings tab")
        if not self.source_keys:
            raise ValueError("chip definition requires at least one source key")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SettingTab:
    key: str
    label: str
    mount_points: tuple[TabMountPoint, ...]
    layout_template: str
    order: int
    default_mount_points: tuple[TabMountPoint, ...] = ()
    summary_template: str | None = None
    summary_keys: tuple[str, ...] = ()
    content_adapter: str = "settings"
    content_options: dict[str, Any] = field(default_factory=dict)
    # UI grouping is declared by the application registry, not inferred by a
    # client from setting names.  Keeping these optional preserves the
    # positional constructor contract used by shared setting modules.
    section_key: str = ""
    help_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["mount_points"] = [mount.value for mount in self.mount_points]
        value["default_mount_points"] = [
            mount.value for mount in self.default_mount_points
        ]
        return value


@dataclass(frozen=True, slots=True)
class SettingsSection:
    """A readable, backend-owned group of local setting tabs."""

    key: str
    label: str
    description: str = ""
    order: int = 100

    def __post_init__(self) -> None:
        if not self.key or not self.label:
            raise ValueError("settings section requires key and label")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ResultTabDefinition:
    key: str
    label: str
    module: str
    order: int
    default: bool = False
    requires: dict[str, tuple[Any, ...]] = field(default_factory=dict)
    help_text: str = ""

    def __post_init__(self) -> None:
        if not self.key or not self.label or not self.module:
            raise ValueError("result tab requires key, label, and module")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["requires"] = {
            key: list(values)
            for key, values in self.requires.items()
        }
        return value


@dataclass(frozen=True, slots=True)
class ResultProjectionDefinition:
    """Backend-owned projection of one persisted result into a result Tab.

    ``ResultTabDefinition`` describes an authoring capability.  A projection
    is deliberately separate: it describes what a completed Job can show,
    which persisted data it needs, and which domain viewer owns its content.
    Keeping the two contracts separate prevents an enabled analysis option
    from becoming an empty result tab by accident.
    """

    key: str
    label: str
    module: str
    order: int
    group: str
    viewer: str
    source_artifacts: tuple[str, ...]
    output_requests: tuple[str, ...]
    presentation: str = "table"
    default: bool = False
    content_key: str = ""
    empty_state: str = "暂无可展示结果"
    source_policy: str = "any"

    def __post_init__(self) -> None:
        if not self.key or not self.label or not self.module:
            raise ValueError(
                "result projection requires key, label, and module"
            )
        if not self.group or not self.viewer:
            raise ValueError("result projection requires group and viewer")
        if not self.source_artifacts:
            raise ValueError("result projection requires source artifacts")
        if not self.output_requests:
            raise ValueError("result projection requires output requests")
        if self.presentation not in {"chart", "table", "detail"}:
            raise ValueError(
                f"result projection presentation is invalid: {self.presentation}"
            )
        if self.source_policy not in {"any", "all"}:
            raise ValueError(
                f"result projection source policy is invalid: {self.source_policy}"
            )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["source_artifacts"] = list(self.source_artifacts)
        value["output_requests"] = list(self.output_requests)
        return value


@dataclass(frozen=True, slots=True)
class RunFieldDefinition:
    """A per-run input that is not an ordinary reusable test setting.

    The declaration tells every client where the value is supplied and where
    the accepted value becomes auditable.  ``template_policy`` is explicit so
    routing and diagnostic controls cannot silently leak into test templates.
    """

    key: str
    label: str
    editor: str
    default: Any
    request_location: str
    freeze_target: str
    placement: str
    template_policy: str = "exclude"
    order: int = 100
    options: tuple[SettingOption, ...] = ()
    help_text: str = ""
    info_overlay: dict[str, Any] | None = None
    enabled_payload: dict[str, Any] | None = None
    _REQUEST_LOCATIONS = ("body", "query")
    _PLACEMENTS = (
        "advanced_run_options", "global_settings", "outputs", "run_identity",
        "run_options",
    )
    _TEMPLATE_POLICIES = ("exclude", "include")
    _CLIENTS = ("web", "swift", "cli")
    value_descriptor: ValueDescriptor | None = None
    # Some run controls are meaningful only on a specific client surface
    # (for example local Swift execution).  Keep this routing metadata in the
    # canonical run-field declaration; it is not a second value protocol.
    client_targets: tuple[str, ...] = ("web", "swift", "cli")
    # Conditional visibility is declared with the same ``*_if`` rules
    # vocabulary used by reusable settings and engine fields.  The manifest
    # exposes this unchanged as ``rules.visible_if``.
    visible_if: dict[str, tuple[Any, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.key or not self.label or not self.editor:
            raise ValueError("run field requires key, label, and template")
        if self.request_location not in self._REQUEST_LOCATIONS:
            raise ValueError(f"run field request location is invalid: {self.request_location}")
        if not self.freeze_target:
            raise ValueError("run field requires an auditable freeze target")
        if self.placement not in self._PLACEMENTS:
            raise ValueError(f"run field placement is invalid: {self.placement}")
        if self.template_policy not in self._TEMPLATE_POLICIES:
            raise ValueError(f"run field template policy is invalid: {self.template_policy}")
        if not self.client_targets or any(
            client not in self._CLIENTS for client in self.client_targets
        ):
            raise ValueError(
                "run field client_targets must contain only web, swift, or cli"
            )
        if self.value_descriptor is None:
            object.__setattr__(
                self,
                "value_descriptor",
                infer_value_descriptor(
                    self.editor,
                    self.default,
                    field_key=self.key,
                    options=tuple((option.value, option.label) for option in self.options),
                ),
            )

    def field_spec(self) -> FieldSpec:
        """Return the lifecycle-neutral contract for this per-run field."""
        assert self.value_descriptor is not None
        return FieldSpec(
            key=self.key,
            value=self.value_descriptor,
            label=self.label,
            help_text=self.help_text,
            info_overlay=self.info_overlay,
            roles=frozenset({"run"}),
            run=RunRole(
                request_location=self.request_location,
                freeze_target=self.freeze_target,
                placement=self.placement,
                template_policy=self.template_policy,
                default=self.default,
                rules=FieldRules.from_registration(visible_if=self.visible_if),
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key in ("_REQUEST_LOCATIONS", "_PLACEMENTS", "_TEMPLATE_POLICIES"):
            value.pop(key, None)
        value.pop("editor", None)
        value.pop("options", None)
        value["value_descriptor"] = self.value_descriptor.to_dict()
        value["rules"] = self.field_spec().run.rules.to_dict()  # type: ignore[union-attr]
        if self.info_overlay is None:
            value.pop("info_overlay", None)
        value.pop("client_targets", None)
        value.pop("visible_if", None)
        if self.client_targets != self._CLIENTS:
            value["client_targets"] = list(self.client_targets)
        return value


@dataclass(frozen=True, slots=True)
class SettingsSurface:
    """A settings "surface" the frontend common component renders.

    Two forms, distinguished by ``kind``:
      - kind="panel": a flat settings panel (the module-level local-settings).
      - kind="list":  a row-list of item-configs (each row = the GROUP_SETTINGS
        scope), with select/expand/chips and a click-to-edit modal.

    A surface binds to an existing ``mount`` point, so it reuses the existing
    ``tab_lists[mount]`` / field-scope machinery — it only adds the panel-level
    declaration (label + list behavior) that was previously implicit/frontend-only.
    """
    key: str
    label: str
    mount: TabMountPoint
    kind: str = "panel"            # "panel" | "list"
    order: int = 0
    # list-only behavior (ignored for kind="panel")
    selection: str = "single"     # "single" | "multi"
    run_mode: str = "run_all"     # "select_then_run" | "run_all" | "per_item_run"
    editable: bool = False        # click a row to open the edit modal
    item_label: str = ""          # display name of one item, e.g. "分组" / "IC 配置"
    chip_keys: tuple[str, ...] = ()  # setting keys shown as chips per row (empty = all item settings)
    content_adapter: str = "settings"  # frontend domain adapter selected by the backend
    content_options: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.key or not self.label:
            raise ValueError("settings surface requires key and label")
        if self.kind not in ("panel", "list"):
            raise ValueError(f"settings surface kind 非法: {self.kind}")
        if not self.content_adapter:
            raise ValueError("settings surface requires content_adapter")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["mount"] = self.mount.value
        value["chip_keys"] = list(self.chip_keys)
        value["content_options"] = dict(self.content_options)
        return value


@dataclass(frozen=True, slots=True)
class SurfaceFlow:
    """A declarative action ("flow") a list surface supports.

    Declares the *metadata* a client needs to render the affordance uniformly —
    label, kind, which form tab it opens, and when it is available (selection
    count + structural predicates). The flow's *behavior* (how a draft is built,
    what a submit does) stays in the per-client module; this makes the flow set
    and its UI portable across clients while keeping logic where it belongs.

    kinds:
      - "create":  add a brand-new item (e.g. 新增分组)
      - "derive":  create a child item from the selected one(s) (派生)
      - "compose": combine selected items into a new derived one (Long-Short)
      - "edit":    modify the selected item
      - "rename":  change only the display name of the selected item
      - "swap":    exchange the two legs of a pair strategy
      - "delete":  remove the selected item(s)
      - "clone":   copy the selected item(s)
    """
    surface: str                    # owning list surface key, e.g. "groups" / "ic_configs"
    key: str                        # flow key, e.g. "add_group" / "create_derived" / "delete"
    label: str
    kind: str
    order: int = 0
    form_tab: str = ""              # add/edit form tab to open (frontend defaultTab), if any
    min_selected: int | None = None  # availability: required selection count (inclusive)
    max_selected: int | None = None
    requires: dict[str, Any] = field(default_factory=dict)  # structural predicates, e.g. {"has_derived_groups": True}
    button_class: str = ""          # optional presentation hint

    _KINDS = ("create", "derive", "compose", "edit", "rename", "swap", "delete", "clone")

    def __post_init__(self) -> None:
        if not self.surface or not self.key or not self.label:
            raise ValueError("surface flow requires surface, key and label")
        if self.kind not in self._KINDS:
            raise ValueError(f"surface flow kind 非法: {self.kind}")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("_KINDS", None)
        value["requires"] = dict(self.requires)
        return value
