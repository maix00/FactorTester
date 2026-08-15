"""Launch the installed CLI without importing a stale checkout from cwd."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Iterable


def sanitized_import_path(
    entries: Iterable[str], *, cwd: Path, trusted_root: Path | None,
) -> list[str]:
    """Remove checkout paths that could shadow the installed ``tools.cli``."""
    current = cwd.resolve()
    trusted = trusted_root.resolve() if trusted_root is not None else None
    result: list[str] = []
    if trusted is not None:
        result.append(str(trusted))
    for entry in entries:
        if not entry:
            continue
        try:
            resolved = Path(entry).resolve()
        except OSError:
            result.append(entry)
            continue
        if resolved == current or resolved == trusted:
            continue
        if (resolved / "tools" / "cli" / "app.py").is_file():
            continue
        result.append(entry)
    return result


def main() -> object:
    """Load the CLI from its installed distribution, independent of cwd."""
    trusted = _trusted_import_root()
    sys.path[:] = sanitized_import_path(
        sys.path, cwd=Path.cwd(), trusted_root=trusted,
    )
    from tools.cli.app import cli

    return cli()


def manager_main() -> object:
    """Load the installed Manager/operator CLI from its safe bootstrap."""
    trusted = _trusted_import_root()
    sys.path[:] = sanitized_import_path(
        sys.path, cwd=Path.cwd(), trusted_root=trusted,
    )
    from tools.cli.manager_app import manager_cli

    return manager_cli()


def _trusted_import_root() -> Path | None:
    source = Path(__file__).resolve()
    for parent in source.parents:
        if (parent / "tools" / "cli" / "app.py").is_file():
            return parent
    return None
