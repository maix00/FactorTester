import pytest

from server.modules.shared.factor_param_resolver import resolve_factor_param_value
from server.modules.shared.factor_param_utils import (
    factor_param_value_storage,
    frozen_factor_dependencies,
)
from server.modules.shared.param_meta import serialize_param_meta
from tools.factors.formula_identity import freeze_factor_identity
from tools.parameters import (
    DataColumnParam,
    DataTimeParam,
    FactorParam,
    FinRangeParam,
    TimeDeltaParam,
    TypeParam,
    WindowParam,
)
from tools.factors.Parameters import FactorFreqParam, ReverseParam


def _frozen(alias: str, *, params: dict | None = None) -> dict:
    return freeze_factor_identity(
        owner_ref="alice",
        family_alias=alias.split("|", 1)[0],
        factor_alias=alias,
        family_formula_fingerprint="a" * 64,
        self_formula_fingerprint="b" * 64,
        params=params or {},
    )


def test_factor_param_declares_visible_factor_reference_editor():
    value = serialize_param_meta(FactorParam("P", default_value=None))

    assert value["type"] == "FactorParam"
    assert value["input_mode"] == "factor_ref_custom"
    assert value["options"]
    assert any(option["value"] == "C" for option in value["options"])
    assert "ConstExpr" in value["input_help"]
    assert "ColumnRef" in value["input_help"]
    assert "factor:v2" in value["input_help"]


@pytest.mark.parametrize(
    "parameter",
    [
        TypeParam("TypedHelp", default_value=1),
        FinRangeParam("FiniteHelp", value_space=["a", "b"]),
        TimeDeltaParam("DeltaHelp", default_value="1d"),
        DataColumnParam("ColumnHelp", default_value="CA"),
        DataTimeParam("TimeHelp", default_value="2026-09-01"),
        WindowParam("WindowHelp", default_value="20d"),
    ],
)
def test_every_parameter_type_exports_class_owned_input_help(parameter):
    value = serialize_param_meta(parameter)

    assert value["input_help"] == parameter.input_help
    assert value["input_help"].strip()


@pytest.mark.parametrize(
    ("parameter", "expected_type", "help_fragment"),
    [
        (FactorFreqParam, "FactorFrequencyParam", "信号频率"),
        (ReverseParam, "ReverseSignalParam", "反转"),
    ],
)
def test_system_parameters_expose_semantic_types_and_help(
    parameter, expected_type, help_fragment,
):
    value = serialize_param_meta(parameter)

    assert value["type"] == expected_type
    assert help_fragment in value["input_help"]


def test_factor_param_numeric_constant_keeps_plain_default_value():
    value = serialize_param_meta(FactorParam("NumericP", default_value=0.001))

    assert value["default_value"] == "0.001"


def test_scalar_parameter_keeps_scalar_editor_contract():
    value = serialize_param_meta(WindowParam("N", default_value="20d"))

    assert value["type"] == "WindowParam"
    assert value["input_mode"] == "text"


def test_factor_param_storage_uses_only_the_nested_v2_ref():
    parameter = FactorParam("P", default_value=None)
    nested = _frozen("Nested|N:20d")

    assert factor_param_value_storage(parameter, nested) == nested["ref"]


def test_factor_param_storage_preserves_numeric_constant_type():
    parameter = FactorParam("NumericStorageP", default_value=0.001)

    assert factor_param_value_storage(parameter, parameter.default_value) == 0.001


def test_factor_param_dependencies_are_flattened_and_deduplicated():
    parameter = FactorParam("P", default_value=None)
    leaf = _frozen("Leaf|N:5d")
    nested = {
        **_frozen("Nested|P:leaf", params={"P": leaf["ref"]}),
        "factor_dependencies": [leaf, leaf],
    }

    assert frozen_factor_dependencies([parameter], {"P": nested}) == [leaf, {
        key: value for key, value in nested.items() if key != "factor_dependencies"
    }]


def test_runtime_rejects_a_nested_ref_missing_from_frozen_runspec():
    with pytest.raises(ValueError, match="未在 RunSpec 中冻结"):
        resolve_factor_param_value("factor:v2:missing", frozen_by_ref={})
