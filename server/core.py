"""
Core Blueprint — 应用入口和页面路由。

负责：
  - 首页 (/) 及功能页面（价格查看）渲染
  - /docs/* 文档体系全体路由（用户手册、开发者指南、数据字典、工具类源码）
  - 数据字典页动态调用 data_dictionary 扫描器
  - 工具类源码页 AST 解析 + 折叠渲染
"""

from flask import Blueprint, jsonify, redirect, render_template, request

core_bp = Blueprint('core', __name__)


@core_bp.route('/', methods=['GET'])
def home():
    return render_template('home.html')


@core_bp.route('/products', methods=['GET'])
def products():
    """产品管理 & 序列查看页面。"""
    return render_template('products.html')


@core_bp.route('/local-data', methods=['GET'])
def local_data():
    """Local SQL data browser entry; redirects to sqlite-web."""
    return redirect('/sqlite-web/')


@core_bp.route('/api/local-data/stores', methods=['GET'])
def api_local_data_stores():
    from server.services.local_sql_data import list_stores
    return jsonify({'success': True, 'stores': list_stores()})


@core_bp.route('/api/local-data/<store_key>/tables', methods=['GET'])
def api_local_data_tables(store_key):
    from server.services.local_sql_data import list_tables
    try:
        return jsonify({'success': True, 'store': store_key, 'tables': list_tables(store_key)})
    except Exception as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400


@core_bp.route('/api/local-data/<store_key>/table/<table_name>', methods=['GET'])
def api_local_data_table(store_key, table_name):
    from server.services.local_sql_data import read_table
    try:
        payload = read_table(
            store_key,
            table_name,
            limit=int(request.args.get('limit', 200)),
            offset=int(request.args.get('offset', 0)),
        )
        return jsonify({'success': True, **payload})
    except Exception as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400


@core_bp.route('/docs', methods=['GET'])
def docs():
    """用户手册首页。"""
    return render_template('docs/user_manual_home.html')


@core_bp.route('/docs/single-factor', methods=['GET'])
def docs_single_factor():
    """用户手册 - 单因子测试。"""
    return render_template('docs/user_manual_single_factor.html')


@core_bp.route('/docs/price-viewer', methods=['GET'])
def docs_price_viewer():
    """用户手册 - 价格查看。"""
    return render_template('docs/user_manual_price_viewer.html')


@core_bp.route('/docs/factor-editor', methods=['GET'])
def docs_factor_editor():
    """用户手册 - 因子管理。"""
    return render_template('docs/user_manual_factor_editor.html')


@core_bp.route('/docs/data-dictionary', methods=['GET'])
def docs_data_dictionary():
    """数据字典 — 全量字段清单（SOE 合规审计用）。"""
    from server.services.data_dictionary import build_data_dictionary, data_dictionary_to_dict
    from server.services.sqlite.bootstrap import ensure_unified_sqlite_store, load_data_dictionary_snapshot

    ensure_unified_sqlite_store()
    dd = load_data_dictionary_snapshot()
    if dd is None:
        dd = data_dictionary_to_dict(build_data_dictionary())
    return render_template('docs/data_dictionary.html', dd=dd)


@core_bp.route('/docs/dev', methods=['GET'])
def docs_dev():
    """开发者指南首页。"""
    return render_template('docs/dev_home.html')


@core_bp.route('/docs/dev/backend', methods=['GET'])
def docs_dev_backend():
    """开发者指南 - 后端架构。"""
    return render_template('docs/dev_backend.html')


@core_bp.route('/docs/dev/frontend', methods=['GET'])
def docs_dev_frontend():
    """开发者指南 - 前端架构。"""
    return render_template('docs/dev_frontend.html')


@core_bp.route('/docs/dev/data-pipeline', methods=['GET'])
def docs_dev_data_pipeline():
    """开发者指南 - 数据管线。"""
    return render_template('docs/dev_data_pipeline.html')


