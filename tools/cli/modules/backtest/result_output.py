"""Common result-output option parsing and emission helpers."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any
import contextlib
import io


Echo = Callable[[str], None]


def parse_result_output_options(args: tuple[str, ...], *, error: Callable[[str], Exception]) -> tuple[dict[str, Any], tuple[str, ...]]:
    options: dict[str, Any] = {
        "output": "",
        "terminal": True,
        "append": False,
    }
    cleaned: list[str] = []
    i = 0
    while i < len(args):
        token = args[i]
        if token in {"--output", "-o"}:
            if i + 1 >= len(args) or args[i + 1].startswith("--"):
                raise error(f"{token} 缺少文件路径")
            options["output"] = args[i + 1]
            i += 2
            continue
        if token.startswith("--output="):
            options["output"] = token.split("=", 1)[1]
            i += 1
            continue
        if token == "--no-terminal":
            options["terminal"] = False
            i += 1
            continue
        if token == "--append":
            options["append"] = True
            i += 1
            continue
        cleaned.append(token)
        i += 1
    if not options["terminal"] and not options["output"]:
        raise error("--no-terminal 必须搭配 --output PATH")
    return options, tuple(cleaned)


def emit_result_output(options: dict[str, Any], callback: Callable[[], None], *, echo: Echo) -> None:
    output_path = str(options.get("output") or "")
    terminal = bool(options.get("terminal", True))
    append = bool(options.get("append", False))
    if terminal and not output_path:
        callback()
        return
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        callback()
    text = buffer.getvalue()
    if output_path:
        path = Path(output_path).expanduser()
        if path.parent and str(path.parent) not in {"", "."}:
            path.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with path.open(mode, encoding="utf-8") as fh:
            fh.write(text)
            if text and not text.endswith("\n"):
                fh.write("\n")
    if terminal and text:
        echo(text)
