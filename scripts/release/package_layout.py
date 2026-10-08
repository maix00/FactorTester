"""Validate the explicit package map used by the frozen client runtime."""

from __future__ import annotations

from pathlib import Path
import tomllib


_IGNORED_PARTS = {
    "__pycache__",
    "build",
    "dist",
    "tests",
}


def validate_client_package_layout(repo: Path) -> None:
    """Reject stale or incomplete setuptools declarations before building."""
    root = repo / "tools" / "cli"
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        raise ValueError(f"client pyproject is missing: {pyproject}")
    configuration = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    setuptools = configuration.get("tool", {}).get("setuptools", {})
    packages = set(setuptools.get("packages") or [])
    package_dirs = setuptools.get("package-dir") or {}
    if packages != set(package_dirs):
        missing_paths = sorted(packages - set(package_dirs))
        extra_paths = sorted(set(package_dirs) - packages)
        raise ValueError(
            "client package declarations disagree with package-dir: "
            f"missing_paths={missing_paths}, extra_paths={extra_paths}"
        )

    invalid = sorted(
        name
        for name, relative in package_dirs.items()
        if not (root / relative / "__init__.py").is_file()
    )
    if invalid:
        raise ValueError(
            "client package directories are missing: " + ", ".join(invalid)
        )

    names_by_directory = {
        Path(relative): name for name, relative in package_dirs.items()
    }
    discovered = {
        _package_name(root, path.parent, names_by_directory)
        for path in root.rglob("__init__.py")
        if not _ignored(path.relative_to(root))
    }
    undeclared = sorted(discovered - packages)
    stale = sorted(packages - discovered)
    if undeclared or stale:
        raise ValueError(
            "client package map is incomplete: "
            f"undeclared={undeclared}, stale={stale}"
        )


def _package_name(
    root: Path, directory: Path, names_by_directory: dict[Path, str],
) -> str:
    relative = directory.relative_to(root)
    explicit = names_by_directory.get(relative)
    if explicit is not None:
        return explicit
    suffix = ".".join(relative.parts)
    return "tools.cli" + (f".{suffix}" if suffix else "")


def _ignored(path: Path) -> bool:
    return any(
        part in _IGNORED_PARTS
        or part.endswith(".egg-info")
        or part.startswith(".")
        for part in path.parts
    )
