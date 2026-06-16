#!/usr/bin/env python3
"""
解析 tools/ 目录下所有 .py 文件，提取：
  - 文件头文档注释（以 # ===== 开头，到第一个新行或 import 之前的注释块）
  - 完整源代码
返回 JSON，供 tools_doc.html 页面使用。
"""
import json
import os

from tools.tool_docs import scan_tool_files


if __name__ == '__main__':
    tools_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools')
    result = scan_tool_files(tools_dir, include_code=True)
    print(json.dumps(result, ensure_ascii=False))
