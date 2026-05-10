#!/usr/bin/env python3
"""
解析 tools/ 目录下所有 .py 文件，提取：
  - 文件头文档注释（以 # ===== 开头，到第一个新行或 import 之前的注释块）
  - 完整源代码
返回 JSON，供 tools_doc.html 页面使用。
"""
import os
import json
from typing import Any

from server.services.tool_docs import extract_header_description, parse_tool_file, scan_tool_files


def extract_description(source: str) -> str:
    """Compatibility wrapper for old callers."""
    return extract_header_description(source)


def parse_file(filepath: str, tools_dir: str) -> dict[str, Any]:
    """解析单个 .py 文件"""
    return parse_tool_file(filepath, tools_dir, include_code=True)


def scan_tools(tools_dir: str) -> list[dict[str, Any]]:
    """扫描 tools/ 下所有 .py 文件（含子目录），按路径排序"""
    return scan_tool_files(tools_dir, include_code=True)


if __name__ == '__main__':
    tools_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools')
    result = scan_tools(tools_dir)
    print(json.dumps(result, ensure_ascii=False))
