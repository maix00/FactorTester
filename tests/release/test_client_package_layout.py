from __future__ import annotations

from pathlib import Path

import pytest

from script.release.package_layout import validate_client_package_layout


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_current_client_package_map_is_complete() -> None:
    validate_client_package_layout(REPO_ROOT)


def test_rejects_a_declared_package_without_source(tmp_path: Path) -> None:
    client = tmp_path / "tools/cli"
    client.mkdir(parents=True)
    (client / "__init__.py").write_text("", encoding="utf-8")
    (client / "pyproject.toml").write_text(
        """
[tool.setuptools]
packages = ["tools.cli", "tools.cli.removed"]

[tool.setuptools.package-dir]
"tools.cli" = "."
"tools.cli.removed" = "removed"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="directories are missing"):
        validate_client_package_layout(tmp_path)


def test_rejects_an_undeclared_source_package(tmp_path: Path) -> None:
    client = tmp_path / "tools/cli"
    extra = client / "extra"
    extra.mkdir(parents=True)
    (client / "__init__.py").write_text("", encoding="utf-8")
    (extra / "__init__.py").write_text("", encoding="utf-8")
    (client / "pyproject.toml").write_text(
        """
[tool.setuptools]
packages = ["tools.cli"]

[tool.setuptools.package-dir]
"tools.cli" = "."
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="undeclared=.*tools.cli.extra"):
        validate_client_package_layout(tmp_path)
