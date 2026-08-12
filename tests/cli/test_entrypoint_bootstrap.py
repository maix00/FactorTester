from __future__ import annotations

import importlib.util
from pathlib import Path


def _bootstrap_module():
    source = (
        Path(__file__).resolve().parents[2]
        / "tools" / "cli" / "bootstrap" / "__init__.py"
    )
    spec = importlib.util.spec_from_file_location("tested_cli_bootstrap", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bootstrap_removes_cwd_and_stale_source_checkout(tmp_path: Path) -> None:
    module = _bootstrap_module()
    stale = tmp_path / "stale"
    trusted = tmp_path / "installed"
    unrelated = tmp_path / "dependency"
    for root in (stale, trusted):
        app = root / "tools" / "cli" / "app.py"
        app.parent.mkdir(parents=True)
        app.write_text("", encoding="utf-8")

    result = module.sanitized_import_path(
        ["", str(stale), str(trusted), str(unrelated)],
        cwd=stale,
        trusted_root=trusted,
    )

    assert result == [str(trusted), str(unrelated)]


def test_cli_entrypoint_uses_safe_bootstrap() -> None:
    pyproject = (
        Path(__file__).resolve().parents[2] / "tools" / "cli" / "pyproject.toml"
    ).read_text(encoding="utf-8")

    assert 'factortester = "factortester_cli_bootstrap:main"' in pyproject
    assert 'factortester = "tools.cli.app:cli"' not in pyproject
