"""Canonical setting schema returned to every backtest frontend."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


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
    control_template: str
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
    disabled_values_by_engine: dict[str, tuple[str, ...]] = field(default_factory=dict)
    visible_when: dict[str, tuple[Any, ...]] = field(default_factory=dict)
    editable_when: dict[str, tuple[Any, ...]] = field(default_factory=dict)
    default_when: dict[str, dict[Any, Any]] = field(default_factory=dict)
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

    def __post_init__(self) -> None:
        if not self.key or not self.label or not self.tab or not self.control_template:
            raise ValueError("setting definition requires key, label, tab, and template")
        if not self.module:
            raise ValueError("setting definition requires a backend module owner")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["scope_policy"] = self.scope_policy.value
        value["tab_default_mount_points"] = [
            mount.value for mount in self.tab_default_mount_points
        ]
        value["visible_when"] = {
            key: list(values)
            for key, values in self.visible_when.items()
        }
        value["editable_when"] = {
            key: list(values)
            for key, values in self.editable_when.items()
        }
        value["default_when"] = {
            key: dict(values)
            for key, values in self.default_when.items()
        }
        # instance_class 是 Python 类，不能进 JSON manifest；只暴露"是否有实例信息"。
        value.pop("instance_class", None)
        value["has_instance"] = self.instance_class is not None
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
    # 该 chip 是否为"批次键"——分组组合按这些字段成批；批次头展示它们，每组行不重复。
    # 后端声明，前端据此渲染（取代前端硬编码的 factor_alias/product_path_selection/split_count）。
    batch_owned: bool = False
    source_adapter: str = ""

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

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["mount_points"] = [mount.value for mount in self.mount_points]
        value["default_mount_points"] = [
            mount.value for mount in self.default_mount_points
        ]
        return value


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
class RunFieldDefinition:
    """A per-run input that is not an ordinary reusable test setting.

    The declaration tells every client where the value is supplied and where
    the accepted value becomes auditable.  ``template_policy`` is explicit so
    routing and diagnostic controls cannot silently leak into test templates.
    """

    key: str
    label: str
    control_template: str
    default: Any
    request_location: str
    freeze_target: str
    placement: str
    template_policy: str = "exclude"
    order: int = 100
    options: tuple[SettingOption, ...] = ()
    help_text: str = ""
    enabled_payload: dict[str, Any] | None = None

    _REQUEST_LOCATIONS = ("body", "query")
    _PLACEMENTS = (
        "advanced_run_options", "global_settings", "outputs", "run_options",
    )
    _TEMPLATE_POLICIES = ("exclude", "include")

    def __post_init__(self) -> None:
        if not self.key or not self.label or not self.control_template:
            raise ValueError("run field requires key, label, and template")
        if self.request_location not in self._REQUEST_LOCATIONS:
            raise ValueError(f"run field request location is invalid: {self.request_location}")
        if not self.freeze_target:
            raise ValueError("run field requires an auditable freeze target")
        if self.placement not in self._PLACEMENTS:
            raise ValueError(f"run field placement is invalid: {self.placement}")
        if self.template_policy not in self._TEMPLATE_POLICIES:
            raise ValueError(f"run field template policy is invalid: {self.template_policy}")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key in ("_REQUEST_LOCATIONS", "_PLACEMENTS", "_TEMPLATE_POLICIES"):
            value.pop(key, None)
        value["options"] = [asdict(option) for option in self.options]
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

    _KINDS = ("create", "derive", "compose", "edit", "delete", "clone")

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
