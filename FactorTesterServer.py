   
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
        <div style="margin-top:-15px; display: flex; align-items: baseline;">
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

                document.getElementById('confirm_time_status').innerText = '保存中...';

                fetch('/set_time_range', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(timeData)
                }})
                .then(response => response.json())
                .then(data => {{
                    if (data.success) {{
                        document.getElementById('confirm_time_status').innerText = '✓ 已保存，各因子起始计算时间已更新为唯一值: ' + data.start_calc_param_val;
                    if (data.show_next) {{
                        openModule('category_filter_module');
                    }}
                    }} else {{
                    document.getElementById('confirm_time_status').innerText = '保存失败: ' + (data.error || '未知错误');
                    }}
                }})
                .catch(err => {{
                    console.error('请求出错', err);
                    document.getElementById('confirm_time_status').innerText = '网络错误';
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

def get_category_filter_module_html():
    tree = get_cat_tree().tree

    # 递归生成HTML（默认展开到第一次没有$SUBCLASS$的层，剩下的层默认隐藏）
    def render_tree(tree, path=None, level=0, expand=True):
        if path is None:
            path = []
        html = ''
        for key, value in tree.items():
            if key == '$OBJECTS$':
                obj_path = '_'.join(str(p) for p in path)
                html += f'<div class="tree-level-{level+1}" style="margin-left:{level*4}px;margin-bottom:2px;">'
                html += f'<input type="checkbox" class="select-all" data-level="{level+1}" data-path="{obj_path}" onclick="selectAllObjects(this)" style="width:13px;height:13px;">'
                html += f'<button type="button" onclick="toggleCollapse(\'{obj_path}_collapse\')" style="margin-left:4px;font-size:12px;padding:1px 6px;height:22px;">折叠/展开</button>'
                html += f'<button type="button" onclick="loadProducts(\'{obj_path}_collapse\', \'{obj_path}\')" style="margin-left:4px;font-size:12px;padding:1px 6px;height:22px;">查看产品</button>'
                html += f'<div id="{obj_path}_collapse" style="display:none;"></div>'
                html += '</div>'
            elif key == '$SUBCLASS$':
                # 如果有$SUBCLASS$，默认展开，否则默认隐藏
                html += render_tree(value, path, level, expand)
            else:
                new_path = path + [str(key)]
                # 判断是否有$SUBCLASS$，决定是否展开
                has_subclass = '$SUBCLASS$' in value
                display = '' if expand else 'none'
                html += f'<div class="tree-level-{level+1}" style="margin-left:{level*4}px;margin-bottom:2px;display:{display};" id="tree_{("_".join(new_path))}_div">'
                html += f'<span style="color:#0078d4;font-size:13px;">{str(key)}</span>'
                html += render_tree(value, new_path, level+1, expand=has_subclass)
                html += '</div>'
        return html

    html = '<div class="module" id="category_filter_module" style="margin-top:24px;">'
    html += '<div class="section-title" style="font-size:15px;">2. 产品类别筛选</div>'
    html += '<div style="margin-bottom:8px;color:#888;font-size:12px;">可折叠树状结构，勾选后提交</div>'
    html += '<form id="product_filter_form">'
    html += render_tree(tree)
    html += '<button type="button" onclick="submitSelectedProducts()" style="margin-top:12px;background:#0078d4;color:#fff;border:none;border-radius:4px;padding:3px 10px;font-size:13px;height:24px;">提交选中产品</button>'
    html += '</form>'
    html += '<div id="submit_status" style="margin-top:6px;color:#0078d4;font-size:12px;"></div>'
    html += '</div>'
    
    # 前端JS
    js = """
    <script>
    function toggleCollapse(id) {
        var el = document.getElementById(id);
        if (el) el.style.display = (el.style.display === 'none' ? '' : 'none');
    }
    function loadProducts(divId, objPath) {
        var div = document.getElementById(divId);
        if (!div) return;
        if (div.getAttribute('data-loaded') === '1') {
            div.style.display = '';
            return;
        }
        div.innerHTML = '<div style="color:#888;font-size:12px;margin-left:6px;">加载中...</div>';
        fetch('/get_products?path=' + encodeURIComponent(objPath))
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    var html = '';
                    data.products.forEach(function(prod) {
                        var prod_id = objPath + '_' + prod.id;
                        html += '<div class="tree-level-product" style="margin-left:6px;margin-bottom:2px;">';
                        html += '<input type="checkbox" name="selected_products" value="' + prod_id + '" class="product-checkbox" style="width:13px;height:13px;">';
                        html += '<span style="color:#888;font-size:12px;">' + prod.name + '</span>';
                        html += '</div>';
                    });
                    div.innerHTML = html;
                    div.setAttribute('data-loaded', '1');
                    div.style.display = '';
                } else {
                    div.innerHTML = '<div style="color:#d40000;font-size:12px;">加载失败: ' + (data.error || '未知错误') + '</div>';
                }
            });
    }
    function selectAllObjects(checkbox) {
        var path = checkbox.getAttribute('data-path');
        var form = document.getElementById('product_filter_form');
        var checked = checkbox.checked;
        var prodBoxes = form.querySelectorAll('input.product-checkbox');
        prodBoxes.forEach(function(b) {
            if (b.value.startsWith(path + '_')) b.checked = checked;
        });
    }
    function submitSelectedProducts() {
        var form = document.getElementById('product_filter_form');
        var checked = Array.from(form.querySelectorAll('input.product-checkbox:checked')).map(function(b) { return b.value; });
        fetch('/submit_selected_products', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({selected_products: checked})
        }).then(r => r.json()).then(data => {
            var status = document.getElementById('submit_status');
            if (data.success) status.innerText = '✓ 已提交，选中产品数量: ' + data.count;
            else status.innerText = '提交失败: ' + (data.error || '未知错误');
        });
    }
    // 默认展开到第一次没有$SUBCLASS$的层
    document.addEventListener('DOMContentLoaded', function() {
        var divs = document.querySelectorAll('[id^="tree_"]');
        divs.forEach(function(div) {
            if (div.style.display === 'none') div.style.display = '';
        });
    });
    </script>
    """

    return html + js

def get_ic_test_module_html():
    return """
        <div class="module" id="ic_test_module" style="margin-top:32px;display:none;">
            <div class="section-title">3. IC测试</div>
            <button disabled style="background:#ccc;">运行IC测试</button>
            <div style="color:#aaa;">（功能开发中）</div>
        </div>
    """

def get_group_test_module_html():
    return """
        <div class="module" id="group_test_module" style="margin-top:32px;display:none;">
            <div class="section-title">4. 分组测试</div>
            <button disabled style="background:#ccc;">运行分组测试</button>
            <div style="color:#aaa;">（功能开发中）</div>
        </div>
    """

def get_factor_main_section_html(factor_family_alias):
    module_ids = [
        'latex_module',
        'parameter_module',
        'time_range_module',
        'category_filter_module',
        'ic_test_module',
        'group_test_module']
    return f"""
        <div class="section">
            <div class="section-title">当前因子: <b style="color:#0078d4;">{factor_family_alias}</b></div>
            <div style="margin-top:16px;color:#888;">功能陆续开发中</div>
            {get_latex_module_html(factor_family_alias)}
            {get_parameter_module_html(factor_family_alias)}
            {get_time_range_module_html(factor_family_alias)}
            {get_category_filter_module_html()}
            {get_ic_test_module_html()}
            {get_group_test_module_html()}
        </div>
        <script>
            function openModule(moduleId) {{ document.getElementById(moduleId).style.display = ''; }}
            function closeModule(moduleId) {{ document.getElementById(moduleId).style.display = 'none'; }}
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

        # 可以根据是否是交易日等设置调整默认的时间范围
        show_next = (start_date <= end_date)

        return jsonify({'success': True, 'show_next': show_next, 'start_calc_param_val': start_calc_param_val})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/submit_selected_products', methods=['POST'])
def submit_selected_products():
    data = request.get_json()
    selected_products = data.get('selected_products', [])
    try:
        # 这里可以保存选中的产品到session或文件等
        # 这里只返回数量
        return jsonify({'success': True, 'count': len(selected_products)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

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
