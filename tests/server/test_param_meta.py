import pytest

from server.modules.shared import factor_param_resolver
from server.modules.shared.factor_instance_metadata import _dependency_index
from server.modules.shared.factor_param_resolver import resolve_factor_param_value
from server.modules.shared.factor_param_utils import (
    factor_param_value_storage,
    frozen_factor_dependencies,
)
from server.modules.shared.param_meta import serialize_param_meta
from tools.factors.formula_identity import freeze_factor_identity
from tools.factors.FactorExpr import ConstExpr
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


def test_dependency_index_merges_compact_and_complete_same_frozen_identity():
    leaf = _frozen("Leaf|N:5d")
    complete = {
        **leaf,
        "source_kind": "transient",
        "source_origin": "test_inline",
        "source_code": "class Leaf: pass",
    }
    outer = {
        **_frozen("Outer|P:[Leaf|N:5d]", params={"P": leaf["ref"]}),
        "factor_dependencies": [leaf],
    }

    index = _dependency_index([complete, outer])

    assert index[leaf["ref"]]["source_code"] == "class Leaf: pass"
    nested = index[outer["ref"]]["factor_dependencies"][0]
    assert nested["ref"] == complete["ref"]
    assert nested["source_code"] == complete["source_code"].strip()


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


def test_factor_param_storage_reduces_const_expr_to_json_scalar():
    parameter = FactorParam("ScalarExpression", default_value=None)

    assert factor_param_value_storage(parameter, ConstExpr(0.9)) == 0.9
    assert frozen_factor_dependencies(
        [parameter], {"ScalarExpression": ConstExpr(0.9)},
    ) == []


def test_factor_param_dependencies_are_flattened_and_deduplicated():
    parameter = FactorParam("P", default_value=None)
    leaf = _frozen("Leaf|N:5d")
    nested = {
        **_frozen("Nested|P:leaf", params={"P": leaf["ref"]}),
        "factor_dependencies": [leaf, leaf],
    }

    assert frozen_factor_dependencies([parameter], {"P": nested}) == [
        leaf, {**nested, "factor_dependencies": [leaf]},
    ]


def test_inline_factor_dependency_keeps_only_its_frozen_source_payload():
    parameter = FactorParam("P", default_value=None)
    inline = {
        **_frozen("Inline|N:5d"),
        "temporary": True,
        "source_kind": "transient",
        "source_origin": "test_inline",
        "source_code": "class Inline: pass\n",
        "ui_only": "discard me",
    }

    dependencies = frozen_factor_dependencies([parameter], {"P": inline})

    assert dependencies == [{
        **_frozen("Inline|N:5d"),
        "temporary": True,
        "source_kind": "transient",
        "source_origin": "test_inline",
        "source_code": "class Inline: pass",
    }]


def test_inline_factor_from_library_family_keeps_provenance_without_source():
    parameter = FactorParam("P", default_value=None)
    inline = {
        **_frozen("LibraryFamily|N:5d"),
        "temporary": True,
        "source_kind": "factor_library",
        "source_origin": "test_inline",
    }

    assert frozen_factor_dependencies([parameter], {"P": inline}) == [{
        **_frozen("LibraryFamily|N:5d"),
        "temporary": True,
        "source_kind": "factor_library",
        "source_origin": "test_inline",
    }]


def test_runtime_rejects_a_nested_ref_missing_from_frozen_runspec():
    with pytest.raises(ValueError, match="未在 RunSpec 中冻结"):
        resolve_factor_param_value("factor:v2:missing", frozen_by_ref={})


def test_runtime_restores_nested_factor_from_flattened_frozen_dependencies(
    monkeypatch,
):
    leaf = {
        **freeze_factor_identity(
            owner_ref="alice", family_alias="Leaf", factor_alias="Leaf|N:5d",
            family_formula_fingerprint="1" * 64,
            self_formula_fingerprint="2" * 64, params={"N": "5d"},
        ),
        "temporary": True,
        "source_kind": "transient",
        "source_code": "inline Leaf source",
    }
    outer = {
        **freeze_factor_identity(
            owner_ref="alice", family_alias="Outer",
            factor_alias="Outer|P:[Leaf|N:5d]",
            family_formula_fingerprint="3" * 64,
            self_formula_fingerprint="4" * 64,
            params={"P": leaf["ref"]},
        ),
        "factor_dependencies": [leaf],
    }

    class Expr:
        def __init__(self, fingerprint):
            self.fingerprint = fingerprint

        def semantic_fingerprint(self):
            return self.fingerprint

    class Factor:
        def __init__(self, alias, fingerprint):
            self.alias = alias
            self.expr = Expr(fingerprint)
            self._source_expr = self.expr

    from tools.parameters import FactorParam

    class LeafFamily:
        alias = "Leaf"
        params = [FactorParam("N", default_value=None)]
        expr = Expr("1" * 64)

        def get_factor(self, **_params):
            return Factor(leaf["alias"], "2" * 64)

    class OuterFamily:
        alias = "Outer"
        params = [FactorParam("P", default_value=None)]
        expr = Expr("3" * 64)

        def get_factor(self, **params):
            from tools.factors.factor_param_resolution import (
                resolve_factor_param_value as resolve_engine_value,
            )
            nested = resolve_engine_value(params["P"])
            assert nested.alias == leaf["alias"]
            return Factor(outer["alias"], "4" * 64)

    class Catalog:
        def version(self, _principal, _kind, alias, _version, **_kwargs):
            assert alias != "Leaf", "inline dependency must not query the library"
            fingerprints = {"Leaf": "1" * 64, "Outer": "3" * 64}
            return {
                "source_code": alias,
                "family_formula_fingerprint": fingerprints[alias],
            }

    monkeypatch.setattr(factor_param_resolver, "FactorSourceCatalog", Catalog)
    monkeypatch.setattr(
        factor_param_resolver, "_load_factor_family_from_source",
        lambda source, _alias: (
            LeafFamily if source == "inline Leaf source" else OuterFamily, None,
        ),
    )
    monkeypatch.setattr(
        factor_param_resolver, "normalize_factor_param_row",
        lambda _family, params: dict(params),
    )

    restored = resolve_factor_param_value(outer, username="alice")

    assert restored.alias == outer["alias"]
