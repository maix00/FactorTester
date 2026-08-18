from __future__ import annotations

import pytest

from tools.testers.backtest.engines.native.fields import FieldDefinition
from tools.testers.field_spec import (
    FieldSpec,
    RunRole,
    SettingRole,
    ValueDescriptor,
)
from tools.testers.settings.contracts import (
    RunFieldDefinition,
    ScopePolicy,
    SettingDefinition,
    SettingOption,
)


def test_scalar_setting_exposes_a_typed_descriptor() -> None:
    setting = SettingDefinition(
        "lookback",
        "窗口",
        "summary",
        "number",
        20,
        ScopePolicy.LOCAL_ONLY,
        module="summary",
        minimum=2,
        step=1,
    )

    assert setting.value_descriptor.to_dict() == {
        "value_type": "integer",
        "cardinality": "one",
        "editor": "input",
        "format": "",
        "unit": "",
        "option_source": "",
        "resolver": "",
        "item_type": "",
        "ref_kind": "",
        "schema": {},
        "options": [],
        "minimum": 2,
        "maximum": None,
        "step": 1,
    }
    assert setting.field_spec().to_dict()["roles"] == ["setting"]


def test_help_metadata_is_kept_in_canonical_field_contracts() -> None:
    setting = SettingDefinition(
        "factor",
        "因子",
        "factor",
        "select",
        "",
        ScopePolicy.LOCAL_ONLY,
        module="factor_execution",
        help_text="选择因子",
        info_overlay={"type": "factor_info"},
    )
    assert setting.field_spec().to_dict()["help_text"] == "选择因子"
    assert setting.to_dict()["info_overlay"] == {"type": "factor_info"}

    run_field = RunFieldDefinition(
        "output",
        "输出",
        "select",
        "",
        "body",
        "job.output",
        "outputs",
        help_text="选择输出",
        info_overlay={"type": "output_info"},
    )
    assert run_field.field_spec().to_dict()["info_overlay"] == {"type": "output_info"}


def test_catalog_and_grid_fields_are_not_flat_text() -> None:
    catalog = SettingDefinition(
        "product_path_selections",
        "产品路径选择",
        "products",
        "custom",
        [],
        ScopePolicy.LOCAL_ONLY,
        module="product_selection",
        serialization={"kind": "product_path_selection_list", "multi": True},
    )
    grid = SettingDefinition(
        "ic_lags",
        "延迟",
        "delay",
        "ic_delay_grid",
        [0],
        ScopePolicy.LOCAL_ONLY,
        module="ic_delay",
    )

    assert catalog.value_descriptor.value_type == "reference"
    assert catalog.value_descriptor.cardinality == "many"
    assert catalog.value_descriptor.editor == "catalog"
    assert catalog.value_descriptor.option_source == "catalog.product_path_selection_list"
    assert grid.value_descriptor.to_dict()["value_type"] == "grid"
    assert grid.value_descriptor.item_type == "integer"

    duration = SettingDefinition(
        "warmup_window",
        "前摇时长",
        "factor",
        "text",
        "30d",
        ScopePolicy.LOCAL_ONLY,
        module="factor_execution",
    )
    assert duration.value_descriptor.value_type == "duration"
    assert duration.value_descriptor.format == "duration"


def test_run_field_keeps_submission_lifecycle_separate() -> None:
    field = RunFieldDefinition(
        "task_name",
        "任务名称",
        "text",
        "",
        "body",
        "job.task_name",
        "run_identity",
    )

    spec = field.field_spec().to_dict()
    assert spec["roles"] == ["run"]
    assert spec["run"]["freeze_target"] == "job.task_name"
    assert spec["value"]["value_type"] == "string"
    assert field.to_dict()["value_descriptor"]["value_type"] == "string"


def test_native_field_descriptor_uses_registry_key_for_dynamic_catalogs() -> None:
    field = FieldDefinition(
        public=True,
        editor="select",
        default="",
        options=(("", "自动"),),
    )

    descriptor = field.descriptor_for("data_source")
    assert descriptor.value_type == "reference"
    assert descriptor.editor == "catalog"
    assert field.field_spec("data_source").to_dict()["roles"] == ["runtime"]


def test_module_settings_project_both_setting_and_runtime_roles() -> None:
    from tools.testers.settings import backtest_setting_registry

    contracts = backtest_setting_registry.get("group_test").manifest()["field_contracts"]
    margin = contracts["settings"]["margin_mode"]

    assert margin["roles"] == ["runtime", "setting"]
    assert margin["runtime"]["owner"]
    assert margin["setting"]["scope_policy"]


def test_field_spec_rejects_role_metadata_drift() -> None:
    with pytest.raises(ValueError, match="metadata does not match roles"):
        FieldSpec(
            key="task_name",
            value=ValueDescriptor("string"),
            roles=frozenset({"run"}),
            setting=SettingRole(scope_policy="local_only"),
        )

    FieldSpec(
        key="task_name",
        value=ValueDescriptor("string"),
        roles=frozenset({"run"}),
        run=RunRole(
            request_location="body",
            freeze_target="job.task_name",
            placement="run_identity",
        ),
    )


def test_collection_descriptor_requires_item_type() -> None:
    with pytest.raises(ValueError, match="multi-value fields require"):
        ValueDescriptor("reference", cardinality="many")

    ValueDescriptor("reference", cardinality="many", item_type="reference")
