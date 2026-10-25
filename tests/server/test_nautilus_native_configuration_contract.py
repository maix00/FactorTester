"""Keep the FactorTester projection aligned with the pinned Nautilus API."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from server.services.nautilus_bridge.config import UnsupportedExecutionConfig
from server.services.nautilus_bridge.native_configuration import (
    freeze_native_venue_config,
    native_configuration_schema,
)


ROOT = Path(__file__).resolve().parents[2]
NAUTILUS = ROOT / "vendor" / "nautilus_trader"


def _method_parameters(path: Path, class_name: str, method_name: str) -> list[str]:
    tree = ast.parse(path.read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    method = next(
        node for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == method_name
    )
    return [argument.arg for argument in method.args.args if argument.arg not in {"self", "cls"}]


def test_venue_capability_catalog_matches_pinned_add_venue_signature() -> None:
    parameters = _method_parameters(
        NAUTILUS / "python" / "nautilus_trader" / "backtest" / "__init__.pyi",
        "BacktestEngine", "add_venue",
    )
    schema = native_configuration_schema()
    assert schema["native_parameters"] == parameters
    coverage = schema["parameter_coverage"]
    assert [item["parameter"] for item in coverage] == parameters
    assert all(
        item["runspec_path"] != "—" or item["status"] == "unsupported"
        for item in coverage
    )
    assert all(item.get("note") for item in coverage if item["status"] == "unsupported")


def test_engine_factory_passes_every_supported_add_venue_argument() -> None:
    parameters = set(_method_parameters(
        NAUTILUS / "python" / "nautilus_trader" / "backtest" / "__init__.pyi",
        "BacktestEngine", "add_venue",
    ))
    tree = ast.parse((ROOT / "server" / "services" / "nautilus_bridge" / "engine_factory.py").read_text())
    call = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_venue"
    )
    passed = {keyword.arg for keyword in call.keywords if keyword.arg}
    assert parameters - {"modules"} == passed
    assert "modules" not in passed


def test_model_handles_are_marked_as_serialization_adapters() -> None:
    schema = native_configuration_schema()
    coverage = {item["parameter"]: item for item in schema["parameter_coverage"]}
    for parameter in ("margin_model", "fill_model", "fee_model", "latency_model"):
        assert coverage[parameter]["status"] == "ft_adapter"
        assert coverage[parameter]["runspec_path"].startswith("venues[].native_config.")


def test_volume_sensitive_fill_model_is_not_exposed_without_market_volume_updates() -> None:
    schema = native_configuration_schema()
    fill_type = next(item for item in schema["fields"] if item["path"] == "fill_model.type")
    assert "volume_sensitive" not in fill_type["options"]
    assert "近期成交量更新入口" in schema["excluded"]["VolumeSensitiveFillModel"]
    with pytest.raises(UnsupportedExecutionConfig, match="fill_model.type"):
        freeze_native_venue_config({"fill_model": {"type": "volume_sensitive"}})


def test_execution_policy_capabilities_match_native_engine_configuration() -> None:
    parameters = set(_method_parameters(
        NAUTILUS / "python" / "nautilus_trader" / "execution" / "__init__.pyi",
        "ExecutionEngineConfig", "__new__",
    ))
    schema = native_configuration_schema()
    coverage = {
        item["parameter"]: item
        for item in schema["execution_policy_coverage"]
    }
    assert coverage["position_cost_basis"]["status"] == "nt_native"
    assert coverage["position_cost_basis"]["native_parameters"] in parameters
    assert coverage["position_cost_basis_by_instrument"]["status"] == "nt_native"
    assert coverage["position_cost_basis_by_instrument"]["native_parameters"] in parameters
    assert coverage["execution_timing"]["status"] == "ft_adapter"
    assert coverage["daily_settlement"]["status"] == "unsupported"

    tree = ast.parse((ROOT / "server" / "services" / "nautilus_bridge" / "engine_factory.py").read_text())
    call = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "ExecutionEngineConfig"
    )
    passed = {keyword.arg for keyword in call.keywords if keyword.arg}
    assert {
        coverage["position_cost_basis"]["native_parameters"],
        coverage["position_cost_basis_by_instrument"]["native_parameters"],
    } <= passed
