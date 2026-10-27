"""Contracts for building the pinned Nautilus extension in GTHT."""

from __future__ import annotations

from pathlib import Path

import yaml

from server.services.nautilus_bridge.version import NAUTILUS_VERSION

ROOT = Path(__file__).resolve().parents[2]


def test_environment_pins_the_vendor_maturin_build_backend():
    environment = yaml.safe_load((ROOT / "environment.yml").read_text())
    pip_packages = environment["dependencies"][-1]["pip"]
    assert "maturin==1.15.0" in pip_packages
    assert "plotly>=7.0.0,<8.0.0" in pip_packages

    vendor = (ROOT / "vendor/nautilus_trader/python/pyproject.toml").read_text()
    assert 'requires = ["maturin==1.15.0", "patchelf"]' in vendor
    assert '"plotly>=7.0.0,<8.0.0"' in vendor

    pyo3 = (ROOT / "vendor/nautilus_trader/crates/pyo3/src/lib.rs").read_text()
    assert "cfg_attr(target_vendor = \"apple\", allow(linker_messages))" in pyo3


def test_builder_uses_vendor_toolchain_and_reused_dev_target():
    builder = (ROOT / "scripts/build_nautilus_extension.sh").read_text()
    assert "rust-toolchain.toml" in builder
    assert 'CARGO_TARGET_DIR="${NAUTILUS_ROOT}/target"' in builder
    assert 'CARGO_PROFILE_DEV_OPT_LEVEL="${DEV_OPT_LEVEL}"' in builder
    assert "maturin develop --profile dev --locked" in builder
    assert 'getattr(native, "__file__", None)' in builder
    assert "_libnautilus" in builder
    assert 'getattr(BacktestEngine, "run_catalogs", None)' in builder
    assert 'path.stat().st_mtime_ns > native_mtime_ns' in builder


def test_test_entrypoint_builds_extension_for_runtime_tests():
    test_script = (ROOT / "scripts/test.sh").read_text()
    assert "scripts/build_nautilus_extension.sh" in test_script
    assert "tests|tests/" in test_script
    assert "tests/server/test_nautilus_bridge_*.py" in test_script
    assert "tests/benchmarks/bench_nautilus_*.py" in test_script
    assert '"tests/server/test_nautilus_bridge_version.py"' in test_script


def test_built_extension_is_loaded_from_the_pinned_vendor_source():
    from tests.nautilus_runtime import require_nautilus

    assert require_nautilus().__version__ == NAUTILUS_VERSION


def test_runtime_helper_rejects_a_native_module_without_a_binary_path(monkeypatch):
    import sys
    from types import ModuleType

    import pytest

    from tests.nautilus_runtime import require_nautilus

    package = ModuleType("nautilus_trader")
    package.__file__ = str(ROOT / "vendor/nautilus_trader/python/nautilus_trader/__init__.py")
    package.__version__ = NAUTILUS_VERSION
    native = ModuleType("nautilus_trader._libnautilus")
    native.__file__ = None
    monkeypatch.setitem(sys.modules, "nautilus_trader", package)
    monkeypatch.setitem(sys.modules, "nautilus_trader._libnautilus", native)

    with pytest.raises(pytest.fail.Exception, match="native extension is unavailable"):
        require_nautilus()
