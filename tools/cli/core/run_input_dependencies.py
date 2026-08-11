"""Load bounded, retained Job input files for ``run preview/submit``."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any, Callable, Iterable, TypeVar

import click


SUPPORTED_SUFFIXES = {
    ".cfg", ".csv", ".ini", ".json", ".md", ".py", ".toml",
    ".txt", ".yaml", ".yml",
}
SUPPORTED_PURPOSES = {
    "strategy_dependency", "strategy_configuration", "run_configuration",
    "data_mapping", "documentation", "other",
}
MAX_FILES = 200
MAX_INPUT_BYTES = 20 * 1024 * 1024

_PURPOSE_DIRECTORIES = {
    "strategy_dependency": "strategy-configs",
    "strategy_configuration": "strategy-configs",
    "run_configuration": "run-configs",
    "data_mapping": "data-mappings",
    "documentation": "documentation",
    "other": "run-inputs",
}
_PURPOSE_TITLES = {
    "strategy_dependency": "策略依赖",
    "strategy_configuration": "策略配置",
    "run_configuration": "运行配置",
    "data_mapping": "数据映射",
    "documentation": "说明文档",
    "other": "运行输入",
}
_CONTENT_TYPES = {
    ".cfg": "text/plain",
    ".csv": "text/csv",
    ".ini": "text/plain",
    ".json": "application/json",
    ".md": "text/markdown",
    ".py": "text/x-python",
    ".toml": "application/toml",
    ".txt": "text/plain",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
}

_F = TypeVar("_F", bound=Callable[..., Any])


def option(function: _F) -> _F:
    """Add the repeatable native CLI option without duplicating help text."""
    return click.option(
        "--run-input",
        "run_input_specs",
        multiple=True,
        metavar="[PURPOSE=]FILE",
        help=(
            "随 Job 保留的文本输入，可重复。PURPOSE 可为 strategy_dependency、"
            "strategy_configuration、run_configuration、data_mapping、"
            "documentation 或 other；省略时为 other。"
        ),
    )(function)


def load(
    specifications: Iterable[str],
    *,
    analyses: Iterable[str],
) -> list[dict[str, Any]]:
    """Read local text files into the server's non-executable input contract."""
    values = tuple(
        str(value).strip()
        for value in specifications
        if str(value).strip()
    )
    if len(values) > MAX_FILES:
        raise click.ClickException(f"--run-input 最多允许 {MAX_FILES} 个文件")
    selected_analyses = list(dict.fromkeys(str(value) for value in analyses))
    result: list[dict[str, Any]] = []
    logical_paths: set[str] = set()
    total_bytes = 0
    for specification in values:
        purpose, source = _split_specification(specification)
        path = Path(source).expanduser().resolve()
        if not path.is_file():
            raise click.ClickException(f"运行输入文件不存在: {source}")
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise click.ClickException(
                f"运行输入必须是受支持的文本文件: {path.name}"
            )
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise click.ClickException(
                f"运行输入不是 UTF-8 文本: {path.name}"
            ) from exc
        encoded = content.encode("utf-8")
        total_bytes += len(encoded)
        if total_bytes > MAX_INPUT_BYTES:
            raise click.ClickException("--run-input 文件合计不能超过 20 MiB")
        logical_path = f"{_PURPOSE_DIRECTORIES[purpose]}/{path.name}"
        if logical_path in logical_paths:
            raise click.ClickException(
                f"运行输入文件名冲突，请只保留一个 {logical_path}"
            )
        logical_paths.add(logical_path)
        result.append({
            "path": logical_path,
            "content": content,
            "content_type": _CONTENT_TYPES.get(
                suffix,
                mimetypes.guess_type(path.name)[0] or "text/plain",
            ),
            "title_zh": f"{_PURPOSE_TITLES[purpose]}：{path.name}",
            "purpose": purpose,
            "analyses": list(selected_analyses),
        })
    return result


def _split_specification(value: str) -> tuple[str, str]:
    if "=" not in value:
        return "other", value
    purpose, source = value.split("=", 1)
    if purpose not in SUPPORTED_PURPOSES:
        raise click.ClickException(f"未知的 --run-input PURPOSE: {purpose}")
    if not source.strip():
        raise click.ClickException("--run-input 缺少文件路径")
    return purpose, source.strip()
