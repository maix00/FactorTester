from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from tests._repo import repo_root
from tools.parameters import FactorParam, TypeParam


def _load_factor_param_utils_module():
    module_path = repo_root(Path(__file__)) / "server/modules/shared/factor_param_utils.py"
    spec = importlib.util.spec_from_file_location("_factor_param_utils_under_test", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FactorFamilyStub:
    def __init__(self, params=None):
        self.params = params or [
            TypeParam("TransportAlpha", default_value=0.2, typ=(int, float)),
            TypeParam("TransportLag", default_value=0, typ=int),
        ]
        self.params_dict = {param.alias: param for param in self.params}

    def _normalize_param_kwargs(self, **params):
        return params

    def _check_in_space(self, **params):
        for alias, value in params.items():
            if value not in self.params_dict[alias]:
                raise ValueError(f"{value} is not in the value space of {alias}")


def test_numeric_type_params_are_coerced_from_text_controls():
    param_utils = _load_factor_param_utils_module()
    family = _FactorFamilyStub()

    row = param_utils.normalize_factor_param_row(
        family,
        {"TransportAlpha": "0.2", "TransportLag": "2"},
    )

    assert row["TransportAlpha"] == pytest.approx(0.2)
    assert isinstance(row["TransportAlpha"], float)
    assert row["TransportLag"] == 2
    assert isinstance(row["TransportLag"], int)


def test_invalid_numeric_type_param_text_remains_rejected():
    param_utils = _load_factor_param_utils_module()
    family = _FactorFamilyStub()

    with pytest.raises(ValueError, match="TransportAlpha"):
        param_utils.normalize_factor_param_row(family, {"TransportAlpha": "not-a-number"})


def test_numeric_factor_param_is_coerced_and_wrapped_from_text_control():
    param_utils = _load_factor_param_utils_module()
    family = _FactorFamilyStub([
        FactorParam("TransportThreshold", default_value=0.001),
    ])

    row = param_utils.normalize_factor_param_row(
        family,
        {"TransportThreshold": "0.025"},
    )

    assert row["TransportThreshold"].value == pytest.approx(0.025)
