"""Core Blueprint: application entry point.
  GET  /                    — 门户首页（模块列表）
  GET  /single_factor_test  — 单因子测试页
"""
import os, traceback
from flask import Blueprint, request, jsonify, render_template
from .shared import (
    get_factor_groups, get_chinese_names, build_group_html, get_factor_main_section_html,
)

core_bp = Blueprint('core', __name__)


@core_bp.route('/', methods=['GET'])
def home():
    return render_template('home.html')


@core_bp.route('/single_factor_test', methods=['GET'])
def index():
    factors_dir = os.path.join(os.getcwd(), 'Factors')
    groups, factor_names = get_factor_groups(factors_dir)
    search_query  = request.args.get('search', '')
    selected_name = request.args.get('factor', '')
    chinese_names = get_chinese_names(factors_dir)

    if search_query:
        q = search_query.lower()
        groups = {
            g: [n for n in names if q in n.lower() or q in chinese_names.get(n, '').lower()]
            for g, names in groups.items()
        }
        groups = {g: names for g, names in groups.items() if names}
        factor_names = [n for n in factor_names if q in n.lower() or q in chinese_names.get(n, '').lower()]

    group_html = build_group_html(groups, chinese_names) if groups else '<div style="color:#888;">无匹配因子</div>'
    main_content = ''

    if selected_name and selected_name in factor_names:
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
    elif not groups:
        main_content = '<div style="margin-top:64px;color:#888;font-size:22px;text-align:center;">未搜索到任何因子</div>'

    return render_template(
        'base.html',
        search_query=search_query,
        group_html=group_html,
        main_content=main_content,
        initial_modules=[],
    )



