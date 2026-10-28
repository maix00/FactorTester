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
    assert "celery==5.6.3" in pip_packages
    import celery
    assert celery.__version__ == "5.6.3"
    assert "plotly>=7.0.0,<8.0.0" in pip_packages

    vendor = (ROOT / "vendor/nautilus_trader/python/pyproject.toml").read_text()
    assert 'requires = ["maturin==1.15.0", "patchelf"]' in vendor
    assert '"plotly>=7.0.0,<8.0.0"' in vendor

    pyo3 = (ROOT / "vendor/nautilus_trader/crates/pyo3/src/lib.rs").read_text()
    assert "cfg_attr(target_vendor = \"apple\", allow(linker_messages))" in pyo3


def test_builder_uses_vendor_toolchain_and_reused_dev_target():
    builder = (ROOT / "scripts/build_nautilus_extension.sh").read_text()
    assert "rust-toolchain.toml" in builder
    assert 'CARGO_TARGET_DIR="${HOST_TARGET}"' in builder
    assert ".artifacts/runtime-receipts/" in builder
    assert 'CARGO_PROFILE_DEV_OPT_LEVEL="${DEV_OPT_LEVEL}"' in builder
    assert "maturin develop --profile dev --locked" in builder
    assert 'getattr(native, "__file__", None)' in builder
    assert "_libnautilus" in builder
    assert "traderesearch_nautilus_runtime" in builder
    assert "attach_factor_family" in builder
    assert 'getattr(BacktestEngine, "run_catalogs", None)' in builder
    assert "source_signature" in builder
    assert "traderesearch-runtime-receipt.json" in builder


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


def test_composition_preserves_upstream_features_version_and_dev_profile():
    import tomllib
    native=tomllib.loads((ROOT/"vendor/nautilus_trader/python/pyproject.toml").read_text())
    composition=tomllib.loads((ROOT/"native/traderesearch_nautilus_runtime/pyproject.toml").read_text())
    assert composition["project"]["version"]==native["project"]["version"]
    assert composition["tool"]["maturin"]["features"]==native["tool"]["maturin"]["features"]
    upstream=tomllib.loads((ROOT/"vendor/nautilus_trader/Cargo.toml").read_text())
    wrapper=tomllib.loads((ROOT/"native/traderesearch_nautilus_runtime/Cargo.toml").read_text())
    assert wrapper["profile"]["dev"]==upstream["profile"]["dev"]
    assert "nautilus-factor-bridge" not in upstream.get("workspace",{}).get("dependencies",{})


def test_alpha_owns_adapter_and_public_strategies_without_a_second_copy():
    import tomllib
    adapter = ROOT / "vendor/py-alpha-lib/adapters/nautilus"
    assert not (ROOT / "native/nautilus_factor_bridge").exists()
    assert not (ROOT / "native/factortester_nautilus_runtime").exists()
    assert (adapter / "src/family.rs").is_file()
    assert (adapter / "src/runtime.rs").is_file()
    core = tomllib.loads((ROOT / "vendor/py-alpha-lib/alpha-algo/Cargo.toml").read_text())
    assert not any(key.startswith("nautilus") for key in core["dependencies"])
    bridge = tomllib.loads((adapter / "Cargo.toml").read_text())
    assert bridge["dependencies"]["alpha-algo"]["path"] == "../../alpha-algo"
    assert not any("path" in value for key, value in bridge["dependencies"].items()
                   if key.startswith("nautilus"))
    composition = ROOT / "native/traderesearch_nautilus_runtime/Cargo.toml"
    wrapper = tomllib.loads(composition.read_text())
    dependency = wrapper["dependencies"]["nautilus-factor-bridge"]
    assert (composition.parent / dependency["path"]).resolve() == adapter.resolve()
    assert wrapper["package"]["name"] == "traderesearch-nautilus-runtime"
    assert 'url = https://github.com/maix00/py-alpha-lib.git' in (ROOT / '.gitmodules').read_text()


def test_adapter_test_build_uses_composition_source_patches():
    from scripts.test_alpha_nautilus_adapter import source_patch_args
    import tomllib
    composition = ROOT / "native/traderesearch_nautilus_runtime/Cargo.toml"
    patches = tomllib.loads(composition.read_text())["patch"]["crates-io"]
    args = source_patch_args()
    assert len(args) == 2 * len(patches)
    for name, patch in patches.items():
        assert any(f'patch.crates-io.{name}.path=' in argument
                   and str((composition.parent / patch['path']).resolve()) in argument
                   for argument in args)