@core_bp.route('/docs/dev/deployment', methods=['GET'])
def docs_dev_deployment():
    """开发者指南 - 部署配置。"""
    return render_template('docs/dev_deployment.html')


@core_bp.route('/docs/tools', methods=['GET'])
def docs_tools():
    """工具类代码概览页——带目录导览，点击进入单个文件。"""
    import os
    from server.services.tool_docs import scan_tool_files
    tools_dir = os.path.join(os.getcwd(), 'tools')
    return render_template('tools_doc.html', files=scan_tool_files(tools_dir))


@core_bp.route('/docs/tool/<path:rel_path>', methods=['GET'])
def docs_tool_detail(rel_path):
    """工具类文件代码详情页——AST解析源码，按类/函数分块折叠展示。"""
    import os, ast, html as html_mod

    tools_dir = os.path.join(os.getcwd(), 'tools')
    file_path = os.path.join(tools_dir, rel_path)
    real = os.path.realpath(file_path)
    if not real.startswith(os.path.realpath(tools_dir) + os.sep) or not os.path.isfile(real):
        return '<h2>文件不存在</h2><a href="/docs">← 返回文档</a>', 404

    with open(real, 'r', encoding='utf-8') as f:
        source = f.read()

    # ---------- 提取 # ===== 头部注释 ----------
    lines = source.split('\n')
    desc_lines = []
    in_header = False
    for line in lines:
        s = line.strip()
        if s.startswith('# ==') and not in_header:
            in_header = True; continue
        if s.startswith('# ==') and in_header:
            break
        if in_header and s.startswith('#'):
            desc_lines.append(s.lstrip('# '))
        elif in_header and s == '':
            desc_lines.append('')
        elif in_header and not s.startswith('#'):
            break
    description = '<br>'.join(desc_lines) if desc_lines else '（无模块级注释）'

    # ---------- AST 解析源码结构 ----------
    def esc(text):
        return html_mod.escape(text)

    def build_chunks(src):
        """用 AST 将源码拆分为导入块、类和顶层函数块。"""
        try:
            tree = ast.parse(src)
        except SyntaxError:
            return [{'type': 'raw', 'title': '源码', 'code': esc(src), 'doc': ''}]

        chunks = []
        imports_code = []

        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                start = node.lineno - 1
                end = node.end_lineno
                imports_code.append('\n'.join(src.split('\n')[start:end]))

        if imports_code:
            chunks.append({
                'type': 'imports',
                'title': '📦 导入',
                'code': esc('\n'.join(imports_code)),
                'doc': ''
            })

        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                chunks.append(_parse_class(node, src))
            elif isinstance(node, ast.FunctionDef):
                if not node.name.startswith('_'):
                    chunks.append(_parse_func(node, src))
            # 跳过 Import/Assign 等（已在 imports 中处理）

        return chunks

    def _parse_class(node, src):
        cls_lines = src.split('\n')
        doc = ast.get_docstring(node) or ''
        start = node.lineno - 1
        end = node.end_lineno

        # 找类上方连续单行注释
        comment = ''
        i = start - 1
        while i >= 0:
            line = cls_lines[i].strip()
            if line.startswith('#') and not line.startswith('# =='):
                comment = line.lstrip('# ') + '\n' + comment
                i -= 1
            else:
                break
        full_doc = (comment.strip() + '\n' + doc).strip()

        # 子成员：方法
        sub_chunks = []
        for sub in node.body:
            if isinstance(sub, ast.FunctionDef):
                sub_chunks.append(_parse_func(sub, src, is_method=True))

        return {
            'type': 'class',
            'title': f'🐍 class {node.name}({", ".join(b.id if isinstance(b, ast.Name) else (b.value.id if isinstance(b, ast.Attribute) and isinstance(b.value, ast.Name) else "...") for b in node.bases)})' if node.bases else f'🐍 class {node.name}',
            'code': esc('\n'.join(cls_lines[start:end])),
            'doc': esc(full_doc),
            'sub': sub_chunks
        }

    def _parse_func(node, src, is_method=False):
        func_lines = src.split('\n')
        doc = ast.get_docstring(node) or ''
        start = node.lineno - 1
        end = node.end_lineno
        params = _format_signature(node)

        comment = ''
        i = start - 1
        while i >= 0:
            line = func_lines[i].strip()
            if line.startswith('#') and not line.startswith('# =='):
                comment = line.lstrip('# ') + '\n' + comment
                i -= 1
            else:
                break
        full_doc = (comment.strip() + '\n' + doc).strip()

        prefix = '🔹' if is_method else '📌'
        return {
            'type': 'method' if is_method else 'function',
            'title': f'{prefix} {node.name}({params})',
            'code': esc('\n'.join(func_lines[start:end])),
            'doc': esc(full_doc),
        }

    def _format_signature(node):
        """格式化函数签名（不含类型注解全路径）。"""
        parts = []
        for a in node.args.args:
            s = a.arg
            if a.annotation:
                s += ': ' + ast.unparse(a.annotation) if hasattr(ast, 'unparse') else ': ...'
            parts.append(s)
        if node.args.vararg:
            parts.append('*' + node.args.vararg.arg)
        if node.args.kwarg:
            parts.append('**' + node.args.kwarg.arg)
        return ', '.join(parts)

    chunks = build_chunks(source)

    # ---------- 渲染 HTML ----------
    nav_items = ''
    for i, ch in enumerate(chunks):
        nav_items += f'<a href="#chunk-{i}" class="chunk-nav-link">{esc(ch["title"])}</a>\n'
        for sub in ch.get('sub', []):
            nav_items += f'<a href="#chunk-{i}-sub" class="chunk-nav-sub">{esc(sub["title"])}</a>\n'

    chunks_html = ''
    for i, ch in enumerate(chunks):
        sub_html = ''
        for s in ch.get('sub', []):
            doc_class = f'doc-{s["type"]}'
            sub_html += f'''
            <div class="chunk {s["type"]}-chunk" id="chunk-{i}-sub">
                <details class="chunk-details">
                    <summary class="chunk-summary">
                        <span class="chunk-icon">{s["title"].split()[0]}</span>
                        <span class="chunk-name">{esc(" ".join(s["title"].split()[1:]))}</span>
                    </summary>
                    {f'<div class="chunk-doc {doc_class}">{s["doc"]}</div>' if s["doc"] else ''}
                    <details class="code-details">
                        <summary class="code-summary">📄 查看源码</summary>
                        <div class="code-block"><pre>{s["code"]}</pre></div>
                    </details>
                </details>
            </div>'''

        doc_class = f'doc-{ch["type"]}'
        chunks_html += f'''
        <div class="chunk {ch["type"]}-chunk" id="chunk-{i}">
            <details class="chunk-details">
                <summary class="chunk-summary">
                    <span class="chunk-icon">{ch["title"].split()[0]}</span>
                    <span class="chunk-name">{esc(" ".join(ch["title"].split()[1:]))}</span>
                </summary>
                {f'<div class="chunk-doc {doc_class}">{ch["doc"]}</div>' if ch["doc"] else ''}
                <details class="code-details">
                    <summary class="code-summary">📄 查看源码</summary>
                    <div class="code-block"><pre>{ch["code"]}</pre></div>
                </details>
            </details>
        </div>'''
        chunks_html += sub_html

    return f'''<!DOCTYPE html>
<html>
<head>
    <title>{esc(rel_path)} — 工具类源码</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        *, *::before, *::after {{ box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f4f6f8; margin: 0; }}
        .wrapper {{ display: flex; max-width: 1400px; margin: 0 auto; min-height: 100vh; }}
        .sidebar {{ width: 260px; flex-shrink: 0; background: #fff; border-right: 1px solid #e8ecf0; padding: 20px 16px; position: sticky; top: 0; height: 100vh; overflow-y: auto; }}
        .sidebar h4 {{ font-size: 12px; color: #999; text-transform: uppercase; letter-spacing: 0.5px; margin: 0 0 12px; }}
        .sidebar .chunk-nav-link {{ display: block; padding: 4px 8px; font-size: 12px; color: #333; text-decoration: none; border-radius: 4px; margin: 2px 0; }}
        .sidebar .chunk-nav-link:hover {{ background: #eef4fb; }}
        .sidebar .chunk-nav-sub {{ display: block; padding: 3px 8px 3px 24px; font-size: 11px; color: #777; text-decoration: none; border-radius: 4px; margin: 1px 0; }}
        .sidebar .chunk-nav-sub:hover {{ background: #eef4fb; color: #4a90d9; }}
        .sidebar .back {{ display: block; color: #4a90d9; text-decoration: none; font-size: 12px; margin-bottom: 16px; }}
        .main {{ flex: 1; min-width: 0; padding: 28px 36px 60px; }}
        .back-top {{ color: #4a90d9; text-decoration: none; font-size: 13px; }}
        .header {{ background: #fff; border-radius: 10px; padding: 24px 28px; margin: 12px 0 24px; box-shadow: 0 1px 4px rgba(0,0,0,0.06); }}
        .header h1 {{ font-size: 22px; margin: 0 0 8px; }}
        .header .path {{ font-size: 13px; color: #888; }}
        .header .desc {{ font-size: 14px; color: #555; line-height: 1.7; margin-top: 12px; }}
        .chunk {{ margin-bottom: 16px; }}
        .chunk-details {{ background: #fff; border-radius: 10px; box-shadow: 0 1px 4px rgba(0,0,0,0.06); overflow: hidden; }}
        .chunk-summary {{ cursor: pointer; padding: 10px 18px; font-size: 14px; font-weight: 600; color: #222; display: flex; align-items: center; gap: 8px; user-select: none; background: #fafbfc; border-bottom: 1px solid #eef0f2; }}
        .chunk-summary:hover {{ background: #f0f4f8; }}
        .chunk-details[open] .chunk-summary {{ border-bottom: 1px solid #ddd; }}
        .chunk-icon {{ font-size: 14px; }}
        .chunk-doc {{ padding: 12px 18px 6px; font-size: 13px; color: #555; line-height: 1.6; white-space: pre-line; border-bottom: 1px solid #eef0f2; }}
        .doc-imports {{ color: #888; }}
        .doc-class {{ color: #2d6a4f; }}
        .doc-method {{ color: #3a5a8c; }}
        .doc-function {{ color: #6b4c8a; }}
        .code-block {{ background: #1e293b; padding: 14px 18px; overflow-x: auto; }}
        .code-block pre {{ margin: 0; color: #e2e8f0; font-size: 12.5px; line-height: 1.6; font-family: "SF Mono", "Fira Code", "Cascadia Code", monospace; white-space: pre; }}
        .code-details {{ margin-top: 4px; }}
        .code-summary {{ cursor: pointer; padding: 6px 18px; font-size: 12px; color: #888; user-select: none; }}
        .code-summary:hover {{ color: #4a90d9; }}
        .method-chunk {{ margin-left: 20px; }}
        @media (max-width: 900px) {{ .sidebar {{ display: none; }} .main {{ padding: 20px 16px; }} }}
    </style>
</head>
<body>
<div class="wrapper">
    <aside class="sidebar">
        <a class="back" href="/docs">← 返回技术文档</a>
        <a class="back" href="/docs/tools" style="margin-top:-4px;">📂 工具类目录</a>
        <h4 style="margin-top: 16px;">代码结构</h4>
        {nav_items}
    </aside>
    <div class="main">
        <a class="back-top" href="/docs/tools">← 返回工具类目录</a>
        <div class="header">
            <h1>{esc(rel_path)}</h1>
            <div class="path">tools/{esc(rel_path)}</div>
            <div class="desc">{description}</div>
        </div>
        {chunks_html}
    </div>
</div>
</body>
</html>'''
