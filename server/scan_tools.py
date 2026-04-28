#!/usr/bin/env python3
"""
解析 tools/ 目录下所有 .py 文件，提取：
  - 文件头文档注释（以 # ===== 开头，到第一个新行或 import 之前的注释块）
  - 完整源代码
返回 JSON，供 tools_doc.html 页面使用。
"""
import os
import re
import json
import sys
from pathlib import Path
from typing import Any

def extract_description(source: str) -> str:
    """提取文件头部的文档注释（双 # 开头注释块之前用 ===== 分隔行标识）"""
    lines = source.split('\n')
    desc_lines = []
    in_desc = False
    for line in lines:
        stripped = line.strip()
        # 检测到 ===== 分隔线开始收集
        if stripped.startswith('# ====') and not in_desc:
            in_desc = True
            continue
        # 遇到另一个 ===== 分隔线停止
        if stripped.startswith('# ====') and in_desc:
            in_desc = False
            continue
        if in_desc:
            if stripped.startswith('# '):
                desc_lines.append(stripped[2:])
            elif stripped == '#':
                desc_lines.append('')
            else:
                break
    return '\n'.join(desc_lines)


def parse_file(filepath: str, tools_dir: str) -> dict[str, Any]:
    """解析单个 .py 文件"""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    rel_path = os.path.relpath(filepath, tools_dir)
    desc = extract_description(content)
    
    return {
        'path': rel_path,
        'name': rel_path.replace('/', ' / ').replace('\\', ' / '),
        'desc': desc.strip(),
        'code': content,
    }


def scan_tools(tools_dir: str) -> list[dict[str, Any]]:
    """扫描 tools/ 下所有 .py 文件（含子目录），按路径排序"""
    files = []
    for root, dirs, filenames in os.walk(tools_dir):
        dirs[:] = [d for d in dirs if not d.startswith('__pycache__') and not d.startswith('.')]
        for fname in sorted(filenames):
            if fname.endswith('.py') and fname != '__init__.py':
                full = os.path.join(root, fname)
                files.append(parse_file(full, tools_dir))
    
    # 按路径分组排序
    files.sort(key=lambda x: x['path'])
    return files


if __name__ == '__main__':
    tools_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tools')
    result = scan_tools(tools_dir)
    print(json.dumps(result, ensure_ascii=False))
