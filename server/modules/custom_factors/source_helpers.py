"""Source-code helpers for custom factor families.

Keep route handlers focused on HTTP/business flow; this module owns the
small amount of source rewriting needed to persist editable metadata.
"""

from __future__ import annotations

import re


def parse_class_meta(source_code: str) -> dict:
    """Extract class metadata from Python source."""
    result = {'name': '', 'chinese_name': '', 'description': '', 'category': ''}

    class_match = re.search(r'^\s*class\s+(\w+)\s*\(', source_code, re.MULTILINE)
    if class_match:
        result['name'] = class_match.group(1)

    desc_match = re.search(r"""^\s*desc\s*=\s*['\"]([^'\"]*)['\"]""", source_code, re.MULTILINE)
    if desc_match:
        result['chinese_name'] = desc_match.group(1)

    desc_long_match = re.search(
        r'^\s*description\s*=\s*("""|\'\'\')(.*?)\1',
        source_code,
        re.MULTILINE | re.DOTALL,
    )
    if not desc_long_match:
        desc_long_match = re.search(
            r"""^\s*description\s*=\s*['\"]([^'\"]*)['\"]""",
            source_code,
            re.MULTILINE,
        )
    if desc_long_match:
        result['description'] = (
            desc_long_match.group(2)
            if desc_long_match.lastindex and desc_long_match.lastindex >= 2
            else desc_long_match.group(1)
        )

    cat_match = re.search(r"""^\s*category\s*=\s*['\"]([^'\"]*)['\"]""", source_code, re.MULTILINE)
    if cat_match:
        result['category'] = cat_match.group(1)

    return result


def assemble_factor_source(
    source_code: str,
    chinese_name: str = '',
    description: str = '',
    category: str = '自编',
) -> str:
    """Persist editor source plus metadata without surprising visible imports.

    The editor source is expected to contain imports, class definition, and
    factor_expr. We keep the user's imports as-is and only add imports that are
    both missing and required by symbols already present in the source.
    """
    lines = source_code.split('\n')
    class_start = None
    for i, line in enumerate(lines):
        if re.match(r'^\s*class\s+\w+\s*\(', line):
            class_start = i
            break
    if class_start is None:
        raise ValueError('源码中未找到 class 定义')

    import_lines = _clean_generated_header(lines[:class_start])
    class_match = re.search(r'^\s*class\s+(\w+)\s*\((.*?)\)\s*:\s*$', lines[class_start])
    class_name = class_match.group(1) if class_match else 'MyFactor'
    base_class = class_match.group(2).strip() if class_match else 'FactorFamily'

    body_lines = []
    in_factor_expr = False
    factor_expr_indent = ''
    for line in lines[class_start + 1:]:
        if re.match(r'^\s*(@staticmethod\s*$|def\s+factor_expr\s*\()', line):
            in_factor_expr = True
            factor_expr_indent = line[:len(line) - len(line.lstrip())]
            continue
        if in_factor_expr:
            stripped = line.strip()
            if stripped:
                line_indent = line[:len(line) - len(line.lstrip())]
                if len(line_indent) <= len(factor_expr_indent):
                    break
                if re.match(r'^\s*(desc|description|category)\s*=', line):
                    continue
            body_lines.append(line)

    parts = []
    parts.extend(import_lines)
    for missing_import in _needed_import_lines(source_code, import_lines):
        if parts and parts[-1].strip():
            parts.append(missing_import)
        else:
            parts.append(missing_import)
    if parts and parts[-1].strip():
        parts.append('')

    indent = '    '
    parts.append(f'class {class_name}({base_class}):')
    parts.append(f'{indent}@staticmethod')
    parts.append(f'{indent}def factor_expr():')
    for bl in body_lines:
        parts.append(bl if not bl or bl.startswith(indent) else indent + bl)

    if chinese_name:
        parts.append('')
        parts.append(f'{indent}desc = {repr(chinese_name)}')

    if description:
        parts.append('')
        if '\n' in description:
            parts.append(f'{indent}description = """')
            for dl in description.split('\n'):
                parts.append(f'{indent}{dl}')
            parts.append(f'{indent}"""')
        else:
            parts.append(f'{indent}description = {repr(description)}')

    if category:
        parts.append(f'{indent}category = {repr(category)}')

    parts.append('')
    return '\n'.join(parts)


def strip_factor_meta(source_code: str) -> str:
    """Remove persisted metadata and old generated headers for editor display."""
    lines = source_code.split('\n')
    stripped = []
    in_multiline_desc = False
    for line in lines:
        if line.strip().startswith('# -*- coding:') or line.strip().startswith('# Custom Factor:'):
            continue
        if re.match(r'^\s*description\s*=\s*("""|\'\'\')', line):
            in_multiline_desc = True
            if line.count('"""') + line.count("'''") >= 2:
                in_multiline_desc = False
            continue
        if in_multiline_desc:
            if '"""' in line or "'''" in line:
                in_multiline_desc = False
            continue
        if re.match(r'^\s*(desc|description|category)\s*=', line):
            continue
        stripped.append(line)
    return _drop_unused_parameter_imports(stripped).strip('\n')


def _clean_generated_header(lines: list[str]) -> list[str]:
    return [
        line for line in lines
        if not line.strip().startswith('# -*- coding:')
        and not line.strip().startswith('# Custom Factor:')
    ]


def _needed_import_lines(source_code: str, import_lines: list[str]) -> list[str]:
    imports = []
    if re.search(r'\bFactorFamily\b', source_code) and not _has_imported_symbol(import_lines, 'FactorFamily'):
        imports.append('from tools.factors import FactorFamily')

    parameter_symbols = ['WindowParam', 'DataColumnParam', 'DateOrTimeParam']
    missing_params = [
        symbol for symbol in parameter_symbols
        if re.search(rf'\b{symbol}\b', source_code) and not _has_imported_symbol(import_lines, symbol)
    ]
    if missing_params:
        imports.append('from tools.parameters import ' + ', '.join(missing_params))
    return imports


def _has_imported_symbol(import_lines: list[str], symbol: str) -> bool:
    return any(
        re.match(r'^\s*(from|import)\s+', line) and re.search(rf'\b{symbol}\b', line)
        for line in import_lines
    )


def _drop_unused_parameter_imports(lines: list[str]) -> str:
    body = '\n'.join(line for line in lines if not re.match(r'^\s*from\s+tools\.parameters\s+import\s+', line))
    result = []
    for line in lines:
        match = re.match(r'^(\s*)from\s+tools\.parameters\s+import\s+(.+?)\s*$', line)
        if not match:
            result.append(line)
            continue
        symbols = [part.strip() for part in match.group(2).split(',') if part.strip()]
        used = [symbol for symbol in symbols if re.search(rf'\b{re.escape(symbol)}\b', body)]
        if used:
            result.append(f'{match.group(1)}from tools.parameters import {", ".join(used)}')
    return '\n'.join(result)
