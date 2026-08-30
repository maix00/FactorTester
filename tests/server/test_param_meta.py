from server.modules.shared.param_meta import serialize_param_meta
from tools.parameters import FactorParam, WindowParam


def test_factor_param_declares_visible_factor_reference_editor():
    value = serialize_param_meta(FactorParam("P", default_value=None))

    assert value["type"] == "FactorParam"
    assert value["input_mode"] == "factor_ref_custom"
    assert value["options"]
    assert any(option["value"] == "C" for option in value["options"])


def test_scalar_parameter_keeps_scalar_editor_contract():
    value = serialize_param_meta(WindowParam("N", default_value="20d"))

    assert value["type"] == "WindowParam"
    assert value["input_mode"] == "text"
