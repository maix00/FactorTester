"""Tools source scanner for docs and CLI output."""

from __future__ import annotations

import os
import ast
from typing import Any


def extract_header_description(source: str) -> str:
    lines = source.split('\n')
    desc_lines = []
    in_header = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('# ====') and not in_header:
            in_header = True
            continue
        if stripped.startswith('# ====') and in_header:
            break
        if in_header:
            if stripped.startswith('# '):
                desc_lines.append(stripped[2:])
            elif stripped == '#':
                desc_lines.append('')
            else:
                break
    return '\n'.join(desc_lines).strip()


def extract_tool_symbols(source: str) -> list[dict[str, str]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    symbols: list[dict[str, str]] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            symbols.append({'kind': 'class', 'name': node.name})
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and not child.name.startswith('_'):
                    symbols.append({'kind': 'method', 'name': f'{node.name}.{child.name}'})
        elif isinstance(node, ast.FunctionDef) and not node.name.startswith('_'):
            symbols.append({'kind': 'function', 'name': node.name})
    return symbols


def parse_tool_file(
    filepath: str,
    tools_dir: str,
    include_code: bool = False,
    include_symbols: bool = False,
) -> dict[str, Any]:
    with open(filepath, 'r', encoding='utf-8') as file:
        source = file.read()
    rel_path = os.path.relpath(filepath, tools_dir)
    item: dict[str, Any] = {
        'path': rel_path,
        'name': rel_path.replace('/', ' / ').replace('\\', ' / '),
        'desc': extract_header_description(source),
    }
    if include_code:
        item['code'] = source
    if include_symbols:
        item['symbols'] = extract_tool_symbols(source)
    return item


def scan_tool_files(
    tools_dir: str,
    include_code: bool = False,
    include_symbols: bool = False,
) -> list[dict[str, Any]]:
    files = []
    for root, dirs, filenames in os.walk(tools_dir):
        dirs[:] = [d for d in sorted(dirs) if not d.startswith('__pycache__') and not d.startswith('.')]
        for filename in sorted(filenames):
            if filename.endswith('.py') and filename != '__init__.py':
                files.append(
                    parse_tool_file(
                        os.path.join(root, filename),
                        tools_dir,
                        include_code=include_code,
                        include_symbols=include_symbols,
                    )
                )
    files.sort(key=lambda item: item['path'])
    return files
