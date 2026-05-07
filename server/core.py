"""Core Blueprint: application entry point.
  GET  /                    — 门户首页（模块列表）
  GET  /single_factor_test  — 单因子测试页
  GET  /multi_factor_test     — 多因子分析页  GET  /price_viewer        — 价格序列查看页"""
import os, traceback
from flask import Blueprint, request, jsonify, render_template, session
from .shared import (
    get_factor_groups, get_chinese_names, build_group_html, get_factor_main_section_html,
    get_custom_factor_instance, _current_user, _user_data_dir,
)

core_bp = Blueprint('core', __name__)


def _list_custom_factors_for_sidebar(username: str) -> list:
    """返回当前用户的自定义因子列表（用于左侧边栏展示）。"""
    import json as _json
    cf_dir = os.path.join(_user_data_dir(username), 'custom_factors')
    factors = []
    if not os.path.exists(cf_dir):
        return factors
    for fname in os.listdir(cf_dir):
        if not fname.endswith('.json'):
            continue
        factor_id = fname[:-5]
        try:
            with open(os.path.join(cf_dir, fname), 'r', encoding='utf-8') as f:
                data = _json.load(f)
            data['id'] = factor_id
            factors.append(data)
        except Exception:
            pass
    factors.sort(key=lambda f: f.get('updated_at', ''), reverse=True)
    return factors


def _search_custom_factors(factors, query):
    """在自定义因子列表中搜索。"""
    q = query.lower()
    return [
        f for f in factors
        if q in f.get('name', '').lower()
        or q in f.get('chinese_name', '').lower()
        or q in f.get('category', '').lower()
    ]


@core_bp.route('/', methods=['GET'])
def home():
    return render_template('home.html')


@core_bp.route('/single_factor_test', methods=['GET'])
def index():
    factors_dir = os.path.join(os.getcwd(), 'Factors')
    groups, factor_names = get_factor_groups(factors_dir)
    search_query  = request.args.get('search', '')
    selected_name = request.args.get('factor', '')
    factor_type   = request.args.get('type', '')  # 'custom' 或空='public'
    chinese_names = get_chinese_names(factors_dir)

    # 获取当前用户的自定义因子
    username = _current_user()
    custom_factors = []
    if username:
        custom_factors = _list_custom_factors_for_sidebar(username)

    # 搜索过滤
    if search_query:
        q = search_query.lower()
        groups = {
            g: [n for n in names if q in n.lower() or q in chinese_names.get(n, '').lower()]
            for g, names in groups.items()
        }
        groups = {g: names for g, names in groups.items() if names}
        factor_names = [n for n in factor_names if q in n.lower() or q in chinese_names.get(n, '').lower()]
        # 同时搜索自定义因子
        custom_factors = _search_custom_factors(custom_factors, q)

    group_html = build_group_html(groups, chinese_names, custom_factors) if (groups or custom_factors) else '<div style="color:#888;">无匹配因子</div>'
    main_content = ''

    if selected_name:
        if factor_type == 'custom' and username:
            # 加载自定义因子
            try:
                ff = get_custom_factor_instance(username, selected_name)
                if ff is not None:
                    from tools.factors.Parameters import FactorFreqParam, ReverseParam
                    math_expr = getattr(ff, 'math_expr', '')
                    desc = getattr(ff, 'desc', '') or getattr(ff, 'chinese_name', '') or ''
                    description = getattr(ff, 'description', '') or ''
                    params = ff.params
                    param_aliases = [p.alias for p in params]
                    factors = ff.get_factors(params_list=[])
                    from server.shared import _get_session_params
                    start_date = getattr(__import__('Settings'), 'default_test_start_date', '2025-01-02')
                    end_date = getattr(__import__('Settings'), 'default_test_end_date', '2025-05-31')
                    import pandas as pd
                    start_date = start_date.strftime('%Y-%m-%d') if isinstance(start_date, pd.Timestamp) else str(start_date)
                    end_date = end_date.strftime('%Y-%m-%d') if isinstance(end_date, pd.Timestamp) else str(end_date)
                    import Settings
                    start_time = getattr(Settings, 'default_day_start_time', '09:30')
                    end_time = getattr(Settings, 'default_day_end_time', '15:00')
                    main_content = render_template(
                        'factor_main.html',
                        factor_family_alias=selected_name,
                        chinese_name=desc,
                        math_expr=math_expr,
                        description=description,
                        params=params,
                        param_aliases=param_aliases,
                        factors=factors,
                        start_date=start_date,
                        end_date=end_date,
                        start_time=start_time,
                        end_time=end_time,
                        is_custom=True,
                        factor_type='custom',
                    )
                else:
                    main_content = f'''<div class="section"><div class="section-title">错误</div><div style="color:#d40000;padding:20px;">无法加载自定义因子 "{selected_name}"</div></div>'''
            except Exception as e:
                traceback.print_exc()
                main_content = f'''<div class="section"><div class="section-title">错误</div><div style="color:#d40000;padding:20px;">加载自定义因子 "{selected_name}" 失败:<br><pre>{str(e)}</pre></div></div>'''
        elif selected_name in factor_names:
            try:
                main_content = get_factor_main_section_html(selected_name)
            except Exception as e:
                traceback.print_exc()
                main_content = f'''
                    <div class="section">
                        <div class="section-title">错误</div>
                        <div style="color:#d40000;padding:20px;">
                            加载因子 "{selected_name}" 失败:<br>
                            <pre>{str(e)}</pre>
                        </div>
                    </div>
                '''
        else:
            main_content = f'<div style="margin-top:64px;color:#888;font-size:22px;text-align:center;">因子 "{selected_name}" 未找到</div>'
    elif not groups and not custom_factors:
        main_content = '<div style="margin-top:64px;color:#888;font-size:22px;text-align:center;">未搜索到任何因子</div>'

    return render_template(
        'base.html',
        search_query=search_query,
        group_html=group_html,
        main_content=main_content,
        initial_modules=[],
    )


@core_bp.route('/multi_factor_test', methods=['GET'])
def multi_factor():
    """多因子分析页面。"""
    return render_template('multi_factor.html')


@core_bp.route('/price_viewer', methods=['GET'])
def price_viewer():
    """价格序列查看页面。"""
    return render_template('price_viewer.html')


@core_bp.route('/docs', methods=['GET'])
def docs():
    """技术文档页面。"""
    return render_template('docs.html')


@core_bp.route('/docs/tools', methods=['GET'])
def docs_tools():
    """工具类代码概览页——带目录导览，点击进入单个文件。"""
    import os, re, json
    tools_dir = os.path.join(os.getcwd(), 'tools')

    def extract_desc(source):
        lines = source.split('\n')
        desc_lines = []
        in_desc = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('# ====') and not in_desc:
                in_desc = True
                continue
            if stripped.startswith('# ====') and in_desc:
                break
            if in_desc:
                if stripped.startswith('# '):
                    desc_lines.append(stripped[2:])
                elif stripped == '#':
                    desc_lines.append('')
                else:
                    break
        return '\n'.join(desc_lines).strip()

    files = []
    for root, dirs, filenames in os.walk(tools_dir):
        dirs[:] = [d for d in sorted(dirs) if not d.startswith('__pycache__') and not d.startswith('.')]
        for fname in sorted(filenames):
            if fname.endswith('.py') and fname != '__init__.py':
                full = os.path.join(root, fname)
                rel = os.path.relpath(full, tools_dir)
                with open(full, 'r', encoding='utf-8') as f:
                    src = f.read()
                desc = extract_desc(src)
                files.append({'path': rel, 'desc': desc})

    return render_template('tools_doc.html', files=files)


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