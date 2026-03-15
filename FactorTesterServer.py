   
# factor_server.py

import importlib.util
import importlib
import os
import sys
import threading
import webbrowser

from flask import Flask, request, jsonify, render_template_string
from Settings import *
from Factor import FactorFamily, Factor, StartCalcParam

app = Flask(__name__)

# --- Global server reference for shutdown ---
_server = None

# --- FactorFamily singleton cache ---
_factor_family_cache = {}
factor_testers = []

def get_factor_family_instance(module_name):
    if module_name in _factor_family_cache:
        return _factor_family_cache[module_name]
    factors_dir = os.path.join(os.getcwd(), "Factors")
    module_path = os.path.join(factors_dir, f"{module_name}.py")
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is not None and spec.loader is not None:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        ff = getattr(module, module_name)()
        assert isinstance(ff, FactorFamily)
        _factor_family_cache[module_name] = ff
        return ff
    else:
        raise ImportError(f"Cannot load module '{module_name}' from '{module_path}'")

def get_factor_groups(factors_dir):
    factor_files = [f for f in os.listdir(factors_dir) if f.endswith(".py")]
    factor_names = [os.path.splitext(f)[0] for f in factor_files]

    def get_group(name):
        group = ""
        upper_count = 0
        for c in name:
            if c.isupper():
                upper_count += 1
                if upper_count == 1:
                    group += c
                elif upper_count == 2:
                    break
            else:
                if upper_count == 1:
                    group += c
        return group if group else name

    groups = {}
    for name in factor_names:
        group = get_group(name)
        groups.setdefault(group, []).append(name)
    return groups, factor_names

def build_group_html(groups):
    group_html = ""
    for group, names in sorted(groups.items()):
        group_html += f'<div style="margin-bottom:16px;"><b style="font-size:20px;color:#0078d4;">{group}</b>'
        group_html += '<ul style="max-height:180px;overflow-y:auto;border:1px solid #eee;border-radius:4px;padding:0;margin-top:8px;">'
        for name in sorted(names):
            group_html += f'<li style="padding:8px;border-bottom:1px solid #eee;"><a href="?factor={name}" style="text-decoration:none;color:#333;font-size:18px;">{name}</a></li>'
        group_html += '</ul></div>'
    return group_html

