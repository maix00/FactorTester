   
# factor_server.py

import importlib.util
import importlib
import os
import sys
import threading
import webbrowser

from flask import Flask, request, jsonify, render_template_string
from Settings import *

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

def get_parameter_module_html(selected_name):
    try:
        ff = get_factor_family_instance(selected_name)
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
                <tr>
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

        table_html = f"""
            <div style="overflow-x:auto;max-width:800px;" id="param_table_scroll">
                <table style="border-collapse:collapse;width:100%;background:#fff;min-width:{120 + sum(get_col_min_width(p) for p in sorted_params) + 80}px;">
                    <thead style="background:#f6f8fa;">{header_html}</thead>
                    <tbody>{input_row_html}{factor_rows_html}</tbody>
                </table>
            </div>
        """

        param_aliases_js = '[' + ','.join([f"'{p.alias}'" for p in sorted_params]) + ']'

        js = f"""
            <script>
                document.addEventListener('DOMContentLoaded', function() {{
                    var scrollDiv = document.getElementById('param_table_scroll');
                    if(scrollDiv) {{
                        scrollDiv.addEventListener('wheel', function(e) {{
                            if (e.deltaY !== 0) {{ scrollDiv.scrollLeft += e.deltaY; e.preventDefault(); }}
                        }});
                    }}
                    function reloadParamTable() {{
                        fetch(window.location.pathname + '?factor={selected_name}')
                            .then(r => r.text())
                            .then(html => {{
                                var parser = new DOMParser();
                                var doc = parser.parseFromString(html, 'text/html');
                                var newTable = doc.getElementById('param_table_scroll');
                                var oldTable = document.getElementById('param_table_scroll');
                                if(newTable && oldTable) oldTable.parentNode.replaceChild(newTable, oldTable);
                                bindParamTableEvents();
                            }});
                    }}
                    function bindParamTableEvents() {{
                        var addBtn = document.getElementById('add_factor_btn');
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
                                    body: JSON.stringify({{factor_family_name: '{selected_name}', params: paramValues}})
                                }}).then(r => r.json()).then(data => {{
                                    if(data.success) {{ reloadParamTable(); }}
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
                                    body: JSON.stringify({{factor_family_name: '{selected_name}', factor_idx: idx}})
                                }}).then(r => r.json()).then(data => {{
                                    if(data.success) reloadParamTable();
                                    else alert('删除失败: ' + data.error);
                                }});
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


def get_time_range_module_html():
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
            起始日期:
            <input type="number" min="1900" max="2100" id="start_year" value="{default_test_start_date[:4]}" style="width:60px;background:#eee;border:none;border-radius:4px;font-size:16px;margin-left:8px;">
            <span style="font-size:16px;">-</span>
            <input type="number" min="1" max="12" id="start_month" value="{pad(default_test_start_date[5:7])}" style="width:40px;background:#eee;border:none;border-radius:4px;font-size:16px;">
            <span style="font-size:16px;">-</span>
            <input type="number" min="1" max="31" id="start_day" value="{pad(default_test_start_date[8:10])}" style="width:40px;background:#eee;border:none;border-radius:4px;font-size:16px;">
            </span>
            <span style="font-size:13px;">
            起始时间:
            <input type="number" min="0" max="23" id="start_hour" value="{pad(default_day_start_time[:2])}" style="width:40px;background:#eee;border:none;border-radius:4px;font-size:16px;margin-left:8px;">
            <span style="font-size:16px;">:</span>
            <input type="number" min="0" max="59" id="start_minute" value="{pad(default_day_start_time[3:5])}" style="width:40px;background:#eee;border:none;border-radius:4px;font-size:16px;">
            </span>
        </div>
        <div style="display:flex;align-items:center;gap:24px;margin-top:12px;">
            <span style="font-size:13px;">
            终末日期:
            <input type="number" min="1900" max="2100" id="end_year" value="{default_test_end_date[:4]}" style="width:60px;background:#eee;border:none;border-radius:4px;font-size:16px;margin-left:8px;">
            <span style="font-size:16px;">-</span>
            <input type="number" min="1" max="12" id="end_month" value="{pad(default_test_end_date[5:7])}" style="width:40px;background:#eee;border:none;border-radius:4px;font-size:16px;">
            <span style="font-size:16px;">-</span>
            <input type="number" min="1" max="31" id="end_day" value="{pad(default_test_end_date[8:10])}" style="width:40px;background:#eee;border:none;border-radius:4px;font-size:16px;">
            </span>
            <span style="font-size:13px;">
            终末时间:
            <input type="number" min="0" max="23" id="end_hour" value="{pad(default_day_end_time[:2])}" style="width:40px;background:#eee;border:none;border-radius:4px;font-size:16px;margin-left:8px;">
            <span style="font-size:16px;">:</span>
            <input type="number" min="0" max="59" id="end_minute" value="{pad(default_day_end_time[3:5])}" style="width:40px;background:#eee;border:none;border-radius:4px;font-size:16px;">
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
        <div style="margin-top:8px;color:#888;">
            <span>当前设置：</span>
            <span id="current_settings"></span>
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
                if (!isNaN(start_dt.getTime()) && !isNaN(end_dt.getTime()) && start_dt <= end_dt) {{
                    openModule('category_filter_module');
                }} else {{
                    closeModule('category_filter_module');
                }}
            }}
            function validateInputOnBlur(input, min, max, isDay, yearId, monthId) {{
                var num = parseInt(input.value);
                if (isNaN(num) || num < min) input.value = pad(min);
                else if (num > max) input.value = pad(max);
                else input.value = pad(num);
                if (isDay) {{
                    var maxDay = getMaxDay(document.getElementById(yearId).value, document.getElementById(monthId).value);
                    if (parseInt(input.value) > maxDay) input.value = pad(maxDay);
                }}
                updateCurrentSettings();
            }}
            function adjustDayIfNeeded(dayId, yearId, monthId) {{
                var dayElem = document.getElementById(dayId);
                var maxDay = getMaxDay(document.getElementById(yearId).value, document.getElementById(monthId).value);
                var dayVal = parseInt(dayElem.value);
                if (isNaN(dayVal) || dayVal < 1) dayElem.value = pad(1);
                else if (dayVal > maxDay) dayElem.value = pad(maxDay);
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
                        validateInputOnBlur(elem,min,max,isDay,yearId,monthId);
                        if(id==='start_year'||id==='start_month') adjustDayIfNeeded('start_day','start_year','start_month');
                        if(id==='end_year'||id==='end_month') adjustDayIfNeeded('end_day','end_year','end_month');
                    }});
                    elem.addEventListener('keydown', function(e) {{
                        if(e.key==='Enter') {{
                            validateInputOnBlur(elem,min,max,isDay,yearId,monthId);
                            if(id==='start_year'||id==='start_month') adjustDayIfNeeded('start_day','start_year','start_month');
                            if(id==='end_year'||id==='end_month') adjustDayIfNeeded('end_day','end_year','end_month');
                        }}
                    }});
                    elem.addEventListener('input', function() {{
                        updateCurrentSettings();
                        if(id==='start_year'||id==='start_month') adjustDayIfNeeded('start_day','start_year','start_month');
                        if(id==='end_year'||id==='end_month') adjustDayIfNeeded('end_day','end_year','end_month');
                    }});
                }});
                toggleTradingDay();
                updateCurrentSettings();
                {show_next}
            }});
        </script>
        </div>
    """


