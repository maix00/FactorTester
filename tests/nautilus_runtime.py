"""Strict access to the repository's locally built NautilusTrader runtime."""

from importlib import import_module
from pathlib import Path

import pytest

from server.services.nautilus_bridge.version import NAUTILUS_VERSION


def require_nautilus():
    try:
        import nautilus_trader
    except (ImportError, OSError) as exc:
        pytest.fail(
            "NautilusTrader's local Python extension is unavailable. Run "
            "scripts/build_nautilus_extension.sh before these integration tests. "
            f"Import error: {exc}",
            pytrace=False,
        )

    source = Path(__file__).resolve().parents[1] / "vendor/nautilus_trader/python"
    package = Path(nautilus_trader.__file__).resolve()
    if not package.is_relative_to(source.resolve()):
        pytest.fail(
            "Integration tests must load the vendored NautilusTrader source, "
            "not a separate wheel. Run scripts/build_nautilus_extension.sh.",
            pytrace=False,
        )
    try:
        native = import_module("nautilus_trader._libnautilus")
    except (ImportError, OSError) as exc:
        pytest.fail(
            "The vendored NautilusTrader Python package is present, but its native "
            "extension is not loaded. Run scripts/build_nautilus_extension.sh. "
            f"Import error: {exc}",
            pytrace=False,
        )
    native_file = getattr(native, "__file__", None)
    if not native_file:
        pytest.fail(
            "The vendored NautilusTrader native extension is unavailable. Run "
            "scripts/build_nautilus_extension.sh.",
            pytrace=False,
        )
    if not Path(native_file).resolve().is_relative_to(source.resolve()):
        pytest.fail(
            "Integration tests must load the native extension built from the "
            "vendored NautilusTrader source. Run scripts/build_nautilus_extension.sh.",
            pytrace=False,
        )
    if nautilus_trader.__version__ != NAUTILUS_VERSION:
        pytest.fail(
            f"NautilusTrader version mismatch: expected {NAUTILUS_VERSION}, "
            f"found {nautilus_trader.__version__}. Rebuild the vendored extension.",
            pytrace=False,
        )
    from nautilus_trader.backtest import BacktestEngine
    if not callable(getattr(BacktestEngine, "run_catalogs", None)):
        pytest.fail("The native extension lacks configured-engine Catalog replay; rebuild the vendored extension.",
                    pytrace=False)
    if not callable(getattr(native, "attach_factor_family", None)):
        pytest.fail("The extension lacks the shared Rust FactorActor runtime; rebuild the composed runtime.", pytrace=False)
    return nautilus_trader
