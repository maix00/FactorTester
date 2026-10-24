"""Keep FactorTester pinned to the version in the Nautilus submodule."""

from __future__ import annotations

from pathlib import Path

import tomllib

from server.services.nautilus_bridge.version import NAUTILUS_VERSION

ROOT = Path(__file__).resolve().parents[2]


def test_bridge_version_matches_vendored_nautilus_source():
    project = tomllib.loads(
        (ROOT / "vendor/nautilus_trader/python/pyproject.toml").read_text()
    )
    assert NAUTILUS_VERSION == project["project"]["version"]
