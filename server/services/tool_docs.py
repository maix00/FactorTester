"""Helpers for reading tools/ documentation source files."""

from __future__ import annotations

import os
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


def parse_tool_file(filepath: str, tools_dir: str, include_code: bool = False) -> dict[str, Any]:
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
    return item


def scan_tool_files(tools_dir: str, include_code: bool = False) -> list[dict[str, Any]]:
    files = []
    for root, dirs, filenames in os.walk(tools_dir):
        dirs[:] = [d for d in sorted(dirs) if not d.startswith('__pycache__') and not d.startswith('.')]
        for filename in sorted(filenames):
            if filename.endswith('.py') and filename != '__init__.py':
                files.append(parse_tool_file(os.path.join(root, filename), tools_dir, include_code=include_code))
    files.sort(key=lambda item: item['path'])
    return files