BASE_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>单因子测试</title>
    <style>
        body { font-family: 'Segoe UI', Arial, sans-serif; background: #f6f8fa; }
        .container { display: flex; max-width: 1200px; margin: 40px auto; background: #fff; border-radius: 8px; box-shadow: 0 2px 8px #ddd; padding: 32px; position: relative; min-height: 700px; }
        .sidebar { width: 320px; border-right: 1px solid #eee; padding-right: 24px; }
        .main { flex: 1; padding-left: 32px; }
        h2 { color: #222; }
        input[type="text"] { width: 100%; padding: 8px; margin-bottom: 16px; border-radius: 4px; border: 1px solid #ccc; font-size: 16px; }
        ul { list-style: none; padding: 0; margin: 0; }
        li:hover { background: #e6f7ff; }
        button { margin-top: 24px; padding: 8px 16px; border-radius: 4px; border: none; background: #0078d4; color: #fff; font-size: 16px; cursor: pointer; }
        .shutdown-btn-topright { position: absolute; top: 16px; right: 16px; padding: 8px 16px; border-radius: 4px; border: none; background: #d40000; color: #fff; font-size: 16px; cursor: pointer; z-index: 10; }
        .section { margin-bottom: 32px; }
        .section-title { font-size:18px;color:#0078d4;margin-bottom:8px; }
        .module { border: 1px solid #eee; border-radius: 6px; background: #fafbfc; margin-bottom: 16px; padding: 16px; }
    </style>
    <script>
        function searchFactors() {
            var query = document.getElementById('search').value;
            window.location.href = '?search=' + encodeURIComponent(query);
        }
        function shutdownServer() {
            if (confirm('确定要关闭服务器吗？')) {
                fetch('/shutdown', {method: 'POST'}).then(function() { window.close(); });
            }
        }
        document.addEventListener('DOMContentLoaded', function() {
            document.getElementById('search').addEventListener('keyup', function(e) {
                if (e.key === 'Enter') searchFactors();
            });
        });
    </script>
</head>
<body>
    <button class="shutdown-btn-topright" onclick="shutdownServer()">关闭服务器</button>
    <div class="container">
        <div class="sidebar">
            <h2>单因子测试 (./Factors)</h2>
            <input type="text" id="search" placeholder="搜索因子名称..." value="{{ search_query }}">
            {{ group_html | safe }}
            <button onclick="shutdownServer()">关闭服务器</button>
        </div>
        <div class="main">
            {{ main_content | safe }}
        </div>
    </div>
</body>
</html>
"""

def get_latex_module_html(selected_name):
    try:
        ff = get_factor_family_instance(selected_name)
        math_expr = getattr(ff, 'math_expr', '')
        latex_html = f"""
            <div class="module" id="math_expr_module" style="margin-top:32px;">
                <div class="section-title">因子表达式 (LaTeX)</div>
                <div style="background:#fafbfc;border-radius:6px;padding:16px;font-size:18px;">
                    $$ {math_expr} $$
                </div>
            </div>
            <script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
        """ if math_expr else ""
    except Exception as e:
        latex_html = f"<div style='color:#888;'>表达式加载失败: {e}</div>"
    return latex_html

def get_parameter_module_html(factor_family_alias):
    try:
        ff = get_factor_family_instance(factor_family_alias)
        params = ff.params

        sorted_params = sorted(params, key=lambda p: getattr(p, 'serial_number', 0))

        def get_col_min_width(param):
            name_len = len(str(param.name))
            return max(80, name_len * 12 + 24)

        header_html = f"""
            <tr>
                <th style='min-width:120px;height:40px;text-align:center;vertical-align:middle;'>因子(家族)名</th>
                {''.join([f"<th style='min-width:{get_col_min_width(p)}px;height:40px;text-align:center;vertical-align:middle;'>{p.name}</th>" for p in sorted_params])}
                <th style='min-width:80px;height:40px;text-align:center;vertical-align:middle;'>操作</th>
            </tr>
        """

        input_style = "height:32px;line-height:normal;box-sizing:border-box;text-align:center;"
        button_style = "height:32px;line-height:normal;box-sizing:border-box;"

        input_row_html = f"""
            <tr>
                <td style='min-width:120px;text-align:center;vertical-align:middle;'>{ff.name}</td>
                {''.join([
                    f"""<td style="min-width:{get_col_min_width(p)}px;text-align:center;vertical-align:middle;">
                        <div style="display:flex;justify-content:center;align-items:center;height:40px;">
                            <input type="text" id="param_{p.alias}" value="{p.get_value_alias(p.default_value)}"
                                style="width:{get_col_min_width(p)}px;font-size:15px;border-radius:4px;border:1px solid #ccc;{input_style};margin:auto;">
                        </div>
                    </td>"""
                    for p in sorted_params
                ])}
                <td style='min-width:80px;text-align:center;vertical-align:middle;'>
                    <div style="display:flex;justify-content:center;align-items:center;height:100%;">
                        <button id="add_factor_btn" type="button" style="background:#0078d4;color:#fff;border:none;border-radius:4px;padding:6px 18px;font-size:15px;{button_style};margin:0;">新增</button>
                    </div>
                </td>
            </tr>
        """

        factor_rows_html = ""
        for idx, factor in enumerate(ff.get_factors()):
            factor_rows_html += f"""
                <tr draggable="true" data-factor-idx="{idx}">
                    <td style='min-width:120px;text-align:center;vertical-align:middle;'>{factor.name}</td>
                    {''.join([
                        f"<td style='min-width:{get_col_min_width(p)}px;text-align:center;vertical-align:middle;'>{factor.params_dict[p.alias].get_value(factor)}</td>"
                        for p in sorted_params
                    ])}
                    <td style='min-width:80px;text-align:center;vertical-align:middle;'>
                        <div style="display:flex;justify-content:center;align-items:center;height:100%;">
                            <button class="delete_factor_btn" data-factor-idx="{idx}" type="button" style="background:#d40000;color:#fff;border:none;border-radius:4px;padding:6px 18px;font-size:15px;{button_style};margin:0;">删除</button>
                        </div>
                    </td>
                </tr>
            """

        total_width = 120 + sum(get_col_min_width(p) for p in sorted_params) + 80

        table_html = f"""
            <div style="overflow-x:auto;max-width:800px;" id="param_table_scroll">
                <table style="border-collapse:collapse;width:100%;background:#fff;min-width:{total_width}px;">
                    <thead style="background:#f6f8fa;">{header_html}</thead>
                    <tbody id="factor_table_body">{input_row_html}{factor_rows_html}</tbody>
                </table>
            </div>
            <div style="margin-top:8px;">
                <input type="range" id="param_table_slider" min="0" max="0" value="0" style="width:100%;"/>
            </div>
            <div style="margin-top:8px;color:#888;font-size:15px;text-align:left;">
                如果表格宽度过大，可以用下方滑块左右浏览
            </div>
        """

        param_aliases_js = '[' + ','.join([f"'{p.alias}'" for p in sorted_params]) + ']'

        js = f"""
            <script>
                document.addEventListener('DOMContentLoaded', function() {{
                    var scrollDiv = document.getElementById('param_table_scroll');
                    var slider = document.getElementById('param_table_slider');
                    function updateSlider() {{
                        if(scrollDiv && slider) {{
                            var scrollWidth = scrollDiv.scrollWidth;
                            var clientWidth = scrollDiv.clientWidth;
                            var maxScroll = scrollWidth - clientWidth;
                            slider.max = maxScroll > 0 ? maxScroll : 0;
                            slider.value = scrollDiv.scrollLeft;
                            slider.style.display = maxScroll > 0 ? '' : 'none';
                        }}
                    }}
                    if(scrollDiv && slider) {{
                        updateSlider();
                        scrollDiv.addEventListener('scroll', function() {{
                            slider.value = scrollDiv.scrollLeft;
                        }});
                        slider.addEventListener('input', function() {{
                            scrollDiv.scrollLeft = slider.value;
                        }});
                        window.addEventListener('resize', updateSlider);
                    }}

                    function reloadParamTable() {{
                        fetch(window.location.pathname + '?factor={factor_family_alias}')
                            .then(r => r.text())
                            .then(html => {{
                                var parser = new DOMParser();
                                var doc = parser.parseFromString(html, 'text/html');
                                var newTable = doc.getElementById('param_table_scroll');
                                var oldTable = document.getElementById('param_table_scroll');
                                var newSlider = doc.getElementById('param_table_slider');
                                var oldSlider = document.getElementById('param_table_slider');
                                if(newTable && oldTable) oldTable.parentNode.replaceChild(newTable, oldTable);
                                if(newSlider && oldSlider) oldSlider.parentNode.replaceChild(newSlider, oldSlider);
                                bindParamTableEvents();
                            }});
                    }}
                    function bindParamTableEvents() {{
                        var addBtn = document.getElementById('add_factor_btn');
                        var scrollDiv = document.getElementById('param_table_scroll');
                        var slider = document.getElementById('param_table_slider');
                        if(scrollDiv && slider) {{
                            function updateSlider() {{
                                var scrollWidth = scrollDiv.scrollWidth;
                                var clientWidth = scrollDiv.clientWidth;
                                var maxScroll = scrollWidth - clientWidth;
                                slider.max = maxScroll > 0 ? maxScroll : 0;
                                slider.value = scrollDiv.scrollLeft;
                                slider.style.display = maxScroll > 0 ? '' : 'none';
                            }}
                            updateSlider();
                            scrollDiv.addEventListener('scroll', function() {{
                                slider.value = scrollDiv.scrollLeft;
                            }});
                            slider.addEventListener('input', function() {{
                                scrollDiv.scrollLeft = slider.value;
                            }});
                            window.addEventListener('resize', updateSlider);
                        }}
                        if(addBtn) {{
                            addBtn.addEventListener('click', function() {{
                                var paramValues = {{}};
                                var paramAliases = {param_aliases_js};
                                paramAliases.forEach(function(alias) {{
                                    var el = document.getElementById('param_' + alias);
                                    if(el) paramValues[alias] = el.value;
                                }});
                                fetch('/add_params', {{
                                    method: 'POST',
                                    headers: {{'Content-Type': 'application/json'}},
                                    body: JSON.stringify({{factor_family_alias: '{factor_family_alias}', params: paramValues}})
                                }}).then(r => r.json()).then(data => {{
                                    if(data.success) {{
                                        reloadParamTable();
                                        var statusSpan = document.getElementById('confirm_time_status');
                                        statusSpan.innerText = '⚠️ 点击确定按钮更新因子计算的时间范围';
                                        statusSpan.style.color = '#d40000';
                                    }}
                                    else alert('添加失败: ' + data.error);
                                }});
                            }});
                        }}
                        Array.from(document.getElementsByClassName('delete_factor_btn')).forEach(function(btn) {{
                            btn.addEventListener('click', function() {{
                                var idx = btn.getAttribute('data-factor-idx');
                                fetch('/delete_params', {{
                                    method: 'POST',
                                    headers: {{'Content-Type': 'application/json'}},
                                    body: JSON.stringify({{factor_family_alias: '{factor_family_alias}', factor_idx: idx}})
                                }}).then(r => r.json()).then(data => {{
                                    if(data.success) reloadParamTable();
                                    else alert('删除失败: ' + data.error);
                                }});
                            }});
                        }});

                        // 拖拽排序功能
                        var tbody = document.getElementById('factor_table_body');
                        var draggingRow = null;
                        var dragStartIdx = null;
                        var dragOverIdx = null;

                        Array.from(tbody.querySelectorAll('tr[draggable="true"]')).forEach(function(row) {{
                            row.addEventListener('dragstart', function(e) {{
                                draggingRow = row;
                                dragStartIdx = parseInt(row.getAttribute('data-factor-idx'));
                                row.style.opacity = '0.5';
                                e.dataTransfer.effectAllowed = 'move';
                            }});
                            row.addEventListener('dragend', function(e) {{
                                row.style.opacity = '';
                                draggingRow = null;
                                dragStartIdx = null;
                                dragOverIdx = null;
                            }});
                            row.addEventListener('dragover', function(e) {{
                                e.preventDefault();
                                dragOverIdx = parseInt(row.getAttribute('data-factor-idx'));
                                row.style.background = '#e6f7ff';
                            }});
                            row.addEventListener('dragleave', function(e) {{
                                row.style.background = '';
                            }});
                            row.addEventListener('drop', function(e) {{
                                e.preventDefault();
                                row.style.background = '';
                                dragOverIdx = parseInt(row.getAttribute('data-factor-idx'));
                                if(dragStartIdx !== null && dragOverIdx !== null && dragStartIdx !== dragOverIdx) {{
                                    fetch('/reorder_params', {{
                                        method: 'POST',
                                        headers: {{'Content-Type': 'application/json'}},
                                        body: JSON.stringify({{
                                            factor_family_alias: '{factor_family_alias}',
                                            from_idx: dragStartIdx,
                                            to_idx: dragOverIdx
                                        }})
                                    }}).then(r => r.json()).then(data => {{
                                        if(data.success) reloadParamTable();
                                        else alert('排序失败: ' + data.error);
                                    }});
                                }}
                            }});
                        }});
                    }}
                    bindParamTableEvents();
                }});
            </script>
        """

        return f"""
            <div class="module" id="parameter_module" style="margin-top:32px;">
                <div class="section-title">0. 参数设置</div>
                {table_html}
            </div>
            {js}
        """
    except Exception as e:
        return f"<div style='color:#d40000;'>参数模块加载失败: {e}</div>"

@app.route('/add_params', methods=['POST'])
def add_params():
    data = request.get_json()
    factor_family_alias = data.get('factor_family_alias')
    params = data.get('params', {})
    try:
        ff = get_factor_family_instance(factor_family_alias)
        ff.add_params(**params)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/delete_params', methods=['POST'])
def delete_params():
    data = request.get_json()
    factor_family_alias = data.get('factor_family_alias')
    factor_idx = int(data.get('factor_idx', -1))
    try:
        ff = get_factor_family_instance(factor_family_alias)
        if 0 <= factor_idx < len(ff._params_list):
            ff._params_list.pop(factor_idx)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    
@app.route('/reorder_params', methods=['POST'])
def reorder_params():
    data = request.get_json()
    factor_family_alias = data.get('factor_family_alias')
    from_idx = int(data.get('from_idx', -1))
    to_idx = int(data.get('to_idx', -1))
    try:
        ff = get_factor_family_instance(factor_family_alias)
        if 0 <= from_idx < len(ff._params_list) and 0 <= to_idx < len(ff._params_list):
            param = ff._params_list.pop(from_idx)
            ff._params_list.insert(to_idx, param)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    
def get_time_range_module_html(factor_family_alias):

    from datetime import datetime as _dt

    def pad(n):
        return f"{int(n):02d}"

    start_dt_str = f"{default_test_start_date} {default_day_start_time}"
    end_dt_str = f"{default_test_end_date} {default_day_end_time}"
    try:
        sdt = _dt.strptime(start_dt_str, "%Y-%m-%d %H:%M")
        edt = _dt.strptime(end_dt_str, "%Y-%m-%d %H:%M")
        show_next = "openModule('category_filter_module');" if sdt <= edt else "closeModule('category_filter_module');"
    except Exception:
        show_next = "closeModule('category_filter_module');"

    return f"""
        <div class="module" id="time_range_module" style="margin-top:32px;">
        <div class="section-title">1. 起始/终末时间设置</div>
        <div style="display:flex;align-items:center;gap:24px;">
            <span style="font-size:13px;">
            起始时间:
            <input type="number" min="1900" max="2100" id="start_year" value="{default_test_start_date[:4]}" style="width:60px;background:#eee;border:none;border-radius:4px;font-size:16px;margin-left:8px;">
            <span style="font-size:16px;">-</span>
            <input type="number" min="0" max="13" id="start_month" value="{pad(default_test_start_date[5:7])}" style="width:40px;background:#eee;border:none;border-radius:4px;font-size:16px;">
            <span style="font-size:16px;">-</span>
            <input type="number" min="0" max="32" id="start_day" value="{pad(default_test_start_date[8:10])}" style="width:40px;background:#eee;border:none;border-radius:4px;font-size:16px;">
            </span>
            <span style="font-size:13px;">
            <input type="number" min="-1" max="24" id="start_hour" value="{pad(default_day_start_time[:2])}" style="width:40px;background:#eee;border:none;border-radius:4px;font-size:16px;margin-left:8px;">
            <span style="font-size:16px;">:</span>
            <input type="number" min="-1" max="60" id="start_minute" value="{pad(default_day_start_time[3:5])}" style="width:40px;background:#eee;border:none;border-radius:4px;font-size:16px;">
            </span>
        </div>
        <div style="display:flex;align-items:center;gap:24px;margin-top:12px;">
            <span style="font-size:13px;">
            终末时间:
            <input type="number" min="1900" max="2100" id="end_year" value="{default_test_end_date[:4]}" style="width:60px;background:#eee;border:none;border-radius:4px;font-size:16px;margin-left:8px;">
            <span style="font-size:16px;">-</span>
            <input type="number" min="0" max="13" id="end_month" value="{pad(default_test_end_date[5:7])}" style="width:40px;background:#eee;border:none;border-radius:4px;font-size:16px;">
            <span style="font-size:16px;">-</span>
            <input type="number" min="0" max="32" id="end_day" value="{pad(default_test_end_date[8:10])}" style="width:40px;background:#eee;border:none;border-radius:4px;font-size:16px;">
            </span>
            <span style="font-size:13px;">
            <input type="number" min="-1" max="24" id="end_hour" value="{pad(default_day_end_time[:2])}" style="width:40px;background:#eee;border:none;border-radius:4px;font-size:16px;margin-left:8px;">
            <span style="font-size:16px;">:</span>
            <input type="number" min="-1" max="60" id="end_minute" value="{pad(default_day_end_time[3:5])}" style="width:40px;background:#eee;border:none;border-radius:4px;font-size:16px;">
            </span>
        </div>
        <div style="margin-top:16px;">
            <label style="font-size:13px;">
            <input type="checkbox" id="is_trading_day" style="width:16px;height:16px;vertical-align:middle;margin-right:8px;">
            <span style="font-size:13px;vertical-align:middle;">交易日</span>
            </label>
        </div>
        <div style="margin-top:5px;">
            <label style="font-size:13px;">
            <input type="checkbox" id="is_cn_futures_day" style="width:16px;height:16px;vertical-align:middle;margin-right:8px;">
            <span style="font-size:13px;vertical-align:middle;">中国期货日盘 (09:00-15:00)</span>
            </label>
            <label style="font-size:13px;margin-left:24px;">
            <input type="checkbox" id="is_cn_futures_night" style="width:16px;height:16px;vertical-align:middle;margin-right:8px;">
            <span style="font-size:13px;vertical-align:middle;">中国期货夜盘 (21:00-15:00)</span>
            </label>
        </div>
        <div style="margin-top:8px; color:#888;">
            <span style="font-size:13px;">当前设置：</span>
            <span id="current_settings" style="font-size:13px;"></span>
        </div>
        <div style="margin-top:8px; display: flex; align-items: baseline;">
            <button id="confirm_time_btn" type="button" style="background:#0078d4; color:#fff; border:none; border-radius:4px; padding:6px 18px; font-size:14px;" disabled>确定</button>
            <span id="confirm_time_status" style="margin-left:12px; color:#0078d4; font-size:13px;"></span>
        </div>
        <script>
            var default_start_date = "{default_test_start_date}";
            var default_end_date = "{default_test_end_date}";
            var default_day_start_time = "{default_day_start_time}";
            var default_day_end_time = "{default_day_end_time}";
            var default_cn_futures_day_start = "{default_cn_futures_day_start}";
            var default_cn_futures_day_end = "{default_cn_futures_day_end}";
            var default_cn_futures_night_start = "{default_cn_futures_night_start}";
            var default_cn_futures_night_end = "{default_cn_futures_night_end}";

            function pad(n) {{ n = parseInt(n); return n < 10 ? '0' + n : n.toString(); }}
            function getMaxDay(year, month) {{
                year = parseInt(year); month = parseInt(month);
                if (isNaN(year) || isNaN(month) || month < 1 || month > 12) return 31;
                return new Date(year, month, 0).getDate();
            }}
            function setTimeInputsDisabled(disabled) {{
                ['start_hour','start_minute','end_hour','end_minute'].forEach(function(id) {{
                    var el = document.getElementById(id);
                    el.disabled = disabled;
                    el.style.background = disabled ? '#ccc' : '#eee';
                    el.style.color = disabled ? '#888' : '';
                }});
            }}
            function updateCurrentSettings() {{
                var sy=document.getElementById('start_year').value, sm=pad(document.getElementById('start_month').value),
                    sd=pad(document.getElementById('start_day').value), sh=pad(document.getElementById('start_hour').value),
                    smin=pad(document.getElementById('start_minute').value);
                var ey=document.getElementById('end_year').value, em=pad(document.getElementById('end_month').value),
                    ed=pad(document.getElementById('end_day').value), eh=pad(document.getElementById('end_hour').value),
                    emin=pad(document.getElementById('end_minute').value);
                var is_trading_day = document.getElementById('is_trading_day').checked;
                document.getElementById('current_settings').innerText =
                    '起始时间: ' + sy+'-'+sm+'-'+sd+' '+sh+':'+smin +
                    ', 终末时间: ' + ey+'-'+em+'-'+ed+' '+eh+':'+emin +
                    (is_trading_day ? ' (交易日)' : '');
                var start_dt = new Date((sy+'-'+sm+'-'+sd+' '+sh+':'+smin).replace(/-/g,'/'));
                var end_dt = new Date((ey+'-'+em+'-'+ed+' '+eh+':'+emin).replace(/-/g,'/'));
                var isValid = !isNaN(start_dt.getTime()) && !isNaN(end_dt.getTime()) && start_dt <= end_dt;
                var confirmBtn = document.getElementById('confirm_time_btn');
                if (isValid) {{
                    confirmBtn.disabled = false;
                    confirmBtn.style.background = '#0078d4';
                    confirmBtn.style.cursor = 'pointer';
                    openModule('category_filter_module');
                }} else {{
                    confirmBtn.disabled = true;
                    confirmBtn.style.background = '#ccc';
                    confirmBtn.style.cursor = 'not-allowed';
                    closeModule('category_filter_module');
                }}
                var statusSpan = document.getElementById('confirm_time_status');
                if (!isValid) {{
                    statusSpan.innerText = '⚠️ 起始时间必须 ≤ 终末时间';
                    statusSpan.style.color = '#d40000';
                }} else {{
                    statusSpan.innerText = '点击确定按钮更新因子计算的时间范围';
                    statusSpan.style.color = '#888';
                }}
            }}
            function carryOver(thisId, thisMin, thisMax, lastId, prefix) {{
                var thisElem = document.getElementById(thisId);
                var lastElem = document.getElementById(lastId);
                var thisNum = parseInt(thisElem.value);
                var lastNum = parseInt(lastElem.value);

                if (isNaN(thisNum)) {{
                    thisElem.value = pad(thisMin);
                    return;
                }}
                else if (isNaN(lastNum)) {{
                    lastElem.value = pad(thisMin);
                    if (thisNum < thisMin) thisElem.value = pad(thisMin);
                    else if (thisNum > thisMax) thisElem.value = pad(thisMax);
                    else thisElem.value = pad(thisNum);
                    return;
                }}
                else if (thisNum === thisMin - 1) {{
                    lastElem.value = lastNum - 1;
                    if (thisId.endsWith('day')) {{
                        thisElem.value = pad(1);
                        adjustTime(lastId, prefix);
                        var newMonth = parseInt(document.getElementById(prefix + '_month').value);
                        var newYear = parseInt(document.getElementById(prefix + '_year').value);
                        var maxDay = getMaxDay(newYear, newMonth);
                        thisElem.value = pad(maxDay);
                    }} else thisElem.value = pad(thisMax);
                    adjustTime(lastId, prefix);
                    lastElem.value = pad(parseInt(lastElem.value))
                    return;
                }}
                else if (thisNum === thisMax + 1) {{
                    lastElem.value = pad(lastNum + 1);
                    thisElem.value = pad(thisMin);
                    adjustTime(lastId, prefix);
                    return;
                }} else if (thisNum > thisMax + 1) {{
                    thisElem.value = pad(thisMax);
                    return;
                }} else if (thisNum < thisMin - 1) {{
                    thisElem.value = pad(thisMin);
                    return;
                }} else {{
                    thisElem.value = pad(thisNum);
                    return;
                }}
            }}
            function adjustTime(id, prefix) {{
            
                var minuteId = prefix + '_minute'
                var hourId = prefix + '_hour'
                var dayId = prefix + '_day'
                var yearId = prefix + '_year'
                var monthId = prefix + '_month'

                var minuteElem = document.getElementById(minuteId);
                var minuteVal = parseInt(minuteElem.value);
                if (isNaN(minuteVal) || minuteVal > 59 || minuteVal < 0) {{
                    carryOver(minuteId, 0, 59, hourId, prefix);
                    return;
                }} else minuteElem.value = pad(minuteVal);

                var hourElem = document.getElementById(hourId);
                var hourVal = parseInt(hourElem.value);
                if (isNaN(hourVal) || hourVal > 23 || hourVal < 0) {{
                    carryOver(hourId, 0, 23, dayId, prefix);
                    return;
                }} else hourElem.value = pad(hourVal);
                
                var dayElem = document.getElementById(dayId);
                var yearElem = document.getElementById(yearId);
                var monthElem = document.getElementById(monthId);

                var year = parseInt(yearElem.value);
                var month = parseInt(monthElem.value);
                var dayVal = parseInt(dayElem.value);
                var maxDay = getMaxDay(year, month);

                if (id.endsWith('month') && dayVal > maxDay) {{
                    dayElem.value = pad(maxDay);
                }}

                if (isNaN(dayVal) || dayVal > maxDay || dayVal < 1) {{
                    carryOver(dayId, 1, maxDay, monthId, prefix);
                    return;
                }} else dayElem.value = pad(dayVal);

                if (isNaN(month) || month > 12 || month < 1) {{
                    carryOver(monthId, 1, 12, yearId, prefix);
                    return;
                }} else monthElem.value = pad(month);

                if (isNaN(year) || year < 1900 || year > 2100) {{
                    if (year < 1900) yearElem.value = '1900';
                    else yearElem.value = '2100';
                    return;
                }} else yearElem.value = pad(year);
            }}
            function toggleTradingDay() {{
                var is_trading_day = document.getElementById('is_trading_day').checked;
                if(is_trading_day) {{
                    document.getElementById('is_cn_futures_day').checked = false;
                    document.getElementById('is_cn_futures_night').checked = false;
                    document.getElementById('start_hour').value = "00";
                    document.getElementById('start_minute').value = "00";
                    document.getElementById('end_hour').value = "00";
                    document.getElementById('end_minute').value = "00";
                    setTimeInputsDisabled(true);
                }} else {{
                    document.getElementById('start_hour').value = pad(parseInt(default_day_start_time.split(':')[0]));
                    document.getElementById('start_minute').value = pad(parseInt(default_day_start_time.split(':')[1]));
                    document.getElementById('end_hour').value = pad(parseInt(default_day_end_time.split(':')[0]));
                    document.getElementById('end_minute').value = pad(parseInt(default_day_end_time.split(':')[1]));
                    setTimeInputsDisabled(false);
                }}
                updateCurrentSettings();
            }}
            function toggleCnFuturesDayNight(event) {{
                var target = event.target;
                var dayCheckbox = document.getElementById('is_cn_futures_day');
                var nightCheckbox = document.getElementById('is_cn_futures_night');
                var tradingDayElem = document.getElementById('is_trading_day');
                if (target === dayCheckbox && dayCheckbox.checked) nightCheckbox.checked = false;
                else if (target === nightCheckbox && nightCheckbox.checked) dayCheckbox.checked = false;
                if (dayCheckbox.checked || nightCheckbox.checked) tradingDayElem.checked = false;
                var is_day = dayCheckbox.checked, is_night = nightCheckbox.checked;
                if (is_day) {{
                    document.getElementById('start_hour').value = pad(parseInt(default_cn_futures_day_start.split(':')[0]));
                    document.getElementById('start_minute').value = pad(parseInt(default_cn_futures_day_start.split(':')[1]));
                    document.getElementById('end_hour').value = pad(parseInt(default_cn_futures_day_end.split(':')[0]));
                    document.getElementById('end_minute').value = pad(parseInt(default_cn_futures_day_end.split(':')[1]));
                    setTimeInputsDisabled(true);
                }} else if (is_night) {{
                    document.getElementById('start_hour').value = pad(parseInt(default_cn_futures_night_start.split(':')[0]));
                    document.getElementById('start_minute').value = pad(parseInt(default_cn_futures_night_start.split(':')[1]));
                    document.getElementById('end_hour').value = pad(parseInt(default_cn_futures_night_end.split(':')[0]));
                    document.getElementById('end_minute').value = pad(parseInt(default_cn_futures_night_end.split(':')[1]));
                    setTimeInputsDisabled(true);
                }} else {{
                    setTimeInputsDisabled(false);
                    document.getElementById('start_hour').value = pad(parseInt(default_day_start_time.split(':')[0]));
                    document.getElementById('start_minute').value = pad(parseInt(default_day_start_time.split(':')[1]));
                    document.getElementById('end_hour').value = pad(parseInt(default_day_end_time.split(':')[0]));
                    document.getElementById('end_minute').value = pad(parseInt(default_day_end_time.split(':')[1]));
                }}
                updateCurrentSettings();
            }}
            function confirmTimeRange() {{
                var startYear = document.getElementById('start_year').value;
                var startMonth = document.getElementById('start_month').value;
                var startDay = document.getElementById('start_day').value;
                var startHour = document.getElementById('start_hour').value;
                var startMinute = document.getElementById('start_minute').value;
                var endYear = document.getElementById('end_year').value;
                var endMonth = document.getElementById('end_month').value;
                var endDay = document.getElementById('end_day').value;
                var endHour = document.getElementById('end_hour').value;
                var endMinute = document.getElementById('end_minute').value;
                var isTradingDay = document.getElementById('is_trading_day').checked;
                var isDay = document.getElementById('is_cn_futures_day').checked;
                var isNight = document.getElementById('is_cn_futures_night').checked;

                var timeData = {{
                    factor_family_alias: '{factor_family_alias}',
                    start_date: startYear + '-' + startMonth + '-' + startDay,
                    start_time: startHour + ':' + startMinute,
                    end_date: endYear + '-' + endMonth + '-' + endDay,
                    end_time: endHour + ':' + endMinute,
                    is_trading_day: isTradingDay,
                    is_cn_futures_day: isDay,
                    is_cn_futures_night: isNight
                }};

                var statusSpan = document.getElementById('confirm_time_status');
                statusSpan.innerText = '保存中...';
                statusSpan.style.color = '#0078d4';

                fetch('/set_time_range', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(timeData)
                }})
                .then(response => response.json())
                .then(data => {{
                    if (data.success) {{
                        var statusSpan = document.getElementById('confirm_time_status');
                        if (data.change_factor_tester) {{
                            statusSpan.innerText = '✓ 已保存，因子起始计算时间更新为: ' + data.start_calc_param_val + '，正在更新因子测试中...';
                            statusSpan.style.color = '#0078d4';
                            setTimeout(function() {{
                                statusSpan.innerText = '✓ 已保存，因子起始计算时间更新为: ' + data.start_calc_param_val + '，因子测试已更新';
                                statusSpan.style.color = '#0078d4';

                            }}, 2000);
                        }} else {{
                            statusSpan.innerText = '✓ 已保存，因子起始计算时间更新为: ' + data.start_calc_param_val;
                            statusSpan.style.color = '#0078d4';
                        }}
                    if (data.show_next) {{
                        openModule('category_filter_module');
                    }}
                    }} else {{
                    statusSpan.innerText = '保存失败: ' + (data.error || '未知错误');
                    statusSpan.style.color = '#d40000';
                    }}
                }})
                .catch(err => {{
                    console.error('请求出错', err);
                    statusSpan.innerText = '网络错误';
                    statusSpan.style.color = '#d40000';
                }});
            }}
            document.addEventListener('DOMContentLoaded', function() {{
                document.getElementById('is_trading_day').addEventListener('change', toggleTradingDay);
                document.getElementById('is_cn_futures_day').addEventListener('change', toggleCnFuturesDayNight);
                document.getElementById('is_cn_futures_night').addEventListener('change', toggleCnFuturesDayNight);
                var inputs = [
                    ['start_year',1900,2100,false,'',''],['start_month',1,12,false,'',''],
                    ['start_day',1,31,true,'start_year','start_month'],
                    ['start_hour',0,23,false,'',''],['start_minute',0,59,false,'',''],
                    ['end_year',1900,2100,false,'',''],['end_month',1,12,false,'',''],
                    ['end_day',1,31,true,'end_year','end_month'],
                    ['end_hour',0,23,false,'',''],['end_minute',0,59,false,'','']
                ];
                inputs.forEach(function(arr) {{
                    var id=arr[0],min=arr[1],max=arr[2],isDay=arr[3],yearId=arr[4],monthId=arr[5];
                    var elem = document.getElementById(id);
                    elem.addEventListener('blur', function() {{
                        if (id.startsWith('start')) adjustTime(id, 'start');
                        if (id.startsWith('end')) adjustTime(id, 'end');
                        updateCurrentSettings();
                    }});
                    elem.addEventListener('keydown', function(e) {{
                        if(e.key==='Enter') {{
                            if (id.startsWith('start')) adjustTime(id, 'start');
                            if (id.startsWith('end')) adjustTime(id, 'end');
                            updateCurrentSettings();
                        }}
                    }});
                    elem.addEventListener('input', function() {{
                        if (id.startsWith('start')) adjustTime(id, 'start');
                        if (id.startsWith('end')) adjustTime(id, 'end');
                        updateCurrentSettings();
                    }});
                }});
                toggleTradingDay();
                updateCurrentSettings();
                {show_next}
                document.getElementById('confirm_time_btn').addEventListener('click', confirmTimeRange);
            }});
        </script>
        </div>
        """
    
@app.route('/set_time_range', methods=['POST'])
def set_time_range():
    data = request.get_json()
    try:
        factor_family_alias = data['factor_family_alias']
        ff = get_factor_family_instance(factor_family_alias)
        start_date = data['start_date']
        start_time = data['start_time']
        end_date = data['end_date']
        end_time = data['end_time']
        is_trading_day = data.get('is_trading_day', False)
        is_cn_futures_day = data.get('is_cn_futures_day', False)
        is_cn_futures_night = data.get('is_cn_futures_night', False)

        # 这里可以添加对时间格式的验证
        global default_test_start_date, default_test_end_date, default_day_start_time, default_day_end_time
        default_test_start_date = start_date
        default_test_end_date = end_date
        default_day_start_time = start_time
        default_day_end_time = end_time

        if is_trading_day:
            start_calc_param_val = ('1d', start_date)
        else:
            start_calc_param_val = ('1min', f"{start_date} {start_time}")
        factors = ff.get_factors(start_calc_time=start_calc_param_val)
        start_calc_param_val = list(set([StartCalcParam.get_value(factor) for factor in factors]))
        assert len(start_calc_param_val) == 1
        start_calc_param_val = f"{StartCalcParam.name} = {start_calc_param_val[0]}"

        if factor_testers:
            from Factor import FactorTester
            for tester in factor_testers:
                assert isinstance(tester, FactorTester)
                tester.update_time_range((f"{start_date} {start_time}", f"{end_date} {end_time}"))

        # 可以根据是否是交易日等设置调整默认的时间范围
        show_next = (start_date <= end_date)

        return jsonify({
            'success': True, 
            'show_next': show_next, 
            'start_calc_param_val': start_calc_param_val, 
            'change_factor_tester': bool(factor_testers)
            })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

def convert_to_fancytree(tree_dict):
    """
    将原始分类树转换为 Fancytree 格式
    :param tree_dict: 原始树字典（如 get\\_cat\\_tree().tree）
    :return: Fancytree 节点列表
    """
    def create_node(key, value, path):
        """为单个分类键创建节点，并递归构建其子节点"""
        # 获取安全的字符串键名
        key_str = str(key) if not isinstance(key, type) else key.__name__
        current_path = f"{path}/{key_str}" if path else key_str

        # 收集子分类节点
        child_nodes = []

        # 处理 $SUBCLASS$ 中的内容
        if isinstance(value, dict) and "$SUBCLASS$" in value:
            sub_dict = value["$SUBCLASS$"]
            if isinstance(sub_dict, dict):
                for subkey, subval in sorted(sub_dict.items(), key=lambda x: str(x[0]) if not isinstance(x[0], type) else x[0].__name__):
                    if subkey not in ("$SUBCLASS$", "$OBJECTS$"):
                        child_nodes.append(create_node(subkey, subval, current_path))

        # 处理其他直接键（排除 $SUBCLASS$ 和 $OBJECTS$）
        # 为了避免重复，可以收集已处理过的键
        processed_keys = set()
        if isinstance(value, dict) and "$SUBCLASS$" in value and isinstance(value["$SUBCLASS$"], dict):
            processed_keys.update(value["$SUBCLASS$"].keys())

        if isinstance(value, dict):
            for k, v in sorted(value.items(), key=lambda x: str(x[0]) if not isinstance(x[0], type) else x[0].__name__):
                if k in ("$SUBCLASS$", "$OBJECTS$") or k in processed_keys:
                    continue
                child_nodes.append(create_node(k, v, current_path))

        # 检查是否有产品
        has_objects = isinstance(value, dict) and "$OBJECTS$" in value and bool(value["$OBJECTS$"])
        has_subclass = isinstance(value, dict) and "$SUBCLASS$" in value and bool(value["$SUBCLASS$"])

        # 构建当前节点
        node = {
            "title": key_str,
            "key": current_path,
            "checkbox": True,
        }

        if child_nodes:
            # 有子分类：文件夹，静态加载
            node["folder"] = True
            node["lazy"] = False
            node["children"] = child_nodes
            # 判断是否应默认展开：有子分类且没有产品
            if not has_objects or has_subclass:
                node["expanded"] = True
            # 如果同时有产品，添加一个“产品列表”子文件夹（懒加载）
            if has_objects:
                node["desc"] = f"{len(value['$OBJECTS$'])} 个产品"
                product_folder = {
                    "title": "Product Lists",
                    "key": current_path + "/_products",
                    "folder": True,
                    "lazy": True,
                    "checkbox": False,   # 产品文件夹本身不可勾选
                }
                node["children"].insert(0, product_folder)
            else:
                node['checkbox'] = False
        elif has_objects:
            # 没有子分类但有产品：节点本身懒加载产品
            node["folder"] = True
            node["lazy"] = True
            node["desc"] = f"{len(value['$OBJECTS$'])} 个产品"
        else:
            # 既无子分类也无产品：叶子节点
            node["folder"] = False
            node["lazy"] = False

        return node

    # 处理顶层节点（排除特殊键）
    top_nodes = []
    for key, value in sorted(tree_dict.items(), key=lambda x: str(x[0]) if not isinstance(x[0], type) else x[0].__name__):
        if key not in ("$SUBCLASS$", "$OBJECTS$"):
            top_nodes.append(create_node(key, value, ""))
    return top_nodes

tree = get_cat_tree().tree

# 新增 API 端点
@app.route('/api/tree-data')
def get_tree_data():
    fancytree_data = convert_to_fancytree(tree)
    return jsonify(fancytree_data)

def find_node_by_path(tree_dict, path_parts):
    """
    在树字典中根据路径部分查找节点。
    :param tree_dict: 当前层级的字典（可以是根或子节点）
    :param path_parts: 路径部分列表，例如 ['Products', 'Product', 'Futures', 'CNFutures', '日夜盘', '夜盘1']
    :return: 找到的节点字典，若未找到返回 None
    """

    flag = False
    original_path_parts = path_parts.copy()
    if len(path_parts) >= 2 and path_parts[-2] == '_products':
        path_parts = path_parts[:-2]
        flag = True

    current = tree_dict
    for part in path_parts:
        found = None
        # 先在当前节点的直接键中查找
        for key, value in current.items():
            key_str = str(key) if not isinstance(key, type) else key.__name__
            if key_str == part:
                if isinstance(value, dict):
                    current = value
                    found = True
                    break
                else:
                    # 路径指向非字典，无法继续
                    return None
        if found:
            continue

        # 如果直接键中没找到，检查 $SUBCLASS$ 内部
        if '$SUBCLASS$' in current and isinstance(current['$SUBCLASS$'], dict):
            subclass_dict = current['$SUBCLASS$']
            for key, value in subclass_dict.items():
                key_str = str(key) if not isinstance(key, type) else key.__name__
                if key_str == part:
                    if isinstance(value, dict):
                        current = value
                        found = True
                        break
                    else:
                        return None
        if not found:
            return None
        
    if flag:
        assert '$OBJECTS$' in current and isinstance(current['$OBJECTS$'], list), f"路径 {original_path_parts} 指向的节点没有 $OBJECTS$ 列表"
        current = current['$OBJECTS$']
        for obj in current:
            if obj.name == original_path_parts[-1]:
                return obj
        return None

    return current

@app.route('/get_products')
def get_products():
    original_path = request.args.get('path')  # 例如 "Products/Product/Futures/CNFutures/日夜盘/夜盘1/_products"
    if not original_path:
        return jsonify([])

    # 判断是否为产品文件夹请求（路径以 /_products 结尾）
    if original_path.endswith('/_products'):
        node_path = original_path[:-10]  # 去掉 /_products，得到分类路径
    else:
        node_path = original_path

    parts = node_path.split('/')
    node = find_node_by_path(tree, parts)
    if node is None:
        return jsonify([])  # 节点不存在

    # 获取产品列表
    objects = node.get('$OBJECTS$', []) if isinstance(node, dict) else [node]
    objects = sorted(objects, key=lambda x: getattr(x, 'name', str(x)))  # 按 name 属性排序，如果没有则按字符串表示排序

    # 转换为 Fancytree 子节点格式
    child_nodes = []
    for prod in objects:
        # 假设 prod 对象有 id 和 name 属性，如果没有则适当处理
        prod_id = getattr(prod, 'id', str(prod))
        prod_name = getattr(prod, 'name', str(prod))
        prod_desc = getattr(prod, 'desc', '')  # 获取描述
        child_nodes.append({
            "title": prod_name,
            "key": f"{original_path}/{prod_id}",  # 使用原始路径保证唯一性
            "checkbox": True,
            "folder": False,
            "lazy": False,
            "extraClasses": "product-node",  # 可选样式
            "desc": prod_desc,  # 将描述添加到节点数据中
        })
    return jsonify(child_nodes)

def get_minimal_paths(paths):
    """
    从路径列表中返回最小集合，使得没有路径是另一个路径的前缀。
    同时，过滤掉以 '/_products' 结尾的路径（视为中间文件夹）。
    """
    # 第一步：过滤掉以 '/_products' 结尾的路径
    filtered = [p for p in paths if not p.endswith('/_products')]
    # 第二步：按长度排序，短的在前
    filtered.sort(key=len)
    result = []
    for p in filtered:
        # 检查 p 是否被 result 中某个路径作为前缀
        if not any(p.startswith(r + '/') or p == r for r in result):
            result.append(p)
    return result

@app.route('/submit_selected_products', methods=['POST'])
def submit_selected_products():
    data = request.get_json()
    selected_paths = data.get('selected_paths', [])
    id_time = data.get('id_time', None)  # 可选的时间戳参数，用于记录提交时间
    id_time = str(id_time) if id_time is not None else None
    try:
        assert selected_paths, "未选择任何产品路径"
        global factor_testers
        selected_products = []
        selected_paths = get_minimal_paths(selected_paths)
        for path in selected_paths:
            parts = path.split('/')
            node = find_node_by_path(tree, parts)
            if isinstance(node, dict) and '$OBJECTS$' in node and isinstance(node['$OBJECTS$'], list):
                selected_products.extend(node['$OBJECTS$'])
            else:
                selected_products.append(node)
        selected_products = sorted(list(set(selected_products)))
        from Factor import FactorTester
        factor_tester = FactorTester(products=selected_products, alias=id_time, time_range=(default_test_start_date, default_test_end_date))
        factor_testers.append(factor_tester)
        return jsonify({
            'success': True, 
            'count': len(selected_products), 
            'count_paths': len(selected_paths), 
            'selected_products': [str(p) for p in selected_products], 
            'selected_paths': selected_paths,
            'factor_tester_name': factor_tester.name,
            'factor_tester_serial': 'FT@' + str(factor_tester.serial_number),
            'count_desc': f"{len(selected_products)} 个产品"
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    
@app.route('/reorder_submissions', methods=['POST'])
def reorder_submissions():
    data = request.get_json()
    new_order = data.get('new_order', [])
    try:
        global factor_testers
        len_factor_testers = len(factor_testers)
        id_to_tester = {int(tester.alias): tester for tester in factor_testers}
        factor_testers = [id_to_tester[id_time] for id_time in new_order if id_time in id_to_tester]
        assert len(factor_testers) == len_factor_testers, "Reordered list length mismatch"
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    
@app.route('/delete_submission', methods=['POST'])
def delete_submission():
    data = request.get_json()
    id_time = data.get('id_time', None)
    try:
        global factor_testers
        len_before = len(factor_testers)
        factor_tester = next((t for t in factor_testers if t.alias == str(id_time)), None)
        assert factor_tester is not None, "Submission not found"
        factor_tester.delete()  # 调用实例的删除方法以释放资源
        factor_testers = [tester for tester in factor_testers if tester.alias != str(id_time)]
        assert len(factor_testers) == len_before - 1, "No submission deleted"
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    
@app.route('/delete_path_of_submission', methods=['POST'])
def delete_path_of_submission():
    data = request.get_json()
    id_time = data.get('id_time', None)
    new_paths = data.get('new_paths', None)
    try:
        global factor_testers
        tester = next((t for t in factor_testers if t.alias == str(id_time)), None)
        assert tester is not None, "Submission not found"
        selected_products = []
        selected_paths = get_minimal_paths(new_paths)
        for path in selected_paths:
            parts = path.split('/')
            node = find_node_by_path(tree, parts)
            if isinstance(node, dict) and '$OBJECTS$' in node and isinstance(node['$OBJECTS$'], list):
                selected_products.extend(node['$OBJECTS$'])
            else:
                selected_products.append(node)
        selected_products = sorted(list(set(selected_products)))
        tester.products = selected_products
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

def get_category_filter_module_html():
    resources = '''
    <!-- Fancytree 资源 -->
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/jquery.fancytree/2.38.2/skin-win8/ui.fancytree.min.css">
    <!-- Font Awesome 用于图标（可选） -->
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <!-- SortableJS 用于拖动排序 -->
    <script src="https://cdn.jsdelivr.net/npm/sortablejs@latest/Sortable.min.js"></script>
    <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/jquery.fancytree/2.38.2/jquery.fancytree-all-deps.min.js"></script>
    '''
    
    html = resources + '''
    <div class="module" id="category_filter_module" style="margin-top:24px;">
        <div style="display: flex; gap: 20px;">
            <!-- 左侧树 -->
            <div style="flex: 1; min-width: 0;">
                <div class="section-title" style="font-size:15px;">2. 产品类别筛选</div>
                <div style="margin-bottom:0px;color:#888;font-size:12px;">树状结构，勾选后提交</div>
                <div style="display: flex; align-items: baseline; margin-top: 8px; margin-bottom: 8px;">
                    <button type="button" id="submit-selected2" style="background:#0078d4;color:#fff;border:none;border-radius:4px;padding:3px 10px;font-size:13px;height:24px;">提交选中产品</button>
                    <div id="submit_status2" style="margin-left: 10px; color:#0078d4; font-size:12px;"></div>
                </div>
                <div id="tree-container" style="max-height: 300px; overflow-y: auto;"></div>
                <div style="display: flex; align-items: baseline; margin-top: 8px;">
                    <button type="button" id="submit-selected" style="background:#0078d4;color:#fff;border:none;border-radius:4px;padding:3px 10px;font-size:13px;height:24px;">提交选中产品</button>
                    <div id="submit_status" style="margin-left: 10px; color:#0078d4; font-size:12px;"></div>
                </div>
            </div>
            <!-- 右侧历史提交记录 -->
            <div style="width: 400px; border-left: 1px solid #ddd; padding-left: 16px;">
                <div style="font-size:14px; font-weight:bold; margin-bottom:10px;">已提交的路径列表</div>
                <div style="display: flex; align-items: baseline; margin-bottom: 8px; font-size:12px;">
                    <div style="color:#888;">拖动提交记录可调整顺序</div>
                    &nbsp;&nbsp;
                    <div id="submission_change_status"></div>
                </div>
                <div id="submission-history" style="max-height: 300px; overflow-y: auto;"></div>
            </div>
        </div>
    </div>
    '''
    
    js = '''
    <script>
    var submissions = [];        // 存储所有提交记录
    var expandedState = {};      // 记录每个提交中路径的展开状态
    var treeInstance = null;     // 用于存储树实例（可选方式）

    $(function() {
        // 初始化 Fancytree
        $("#tree-container").fancytree({
            source: {
                url: "/api/tree-data"
            },
            checkbox: true,
            selectMode: 3,
            // 在初始化完成后触发
            init: function(event, data) {
                treeInstance = data.tree; // ✅ 这才是真正的 Fancytree 实例
            },
            lazyLoad: function(event, data) {
                var node = data.node;
                data.result = {
                    url: "/get_products",
                    data: { path: node.key }
                };
            },
            renderNode: function(event, data) {
                var node = data.node;
                var desc = node.data.desc;
                if (desc) {
                    var $title = $(node.span).find('.fancytree-title');
                    $title.siblings('.node-description').remove();
                    $title.after('<span class="node-description" style="color:#888; margin-left:8px; font-size:12px;">' + desc + '</span>');
                }
            }
        });

        $("#submit-selected").click(submitSelectedProducts);
        $("#submit-selected2").click(submitSelectedProducts);

        // 初始化 SortableJS 实现拖动排序
        var historyContainer = document.getElementById('submission-history');
        new Sortable(historyContainer, {
            animation: 150,
            handle: '.submission-header',  // 通过头部拖动
            onEnd: function(evt) {
                fetch('/reorder_submissions', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ new_order: submissions.map(sub => sub.id) })
                })
                .then(r => r.json())
                .then(data => {
                    var statusElem = document.getElementById('submission_change_status');
                    if (data.success) {
                        statusElem.innerText = '✓ 顺序已更新';
                        statusElem.style.color = '#28a745';

                        // 拖动结束后，重新排序 submissions 数组
                        var oldIndex = evt.oldIndex;
                        var newIndex = evt.newIndex;
                        if (oldIndex !== newIndex) {
                            // 移动数组元素
                            var movedItem = submissions.splice(oldIndex, 1)[0];
                            submissions.splice(newIndex, 0, movedItem);
                            // 重新渲染右侧历史
                            renderHistory();
                            renderICTabs(submissions);  // 新增
                        }

                        setTimeout(function() {
                            statusElem.innerText = '';
                        }, 3000);
                        
                    } else {
                        statusElem.innerText = '✗ 重新排序提交失败: ' + data.error;
                        statusElem.style.color = '#d40000';
                    }
                });
            }
        });

        // 提交按钮点击事件
        function submitSelectedProducts() {
            if (!treeInstance) {
                console.error("树尚未初始化完成");
                return;
            }
            var selectedNodes = treeInstance.getSelectedNodes(); // 现在可以正常使用
            var selectedPaths = selectedNodes.map(function(node) {
                return node.key;
            });
            var pathToDescMap = {};
            selectedNodes.forEach(function(node) {
                pathToDescMap[node.key] = node.data.desc || "";
            });

            var timestamp = new Date()
            var id_time = timestamp.getTime();
            var timeStr = timestamp.toLocaleTimeString();

            fetch('/submit_selected_products', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    selected_paths: selectedPaths,
                    id_time: id_time
                })
            })
            .then(r => r.json())
            .then(data => {
                var status1 = document.getElementById('submit_status');
                var status2 = document.getElementById('submit_status2');
                var msg;
                if (data.success) {
                    msg = '✓ 已提交，产品数量: ' + data.count + ', 路径数量: ' + data.count_paths;
                    status1.style.color = '#28a745';
                    status2.style.color = '#28a745';
                    // 取消所有节点的勾选：通过取消根节点选中，联动清除所有子节点选中状态
                    treeInstance.getRootNode().children.forEach(function(topNode) {
                        topNode.setSelected(false);
                    });
                } else {
                    msg = '提交失败: ' + (data.error || '未知错误');
                    status1.style.color = '#d40000';
                    status2.style.color = '#d40000';
                }
                if (status1) status1.innerText = msg;
                if (status2) status2.innerText = msg;

                // 将本次提交添加到历史记录
                if (data.selected_paths && data.selected_paths.length > 0) {
                    var newSubmission = {
                        id: id_time,  // 简单唯一ID
                        paths: data.selected_paths.slice(),  // 深拷贝
                        pathsDescMap: pathToDescMap,  // 路径到描述的映射
                        factor_tester_name: data.factor_tester_name,
                        factor_tester_serial: data.factor_tester_serial,
                        count_desc: data.count_desc,
                        timestamp: timeStr,
                    };
                    submissions.push(newSubmission);
                    renderHistory();
                    renderICTabs(submissions);  // 新增
                }
            });
        }

        // 渲染右侧历史区域
        function renderHistory() {
            var html = '';
            submissions.forEach(function(sub, index) {
                var isExpanded = expandedState[index] || {};  // 当前提交的展开状态对象
                html += '<div class="submission-item" data-index="' + index + '" style="border:1px solid #ccc; border-radius:4px; margin-bottom:12px; background:#f9f9f9;">';
                html += '  <div class="submission-header" style="background:#e9e9e9; padding:5px 10px; cursor:move; display:flex; justify-content:space-between; font-size:13px;">';
                html += '    <span><i class="fas fa-grip-vertical" style="margin-right:5px;"></i>序号 ' + (index+1) + ' : ' + sub.factor_tester_serial + ' (' + sub.timestamp + ')' + (sub.count_desc ? ' <span style="color:#d00;font-size:12px;">' + sub.count_desc + '</span>' : '') + '</span>';
                html += '    <button class="delete-submission" data-index="' + index + '" style="background:transparent; border:none; color:#d00; cursor:pointer; margin-top:0; padding:0 0; margin-right:0px; margin-left:auto"><i class="fas fa-trash"></i></button>';
                html += '  </div>';
                html += '  <div style="padding:2px;">';
                html += '    <table style="width:100%; border-collapse:collapse;">';
                sub.paths.forEach(function(path, pathIdx) {
                    var rowId = 'path-' + index + '-' + pathIdx;
                    var expanded = isExpanded[path] || false;  // 该路径是否展开
                    html += '      <tr class="path-row" data-path="' + path + '" data-sub-index="' + index + '" data-path-index="' + pathIdx + '">';
                    html += '        <td style="padding:0 0; border-bottom:1px solid #eee;">';
                    html += '          <div style="display:flex;align-items:center;">';
                    html += '            <span class="path-text" style="cursor:pointer; font-size:13px; margin-left:6px">' + path + (sub.pathsDescMap[path] ? ' <span style="color:#888;font-size:12px;">' + sub.pathsDescMap[path] + '</span>' : '') + '</span>';
                    html += '            <button class="delete-path" data-sub-index="' + index + '" data-path-index="' + pathIdx + '" style="margin-left:auto;background:transparent; border:none; color:#d00; cursor:pointer; margin-top:auto; padding:0 0; margin-right:10px; "><i class="fas fa-times"></i></button>';
                    html += '          </div>';
                    html += '        </td>';
                    html += '      </tr>';
                    if (expanded) {
                        // 如果展开，添加产品详情行（内容稍后通过 AJAX 加载）
                        html += '      <tr class="product-detail-row" id="detail-' + index + '-' + pathIdx + '">';
                        html += '        <td style="padding:8px 0 8px 20px; background:#f0f0f0;">';
                        html += '          <div class="loading-products" style="font-size:13px;">加载中...</div>';
                        html += '        </td>';
                        html += '      </tr>';
                    }
                });
                html += '    </table>';
                html += '  </div>';
                html += '</div>';
            });
            $('#submission-history').html(html);

            // 绑定事件：点击路径展开/折叠
            $('.path-text').click(function() {
                var $row = $(this).closest('tr.path-row');
                var subIndex = $row.data('sub-index');
                var path = $row.data('path');
                var pathIndex = $row.data('path-index');
                var expanded = expandedState[subIndex] || {};
                if (expanded[path]) {
                    // 折叠：移除详情行
                    $('#detail-' + subIndex + '-' + pathIndex).remove();
                    delete expanded[path];
                } else {
                    // 展开：加载产品详情
                    expanded[path] = true;
                    // 在行后插入详情行（使用 after）
                    var detailHtml = '<tr class="product-detail-row" id="detail-' + subIndex + '-' + pathIndex + '">' +
                                        '<td style="padding:8px 0 8px 20px; background:#f0f0f0;">' +
                                        '<div class="loading-products" style="font-size:13px;">加载中...</div>' +
                                        '</td></tr>';
                    $row.after(detailHtml);
                    // 加载产品数据
                    loadProductsForPath(path, subIndex, pathIndex);
                }
                expandedState[subIndex] = expanded;
            });

            // 绑定删除路径按钮
            $('.delete-path').click(function() {
                fetch('/delete_path_of_submission', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        id_time: submissions[$(this).data('sub-index')].id,
                        new_paths: submissions[$(this).data('sub-index')].paths.filter((_, idx) => idx !== $(this).data('path-index'))
                    })
                })
                .then(r => r.json())
                .then(data => {
                    var statusElem = document.getElementById('submission_change_status');
                    if (data.success) {
                        statusElem.innerText = '✓ 路径已删除';
                        statusElem.style.color = '#28a745';
                        // 本地更新提交记录
                        var subIndex = $(this).data('sub-index');
                        var pathIndex = $(this).data('path-index');
                        submissions[subIndex].paths.splice(pathIndex, 1);
                        setTimeout(function() {
                            statusElem.innerText = '';
                        }, 3000);
                        // 如果该提交没有路径了，删除整个提交
                        if (submissions[subIndex].paths.length === 0) {
                            fetch('/delete_submission', {
                                method: 'POST',
                                headers: {'Content-Type': 'application/json'},
                                body: JSON.stringify({ id_time: submissions[subIndex].id })
                            })
                            .then(r => r.json())
                            .then(data => {
                                if (data.success) {
                                    statusElem.innerText = '✓ 路径和提交已删除';
                                    statusElem.style.color = '#28a745';
                                    submissions.splice(subIndex, 1);
                                    setTimeout(function() {
                                        statusElem.innerText = '';
                                    }, 5000);
                                    renderHistory();  // 重新渲染
                                    renderICTabs(submissions);  // 新增
                                } else {
                                    statusElem.innerText = '✗ 路径已删除，但提交删除失败: ' + data.error;
                                    statusElem.style.color = '#d40000';
                                }
                            });
                        }
                        // 清理展开状态（可简化：重新渲染会丢失展开，但这里重新渲染）
                        renderHistory();  // 重新渲染
                        renderICTabs(submissions);  // 新增
                    } else {
                        statusElem.innerText = '✗ 删除路径失败: ' + data.error;
                        statusElem.style.color = '#d40000';
                    }
                });
            });

            // 绑定删除整个提交按钮
            $('.delete-submission').click(function() {

                fetch('/delete_submission', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ id_time: submissions[$(this).data('index')].id })
                })
                .then(r => r.json())
                .then(data => {
                    var statusElem = document.getElementById('submission_change_status');
                    if (data.success) {
                        statusElem.innerText = '✓ 提交已删除';
                        statusElem.style.color = '#28a745';

                        var index = $(this).data('index');
                        submissions.splice(index, 1);
                        renderHistory();
                        renderICTabs(submissions);  // 新增

                        setTimeout(function() {
                            statusElem.innerText = '';
                        }, 3000); 
                    } else {
                        statusElem.innerText = '✗ 删除提交失败: ' + data.error;
                        statusElem.style.color = '#d40000';
                    }
                });
            
            });
        }

        // 加载指定路径的产品详情
        function loadProductsForPath(path, subIndex, pathIndex) {
            var $detailCell = $('#detail-' + subIndex + '-' + pathIndex + ' td');
            $.get('/get_products', { path: path })
                .done(function(data) {
                    if (data && data.length) {
                        var html = '<div style="font-size:13px;">';
                        data.forEach(function(prod) {
                            html += `<div>${prod.title} <span style="color:#888;">${prod.desc}</span></div>`;
                        });
                        html += '</div>';
                        $detailCell.html(html);
                    } else {
                        $detailCell.html('<span style="color:#888;font-size:13px;">无产品</span>');
                    }
                })
                .fail(function() {
                    $detailCell.html('<span style="color:#d00;font-size:13px;">加载失败</span>');
                });
        }
    });
    </script>
    '''
    return html + js

def get_ic_test_module_html(factor_family_alias):
    return f'''
    <div class="module" id="ic_test_module" style="margin-top:32px;">
        <div class="section-title">3. IC测试</div>
        <div id="ic-tab-container">
            <!-- 选项卡和面板将由 JavaScript 动态生成 -->
        </div>
    </div>

    <style>
        .ic-card {{
            margin-top: 14px;
            border: 1px solid #e8edf3;
            border-radius: 10px;
            background: #fff;
            box-shadow: 0 2px 10px rgba(0,0,0,0.04);
            padding: 12px;
        }}
        .ic-status {{
            margin-left: 12px;
            font-size: 13px;
        }}
        .ic-table-wrap {{
            margin-top: 12px;
            border: 1px solid #e8edf3;
            border-radius: 10px;
            overflow: auto;
            max-height: 420px;
            background: #fff;
        }}
        .ic-table {{
            width: 100%;
            border-collapse: separate;
            border-spacing: 0;
            font-size: 13px;
            color: #1f2937;
        }}
        .ic-table thead th {{
            position: sticky;
            top: 0;
            z-index: 2;
            background: #f7fbff;
            color: #0f4c81;
            font-weight: 600;
            border-bottom: 1px solid #dbe7f3;
            padding: 10px 12px;
            white-space: nowrap;
        }}
        .ic-table tbody td {{
            border-bottom: 1px solid #eef2f7;
            padding: 8px 12px;
            white-space: nowrap;
        }}
        .ic-table tbody tr:nth-child(even) {{
            background: #fcfdff;
        }}
        .ic-table tbody tr:hover {{
            background: #eef7ff;
        }}
        .ic-table .idx-col {{
            position: sticky;
            left: 0;
            background: inherit;
            z-index: 1;
            font-weight: 600;
            color: #334155;
        }}
        .ic-empty {{
            margin-top: 12px;
            color: #888;
            padding: 10px;
            border: 1px dashed #d3dbe6;
            border-radius: 8px;
            background: #fafcff;
        }}
    </style>

    <script src="https://cdnjs.cloudflare.com/ajax/libs/highcharts/11.4.8/highstock.min.js"></script>
    <script>
    (function() {{
        function isBootstrapCSSLoaded() {{
            var links = document.querySelectorAll('link[rel="stylesheet"]');
            for (var i = 0; i < links.length; i++) {{
                if (links[i].href.includes('bootstrap.min.css')) return true;
            }}
            return false;
        }}
        function isBootstrapJSLoaded() {{
            return typeof window.bootstrap !== 'undefined';
        }}
        if (!isBootstrapCSSLoaded()) {{
            var link = document.createElement('link');
            link.rel = 'stylesheet';
            link.href = 'https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css';
            document.head.appendChild(link);
        }}
        if (!isBootstrapJSLoaded()) {{
            var script = document.createElement('script');
            script.src = 'https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js';
            document.body.appendChild(script);
        }}
    }})();

    function fmtCell(v) {{
        if (v === null || v === undefined || v === '') return '—';
        if (typeof v === 'number') return Number.isInteger(v) ? v : v.toFixed(6);
        return String(v);
    }}

    function buildPrettyTable(data) {{
        if (!data || !data.columns || !data.rows || !data.columns.length) {{
            return '<div class="ic-empty">无可展示结果</div>';
        }}
        var html = '<div class="ic-table-wrap"><table class="ic-table"><thead><tr>';
        data.columns.forEach(function(col, i) {{
            html += '<th class="' + (i === 0 ? 'idx-col' : '') + '">' + col + '</th>';
        }});
        html += '</tr></thead><tbody>';

        data.rows.forEach(function(row) {{
            html += '<tr>';
            data.columns.forEach(function(col, i) {{
                html += '<td class="' + (i === 0 ? 'idx-col' : '') + '">' + fmtCell(row[col]) + '</td>';
            }});
            html += '</tr>';
        }});

        html += '</tbody></table></div>';
        return html;
    }}

    window.renderICTabs = function(submissions) {{
        var container = document.getElementById('ic-tab-container');
        if (!container) return;
        if (!submissions || submissions.length === 0) {{
            container.innerHTML = '<div style="color:#888; padding:8px; border:1px dashed #ccc; border-radius:4px;">暂无测试器，请先添加测试器。</div>';
            return;
        }}

        var tabsHtml = '<ul class="nav nav-tabs" id="icTab" role="tablist">';
        var panelsHtml = '<div class="tab-content" id="icTabContent">';

        submissions.forEach(function(sub, idx) {{
            var activeClass = idx === 0 ? 'active' : '';
            var showClass = idx === 0 ? 'show active' : '';
            var tabId = 'ic-tab-' + sub.id;
            var panelId = 'ic-panel-' + sub.id;

            tabsHtml += `
                <li class="nav-item" role="presentation">
                    <button style="font-size:12px;" class="nav-link ${{activeClass}}" id="${{tabId}}" data-bs-toggle="tab" data-bs-target="#${{panelId}}" type="button" role="tab" aria-controls="${{panelId}}" aria-selected="${{idx === 0}}">
                        ${{sub.factor_tester_serial || ('测试器' + (idx + 1))}}
                    </button>
                </li>
            `;

            panelsHtml += `
                <div class="tab-pane fade ${{showClass}}" id="${{panelId}}" role="tabpanel" aria-labelledby="${{tabId}}">
                    <div class="ic-card">
                        <button class="btn btn-primary btn-sm" id="run-ic-btn-${{sub.id}}" onclick="runIC('${{sub.id}}')">运行IC测试</button>
                        <span id="ic-status-${{sub.id}}" class="ic-status" style="color:#0078d4;"></span>
                        <div id="ic-result-${{sub.id}}"></div>
                        <div id="chart-container-${{sub.id}}" style="width:100%; height:460px; margin-top:14px;"></div>
                    </div>
                </div>
            `;
        }});

        tabsHtml += '</ul>';
        panelsHtml += '</div>';
        container.innerHTML = tabsHtml + panelsHtml;

        if (typeof bootstrap !== 'undefined') {{
            var triggerTabList = [].slice.call(document.querySelectorAll('#icTab button[data-bs-toggle="tab"]'));
            triggerTabList.forEach(function(triggerEl) {{
                var tabTrigger = new bootstrap.Tab(triggerEl);
                triggerEl.addEventListener('click', function(event) {{
                    event.preventDefault();
                    tabTrigger.show();
                }});
            }});
        }}
    }};

    window.runIC = function(subId) {{
        var btn = document.getElementById('run-ic-btn-' + subId);
        var status = document.getElementById('ic-status-' + subId);
        var resultDiv = document.getElementById('ic-result-' + subId);
        if (!btn || !status || !resultDiv) return;

        btn.disabled = true;
        status.innerText = 'IC测试运行中...';
        resultDiv.innerHTML = '';

        var submission = submissions.find(s => s.id == subId);
        if (!submission) {{
            status.innerText = '错误：未找到提交';
            btn.disabled = false;
            return;
        }}

        fetch('/run_ic_test', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{
                submission_id: subId,
                factor_family_alias: '{factor_family_alias}',
                paths: submission.paths,
            }})
        }})
        .then(r => r.json())
        .then(data => {{
            btn.disabled = false;
            if (!data.success) {{
                status.innerText = '✗ IC测试失败: ' + data.error;
                status.style.color = '#d40000';
                return;
            }}

            status.innerText = '✓ IC测试完成' + (data.paths_hash ? (' (路径哈希: ' + data.paths_hash + ')') : '');
            status.style.color = '#28a745';
            resultDiv.innerHTML = buildPrettyTable(data);

            var chartContainer = document.getElementById('chart-container-' + subId);
            if (!chartContainer) return;
            if (typeof Highcharts === 'undefined') {{
                status.innerText = '错误：Highcharts 未加载';
                status.style.color = '#d40000';
                return;
            }}

            var dates = data.ic_series_dates || [];
            var values = data.ic_series_values || [];
            var seriesData = dates.map(function(date, index) {{
                return [new Date(date).getTime(), values[index]];
            }});

            Highcharts.stockChart(chartContainer, {{
                rangeSelector: {{ selected: 1 }},
                title: {{ text: 'IC 序列' }},
                xAxis: {{
                    type: 'datetime',
                    crosshair: {{ width: 1, color: '#0078d4', dashStyle: 'dash' }}
                }},
                yAxis: {{
                    title: {{ text: 'IC 值' }},
                    crosshair: {{ width: 1, color: '#0078d4', dashStyle: 'dash' }}
                }},
                tooltip: {{ shared: true, valueDecimals: 4 }},
                series: [{{ name: 'IC', data: seriesData, tooltip: {{ valueDecimals: 4 }} }}],
                navigator: {{ enabled: true }},
                scrollbar: {{ enabled: true }}
            }});
        }})
        .catch(err => {{
            btn.disabled = false;
            status.innerText = '前端错误: ' + err.message;
            status.style.color = '#d40000';
        }});
    }};
    </script>
    '''

@app.route('/run_ic_test', methods=['POST'])
def run_ic_test():
    import pickle
    import hashlib
    from pathlib import Path

    data = request.get_json()
    submission_id = data.get('submission_id')
    factor_family_alias = data.get('factor_family_alias')
    paths = data.get('paths', [])
    return_freq = data.get('return_freq', 'N')
    start_calc_time = data.get('start_calc_time', f"{default_test_start_date} {default_day_start_time}")
    re_calc = data.get('re_calc', False)  # 是否强制重新计算，默认为 False
    try:

        import pandas as pd

        global factor_testers
        tester = next((t for t in factor_testers if t.alias == str(submission_id)), None)
        assert tester is not None, "未找到对应的测试器实例"
        from Factor import FactorTester
        assert isinstance(tester, FactorTester), "找到的实例类型不正确"
        factor_family = get_factor_family_instance(factor_family_alias)
        assert isinstance(factor_family, FactorFamily), "未找到对应的因子家族实例"
        factors = factor_family.get_factors()  # 获取因子列表

        cache_dir_ic = Path("../data/factor_tester_ic_cache")
        cache_dir_factor = Path("../data/factor_tester_factor_cache")
        cache_dir_ic.mkdir(parents=True, exist_ok=True)
        cache_dir_factor.mkdir(parents=True, exist_ok=True)

        sorted_paths = sorted(paths)
        paths_hash = hashlib.md5(str(sorted_paths).encode()).hexdigest()
        start_calc_time_str = start_calc_time.replace(':', '-').replace(' ', '_') if start_calc_time else 'latest'

        start_date_str = str(tester.start_date).replace(':', '-').replace(' ', '_')
        end_date_str = str(tester.end_date).replace(':', '-').replace(' ', '_')
        original_products = tester.products.copy()

        for factor in factors:

            tester.products = original_products.copy()
            factor.clear()

            factor_series_cache_file = cache_dir_factor / f"{factor.alias}_{start_calc_time_str}.pkl"
            factor_ic_cache_file = cache_dir_ic / f"{factor.alias}_{return_freq}_{paths_hash}_{start_date_str}_{end_date_str}.pkl"
            
            table = None
            if not re_calc and factor_series_cache_file.exists():
                with open(factor_series_cache_file, "rb") as f:
                    table, start_calc_time_cache = pickle.load(f)
                if start_calc_time == start_calc_time_cache:
                    tester.products = set([p for p in tester.products if p not in table.columns])
            if tester.products:
                try:
                    tester.calc_factor(factors=factor)
                except:
                    pass
                finally:
                    if factor.table is None or factor.table.empty:
                        tester.products = set()
            if table is None and (factor.table is None or factor.table.empty):
                raise ValueError("/run_ic_test: 无法计算因子数据，且缓存中无数据可用")
            if table is not None:
                if factor.table is None or factor.table.empty:
                    factor.table = table
                else: # factor.table is not None and table is not None
                    for col in table.columns:
                        assert col not in factor.table.columns, f"/run_ic_test: 列名冲突: {col} 已存在于 factor.table 中"
                    factor.table = pd.concat([table, factor.table], axis=1)
            else: # table is None
                pass # factor.table is not None or empty, otherwise an error would have been raised above
            if tester.products:
                with open(factor_series_cache_file, "wb") as f:
                    pickle.dump((factor.table, start_calc_time), f)
            tester.products = original_products.copy()

            ic_series = None
            ic_stats = None
            if not re_calc and factor_ic_cache_file.exists():
                with open(factor_ic_cache_file, "rb") as f:
                    ic_series, ic_stats, products_cache, return_freq_cache, start_date_cache, end_date_cache = pickle.load(f)
                if products_cache == tester.products and return_freq_cache != return_freq \
                    and start_date_cache == tester.start_date and end_date_cache == tester.end_date:
                    tester.products = set()
            if tester.products:
                try:
                    ic_series_df, ic_stats_df = tester.calc_ic(factors=factor)
                    ic_series = ic_series_df.iloc[:, 0]
                    ic_stats = ic_stats_df.iloc[:, 0]
                except:
                    pass
            assert ic_series is not None and ic_stats is not None, "/run_ic_test: 无法计算IC数据，且缓存中无数据可用"
            factor.ic_series = ic_series
            factor.ic_stats = ic_stats
            if tester.products:
                with open(factor_ic_cache_file, "wb") as f:
                    pickle.dump((factor.ic_series, factor.ic_stats, tester.products, return_freq, tester.start_date, tester.end_date), f)
        
        tester.products = original_products.copy()
        ic_stats = pd.concat([factor.ic_stats for factor in factors], axis=1)
        ic_stats.rename(columns=lambda x: str(x), inplace=True)
        columns = ic_stats.columns.tolist()
        rows = ic_stats.to_dict(orient='records')
        indices = ic_stats.index.tolist()
        for i, row in enumerate(rows):
            row['index'] = indices[i]
        columns = ['index'] + columns

        factor = factors[0]
        ic_series_dates = None
        ic_series_values = None
        if factor.ic_series is not None:
            if isinstance(factor.ic_series.index, pd.MultiIndex):
                ic_series_dates = pd.to_datetime(factor.ic_series.index.get_level_values(1)).strftime('%Y-%m-%d').tolist()
            else:
                ic_series_dates = pd.to_datetime(factor.ic_series.index).strftime('%Y-%m-%d').tolist()
            ic_series_values = factor.ic_series.values.tolist()

        response = {
            'success': True,
            'paths_hash': paths_hash,
            'ic_stats': {},
            'factors': [],
            'columns': columns, 
            'rows': rows,
            'ic_series_dates': ic_series_dates,
            'ic_series_values': ic_series_values,
        }
        
        from Products import Product
        for factor in factors:
            ic_series_dates = None
            ic_series_values = None
            if isinstance(factor.ic_series.index, pd.MultiIndex):
                ic_series_dates = pd.to_datetime(factor.ic_series.index.get_level_values(1)).strftime('%Y-%m-%d').tolist()
            else:
                ic_series_dates = pd.to_datetime(factor.ic_series.index).strftime('%Y-%m-%d').tolist()
            ic_series_values = factor.ic_series.values.tolist()
            response['factors'].append({
                'name': factor.name,
                'alias': factor.alias,
                'ic_series': {
                    'dates': ic_series_dates,
                    'values': ic_series_values,
                },
                'products': [product.name for product in factor.table.columns if product in tester.products and isinstance(product, Product)] if factor.table is not None else [],
            })

        return jsonify(response)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

def get_group_test_module_html():
    return """
        <div class="module" id="group_test_module" style="margin-top:32px;display:none;">
            <div class="section-title">4. 分组测试</div>
            <button disabled style="background:#ccc;">运行分组测试</button>
            <div style="color:#aaa;">（功能开发中）</div>
        </div>
    """

def get_factor_main_section_html(factor_family_alias):
    module_infos = [
        ('latex_module', get_latex_module_html, factor_family_alias),
        ('parameter_module', get_parameter_module_html, factor_family_alias),
        ('time_range_module', get_time_range_module_html, factor_family_alias),
        ('category_filter_module', get_category_filter_module_html),
        ('ic_test_module', get_ic_test_module_html, factor_family_alias),
        ('group_test_module', get_group_test_module_html),
    ]
    modules_html = ""
    module_ids = []
    for info in module_infos:
        mid, func, *args = info
        modules_html += func(*args) if args else func()
        module_ids.append(mid)

    return f"""
        <div class="section">
            <div class="section-title">当前因子: <b style="color:#0078d4;">{factor_family_alias}</b></div>
            <div style="margin-top:16px;color:#888;">功能陆续开发中</div>
            {modules_html}
        </div>
        <script>
            function openModule(moduleId) {{
                var el = document.getElementById(moduleId);
                if (el) el.style.display = '';
            }}
            function closeModule(moduleId) {{
                var el = document.getElementById(moduleId);
                if (el) el.style.display = 'none';
            }}
            document.addEventListener('DOMContentLoaded', function() {{
                {'; '.join([f"openModule('{mid}')" for mid in module_ids])}
            }});
        </script>
    """


# --- Flask Routes ---

@app.route('/', methods=['GET'])
def index():
    factors_dir = os.path.join(os.getcwd(), "Factors")
    if not os.path.exists(factors_dir):
        os.makedirs(factors_dir)
    groups, factor_names = get_factor_groups(factors_dir)

    search_query = request.args.get('search', '')
    selected_name = request.args.get('factor', '')

    if search_query:
        filtered_groups = {}
        for group, names in groups.items():
            filtered = [n for n in names if search_query.lower() in n.lower()]
            if filtered:
                filtered_groups[group] = filtered
        groups = filtered_groups
        factor_names = [n for n in factor_names if search_query.lower() in n.lower()]

    group_html = build_group_html(groups) if groups else '<div style="color:#888;">无匹配因子</div>'

    if selected_name and selected_name in factor_names:
        main_content = get_factor_main_section_html(selected_name)
    elif not groups:
        main_content = '<div style="margin-top:64px;color:#888;font-size:22px;text-align:center;">未搜索到任何因子</div>'
    else:
        main_content = ''

    return render_template_string(
        BASE_TEMPLATE,
        search_query=search_query,
        group_html=group_html,
        main_content=main_content
    )

@app.route('/shutdown', methods=['POST'])
def shutdown():
    func = request.environ.get('werkzeug.server.shutdown')
    if func:
        func()
    else:
        threading.Thread(target=lambda: os._exit(0)).start()
    return '', 200

def run_flask_server(port=8000, directory='.'):
    os.chdir(directory)
    url = f"http://localhost:{port}/"
    print(f"Serving Flask on {url} from {os.path.abspath(directory)}")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host='localhost', port=port, debug=False, use_reloader=False)
    print("服务器已关闭。")

if __name__ == '__main__':
    run_flask_server(port=8000, directory='.')