def get_category_filter_module_html():
    return """
        <div class="module" id="category_filter_module" style="margin-top:32px;display:none;">
            <div class="section-title">2. 产品类别筛选</div>
            <div style="color:#aaa;">（功能开发中）</div>
        </div>
    """


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


def get_factor_main_section_html(selected_name):
    module_ids = ['parameter_module', 'time_range_module', 'category_filter_module', 'ic_test_module', 'group_test_module']
    return f"""
        <div class="section">
            <div class="section-title">当前因子: <b style="color:#0078d4;">{selected_name}</b></div>
            <div style="margin-top:16px;color:#888;">功能开发中，仅展示页面框架。</div>
            {get_parameter_module_html(selected_name)}
            {get_time_range_module_html()}
            {get_category_filter_module_html()}
            {get_ic_test_module_html()}
            {get_group_test_module_html()}
        </div>
        <script>
            function openModule(moduleId) {{ document.getElementById(moduleId).style.display = ''; }}
            function closeModule(moduleId) {{ document.getElementById(moduleId).style.display = 'none'; }}
            document.addEventListener('DOMContentLoaded', function() {{
                openModule('{module_ids[0]}');
                openModule('{module_ids[1]}');
                {'; '.join([f"closeModule('{mid}')" for mid in module_ids[2:]])}
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
    factor_family_name = data.get('factor_family_name')
    params = data.get('params', {})
    try:
        ff = get_factor_family_instance(factor_family_name)
        ff.add_params(**params)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/delete_params', methods=['POST'])
def delete_params():
    data = request.get_json()
    factor_family_name = data.get('factor_family_name')
    factor_idx = int(data.get('factor_idx', -1))
    try:
        ff = get_factor_family_instance(factor_family_name)
        if 0 <= factor_idx < len(ff._params_list):
            ff._params_list.pop(factor_idx)
        return jsonify({'success': True})
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
