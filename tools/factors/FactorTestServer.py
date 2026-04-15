import sys
from datetime import datetime

from flask import Flask, request, jsonify, render_template  # 添加 render_template
import os
import importlib.util
import threading
import webbrowser
from tools.factors.Factor import FactorFamily, StartCalcPointParam
import Settings as Settings
import time
import traceback

# 添加这段代码来适配打包环境
if getattr(sys, 'frozen', False):
    base_path = getattr(sys, '_MEIPASS', os.path.abspath('.'))
    template_folder = os.path.join(base_path, 'templates')
    static_folder = os.path.join(base_path, 'static')
    app = Flask(__name__, template_folder=template_folder, static_folder=static_folder)
else:
    app = Flask(__name__)

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
    if not groups:
        return '<div style="color:#888;">无匹配因子</div>'
    
    group_html = ""
    for group, names in sorted(groups.items()):
        group_html += f'<div class="factor-group">'
        group_html += f'<div class="factor-group-title">{group}</div>'
        group_html += '<ul class="factor-list">'
        for name in sorted(names):
            group_html += f'<li><a href="?factor={name}">{name}</a></li>'
        group_html += '</ul>'
        group_html += '</div>'
    return group_html

def get_factor_main_section_html(factor_family_alias):
    """
    使用模板渲染因子主内容区域
    """
    try:
        ff = get_factor_family_instance(factor_family_alias)
        
        # 准备 LaTeX 模块的数据
        math_expr = getattr(ff, 'math_expr', '')
        
        # 准备参数模块的数据
        params = ff.params
        param_aliases = [p.alias for p in params]
        factors = ff.get_factors()
        
        # 准备时间范围模块的数据
        from datetime import datetime as _dt
        start_date = getattr(Settings, 'default_test_start_date', '2020-01-01')
        end_date = getattr(Settings, 'default_test_end_date', '2024-12-31')
        start_time = getattr(Settings, 'default_day_start_time', '09:30')
        end_time = getattr(Settings, 'default_day_end_time', '15:00')
        
        # 渲染模板
        return render_template(
            'factor_main.html',
            factor_family_alias=factor_family_alias,
            math_expr=math_expr,
            params=params,
            param_aliases=param_aliases,
            factors=factors,
            start_date=start_date,
            end_date=end_date,
            start_time=start_time,
            end_time=end_time
        )
    except Exception as e:
        # 如果出错，返回错误信息
        return f"""
            <div class="section">
                <div class="section-title">当前因子: <b style="color:#0078d4;">{factor_family_alias}</b></div>
                <div style="color:#d40000;padding:20px;">加载因子失败: {e}</div>
            </div>
        """
    
@app.route('/', methods=['GET'])
def index():
    factors_dir = os.path.join(os.getcwd(), "Factors")
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

    main_content = ''
    
    if selected_name and selected_name in factor_names:
        try:
            print(f"尝试加载因子: {selected_name}")  # 调试输出
            main_content = get_factor_main_section_html(selected_name)
            print("因子加载成功")  # 调试输出
        except Exception as e:
            print(f"因子加载失败: {e}")  # 调试输出
            traceback.print_exc()  # 打印完整错误堆栈
            main_content = f"""
                <div class="section">
                    <div class="section-title">错误</div>
                    <div style="color:#d40000;padding:20px;">
                        加载因子 "{selected_name}" 失败:<br>
                        <pre>{str(e)}</pre>
                    </div>
                </div>
            """
    elif not groups:
        main_content = '<div style="margin-top:64px;color:#888;font-size:22px;text-align:center;">未搜索到任何因子</div>'

    return render_template(
        'base.html',
        search_query=search_query,
        group_html=group_html,
        main_content=main_content,
        initial_modules=[]
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

@app.route('/api/default_time_range')
def get_default_time_range():
    from Settings import default_test_start_date, default_test_end_date, default_day_start_time, default_day_end_time
    return jsonify({
        'start_date': default_test_start_date,
        'start_time': default_day_start_time,
        'end_date': default_test_end_date,
        'end_time': default_day_end_time,
        'timezone': getattr(Settings, 'timezone', 'Asia/Shanghai'),
        'cn_futures_day_start': getattr(Settings, 'default_cn_futures_day_start', '09:00'),
        'cn_futures_day_end': getattr(Settings, 'default_cn_futures_day_end', '15:00'),
        'cn_futures_night_start': getattr(Settings, 'default_cn_futures_night_start', '21:00'),
        'cn_futures_night_end': getattr(Settings, 'default_cn_futures_night_end', '15:00'),
    })
    
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

        import pandas as pd
        # 这里可以添加对时间格式的验证
        global default_test_start_date, default_test_end_date, default_day_start_time, default_day_end_time, timezone, start_calc_point, start_point, end_point
        default_test_start_date = start_date
        default_test_end_date = end_date
        default_day_start_time = start_time
        default_day_end_time = end_time
        timezone = data.get('timezone', 'UTC')
        start_calc_point = pd.Timestamp(f"{start_date} {start_time}").tz_localize(timezone) if not is_trading_day else pd.Timestamp(start_date).date()
        start_point = pd.Timestamp(f"{start_date} {start_time}").tz_localize(timezone) if not is_trading_day else pd.Timestamp(start_date).tz_localize(timezone)
        end_point = pd.Timestamp(f"{end_date} {end_time}").tz_localize(timezone) if not is_trading_day else pd.Timestamp(end_date).tz_localize(timezone)

        factors = ff.get_factors(start_calc_point=start_calc_point)
        start_calc_param_val = list(set([StartCalcPointParam.get_value(factor) for factor in factors]))
        assert len(start_calc_param_val) == 1
        start_calc_param_val = f"{StartCalcPointParam.name} = {start_calc_param_val[0]}"

        if factor_testers:
            from tools.factors.FactorTester import FactorTester
            for tester in factor_testers:
                assert isinstance(tester, FactorTester)
                tester.update_time_range((start_point, end_point))

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

tree = Settings.get_cat_tree().tree

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
        from tools.factors.FactorTester import FactorTester
        factor_tester = FactorTester(products=selected_products, alias=id_time, time_range=(start_point, end_point))
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

@app.route('/api/factor_list')
def factor_list():
    factor_family_alias = request.args.get('factor_family_alias')
    if not factor_family_alias:
        return jsonify({'success': False, 'error': '缺少参数'})
    try:
        ff = get_factor_family_instance(factor_family_alias)
        factors = ff.get_factors()
        factor_data = []
        for f in factors:
            # 将 freq 转换为字符串，假设它是枚举或具有 value 属性
            freq_value = getattr(f, 'freq', None)
            if hasattr(freq_value, 'value'):   # 如果是枚举
                assert freq_value is not None
                freq_str = str(freq_value.value)
            else:
                freq_str = str(freq_value) if freq_value is not None else 'N'
            factor_data.append({
                'alias': f.alias,
                'name': f.name,
                'freq': freq_str   # 确保是字符串
            })
        return jsonify({'success': True, 'factors': factor_data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/run_ic_test', methods=['POST'])
def run_ic_test():
    import pickle
    import hashlib
    from pathlib import Path

    data = request.get_json()
    submission_id = data.get('submission_id')
    factor_family_alias = data.get('factor_family_alias')
    factor_alias_return_freq = data.get('factors', [])
    paths = data.get('paths', [])
    return_freq = data.get('return_freq', 'N')
    re_calc = data.get('re_calc', False)  # 是否强制重新计算，默认为 False
    try:

        import pandas as pd

        global factor_testers
        tester = next((t for t in factor_testers if t.alias == str(submission_id)), None)
        assert tester is not None, "未找到对应的测试器实例"
        from tools.factors.FactorTester import FactorTester
        assert isinstance(tester, FactorTester), "找到的实例类型不正确"
        factor_family = get_factor_family_instance(factor_family_alias)
        assert isinstance(factor_family, FactorFamily), "未找到对应的因子家族实例"
        factors = factor_family.get_factors()  # 获取因子列表
        factors = [next((f for f in factors if f.alias == item['alias'])) for item in factor_alias_return_freq]
        return_freqs = {}
        for factor, item in zip(factors, factor_alias_return_freq):
            return_freq = item.get('return_freq', None)
            return_freqs[factor] = (None if return_freq == 'N' else return_freq)
        assert factors, "没有找到匹配的因子"

        cache_dir_ic = Path('../data/cache/ic')
        cache_dir_factor = Path('../data/cache/factor')
        cache_dir_ic.mkdir(parents=True, exist_ok=True)
        cache_dir_factor.mkdir(parents=True, exist_ok=True)

        sorted_paths = sorted(paths)
        paths_hash = hashlib.md5(str(sorted_paths).encode()).hexdigest()
        start_calc_point_str = str(start_calc_point).replace(':', '-').replace(' ', '_') if start_calc_point else 'latest'

        start_date_str = str(tester.start_date).replace(':', '-').replace(' ', '_')
        end_date_str = str(tester.end_date).replace(':', '-').replace(' ', '_')
        all_products = tester.products.copy()

        for factor in factors:

            run_products = all_products.copy()
            factor.clear()
            return_freq = return_freqs.get(factor, None)

            factor_series_cache_file = cache_dir_factor / f"{factor.alias}_{start_calc_point_str}.pkl"
            factor_ic_cache_file = cache_dir_ic / f"{paths_hash}_{factor.alias}_{return_freq}_{start_date_str}_{end_date_str}.pkl"

            table = None
            if not re_calc and factor_series_cache_file.exists():
                with open(factor_series_cache_file, "rb") as f:
                    table, start_calc_point_cache = pickle.load(f)
                if start_calc_point == start_calc_point_cache:
                    run_products = set([p for p in tester.products if p not in table.columns])
            if run_products:
                try:
                    tester.products = run_products.copy()
                    tester.calc_factor(factors=factor)
                except:
                    tester.products = all_products.copy()
                    pass
                finally:
                    tester.products = all_products.copy()
                    if factor.table is None or factor.table.empty:
                        run_products = set()
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
            if run_products:
                with open(factor_series_cache_file, "wb") as f:
                    pickle.dump((factor.table, start_calc_point), f)
            run_products = all_products.copy()

            ic_series = None
            ic_stats = None
            if not re_calc and factor_ic_cache_file.exists():
                with open(factor_ic_cache_file, "rb") as f:
                    ic_series, ic_stats, products_cache, return_freq_cache, _, start_date_cache, end_date_cache = pickle.load(f)
                if products_cache == run_products and return_freq_cache != return_freq \
                    and start_date_cache == tester.start_date and end_date_cache == tester.end_date:
                    run_products = set()
            returns_table = pd.DataFrame()  # 确保 returns_table 定义，以便后续检查，即使计算失败也不会导致未定义错误
            if run_products:
                try:
                    ic_series_df, ic_stats_df = tester.calc_ic(factors=factor, return_freq=return_freq)
                    returns_table = factor.returns
                    ic_series = ic_series_df.iloc[:, 0]
                    ic_stats = ic_stats_df.iloc[:, 0]
                except:
                    pass
            assert ic_series is not None and ic_stats is not None and not returns_table.empty, "/run_ic_test: 无法计算IC数据，且缓存中无数据可用"
            factor.ic_series = ic_series
            factor.ic_stats = ic_stats
            if run_products:
                with open(factor_ic_cache_file, "wb") as f:
                    pickle.dump((factor.ic_series, factor.ic_stats, all_products, return_freq, returns_table, tester.start_date, tester.end_date), f)
        
        tester.products = all_products.copy()
        ic_stats = pd.concat([factor.ic_stats for factor in factors], axis=1)
        ic_stats.rename(columns=lambda x: str(x), inplace=True)
        columns = ic_stats.columns.tolist()
        rows = ic_stats.to_dict(orient='records')
        indices = ic_stats.index.tolist()
        for i, row in enumerate(rows):
            row['index'] = indices[i]
        columns = ['index'] + columns

        response = {
            'success': True,
            'paths_hash': paths_hash,
            'ic_stats': {
                'columns': columns,
                'rows': rows,
            },
            'factors': [],
        }
        
        from tools.products.Product import Product
        for factor in factors:
            ic_series_dates = None
            ic_series_values = None
            ic_series = factor.ic_series.dropna()
            # 新代码：返回时间戳（毫秒）
            import numpy as np
            if isinstance(ic_series.index, pd.MultiIndex):
                # 多级索引时取第二级（通常是时间）
                timestamps = ic_series.index.get_level_values(-1).view(np.int64) // 10**6
            else:
                timestamps = ic_series.index.view(np.int64) // 10**6
            ic_series_dates = timestamps.tolist()
            ic_series_values = ic_series.values.tolist()
            ic_series_values = [None if (isinstance(v, float) and (pd.isna(v) or pd.isnull(v))) else v for v in ic_series_values]
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

@app.route('/get_factor_series', methods=['POST'])
def get_factor_series():
    import pickle
    from pathlib import Path
    data = request.get_json()
    submission_id = data.get('submission_id')
    factor_family_alias = data.get('factor_family_alias')
    factor_name = data.get('factor_name')
    product_name = data.get('product')
    re_calc = data.get('re_calc', False)

    try:
        global factor_testers
        tester = next((t for t in factor_testers if t.alias == str(submission_id)), None)
        if not tester:
            return jsonify({'error': '未找到测试器实例'}), 404

        # 获取因子家族和具体因子
        factor_family = get_factor_family_instance(factor_family_alias)
        factors = factor_family.get_factors()
        target_factor = next((f for f in factors if f.name == factor_name), None)
        if not target_factor:
            return jsonify({'error': '未找到因子'}), 404

        product = next((p for p in tester.products if p.name == product_name), None)
        if not product:
            return jsonify({'error': '未找到产品'}), 404

        # 缓存目录
        cache_dir_factor = Path('../data/cache/factor')
        cache_dir_factor.mkdir(parents=True, exist_ok=True)
        start_calc_point_str = str(start_calc_point).replace(':', '-').replace(' ', '_') if start_calc_point else 'latest'
        cache_file_1 = cache_dir_factor / f"{target_factor.alias}_{start_calc_point_str}.pkl"
        cache_file_2 = cache_dir_factor / f"{target_factor.alias}_{product.alias}_{start_calc_point_str}.pkl"
        cache_file_1_exists = cache_file_1.exists()
        cache_file_2_exists = cache_file_2.exists()

        series = None
        if not re_calc and cache_file_1_exists:
            with open(cache_file_1, 'rb') as f:
                table, start_calc_point_cache = pickle.load(f)
                if product in table.columns and start_calc_point_cache == start_calc_point:
                    series = table[product].dropna()
                else:
                    re_calc = True
        elif not re_calc and cache_file_2_exists:
            with open(cache_file_2, 'rb') as f:
                table, start_calc_point_cache = pickle.load(f)
                if start_calc_point_cache == start_calc_point:
                    if hasattr(table, 'columns') and product in table.columns:
                        series = table[product].dropna()
                    else:
                        import pandas as pd
                        assert isinstance(table, pd.Series), "缓存数据格式错误，预期为 DataFrame 或 Series"
                        series = table.dropna()
                else:
                    re_calc = True
        if re_calc or (not cache_file_1_exists and not cache_file_2_exists) or series is None:
            # 计算因子序列（仅针对该产品）
            original_products = tester.products.copy()
            tester.products = [product]
            target_factor.clear()
            try:
                tester.calc_factor(factors=target_factor)
                if target_factor.table is None or target_factor.table.empty:
                    raise ValueError("因子计算无结果")
                series = target_factor.table[product].dropna()
                # 缓存
                with open(cache_file_2, 'wb') as f:
                    pickle.dump((target_factor.table, start_calc_point), f)
            finally:
                tester.products = original_products

        assert series is not None, "无法获取因子序列数据"
        # 转换为时间戳（毫秒）
        import numpy as np
        import pandas as pd
        if isinstance(series.index, pd.MultiIndex):
            timestamps = series.index.get_level_values(-1).view(np.int64) // 10**6
        else:
            timestamps = series.index.view(np.int64) // 10**6
        values = series.values.tolist()
        # 处理 NaN
        values = [None if (isinstance(v, float) and pd.isna(v)) else v for v in values]

        return jsonify({'dates': timestamps.tolist(), 'values': values})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
@app.route('/get_return_series', methods=['POST'])
def get_return_series():
    import pickle, hashlib
    from pathlib import Path
    data = request.get_json()
    submission_id = data.get('submission_id')
    product_name = data.get('product')
    factor_family_alias = data.get('factor_family_alias')
    factor_name = data.get('factor_name')
    return_freq = data.get('return_freq', None)
    paths = data.get('paths', [])
    re_calc = data.get('re_calc', False)

    try:
        global factor_testers
        tester = next((t for t in factor_testers if t.alias == str(submission_id)), None)
        if not tester:
            return jsonify({'error': '未找到测试器实例'}), 404
        
        # 获取因子家族和具体因子
        factor_family = get_factor_family_instance(factor_family_alias)
        factors = factor_family.get_factors()
        factor = next((f for f in factors if f.name == factor_name), None)
        if not factor:
            return jsonify({'error': '未找到因子'}), 404

        product = next((p for p in tester.products if p.name == product_name), None)
        if not product:
            return jsonify({'error': '未找到产品'}), 404

        # 收益率缓存目录
        cache_dir_ic = Path('../data/cache/ic')
        cache_dir_return = Path('../data/cache/return')
        cache_dir_return.mkdir(parents=True, exist_ok=True)

        # 缓存键：产品 + 时间范围（开始/结束时间）
        start_date_str = str(tester.start_date).replace(':', '-').replace(' ', '_')
        end_date_str = str(tester.end_date).replace(':', '-').replace(' ', '_')
        
        sorted_paths = sorted(paths)
        paths_hash = hashlib.md5(str(sorted_paths).encode()).hexdigest()
        cache_file_1 = cache_dir_ic / f"{paths_hash}_{factor.alias}_{return_freq}_{start_date_str}_{end_date_str}.pkl"
        cache_file_2 = cache_dir_return / f"{product.alias}_{return_freq}_{start_date_str}_{end_date_str}.pkl"
        cache_file_1_exists = cache_file_1.exists()
        cache_file_2_exists = cache_file_2.exists()

        series = None
        if not re_calc and cache_file_1_exists:
            with open(cache_file_1, 'rb') as f:
                _, _, _, return_freq_cache, returns_table, start_date_cache, end_date_cache = pickle.load(f)
                if return_freq_cache == return_freq \
                    and start_date_cache == tester.start_date \
                    and end_date_cache == tester.end_date:
                    series = returns_table[product].dropna()
                else:
                    re_calc = True
        elif not re_calc and cache_file_2_exists:
            with open(cache_file_2, 'rb') as f:
                returns_table, return_freq_cache, start_date_cache, end_date_cache = pickle.load(f)
                if return_freq_cache == return_freq \
                    and start_date_cache == tester.start_date \
                    and end_date_cache == tester.end_date:
                    if hasattr(returns_table, 'columns') and product in returns_table.columns:
                        series = returns_table[product].dropna()
                    else:
                        import pandas as pd
                        assert isinstance(returns_table, pd.Series), "缓存数据格式错误，预期为 DataFrame 或 Series"
                        series = returns_table.dropna()
                else:
                    re_calc = True
        if re_calc or (not cache_file_1_exists and not cache_file_2_exists) or series is None:
            factor.clear()
            factor.products = set([product])
            series = factor.calc_returns(return_freq=(None if return_freq == 'N' else return_freq))
            with open(cache_file_2, 'wb') as f:
                pickle.dump((series, return_freq, tester.start_date, tester.end_date), f)

        # 转换为时间戳和值
        import numpy as np
        import pandas as pd
        if isinstance(series.index, pd.MultiIndex):
            timestamps = series.index.get_level_values(-1).view(np.int64) // 10**6
        else:
            timestamps = series.index.view(np.int64) // 10**6
        values = series.values.tolist()
        values = [None if (isinstance(v, float) and pd.isna(v)) else v for v in values]

        return jsonify({'dates': timestamps.tolist(), 'values': values})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
@app.route('/get_price_series', methods=['POST'])
def get_price_series():
    import pandas as pd
    import numpy as np
    from pathlib import Path
    import pickle

    data = request.get_json()
    submission_id = data.get('submission_id')
    product_name = data.get('product')
    factor_dates = data.get('factor_dates')          # 因子时间戳列表（毫秒）
    adjusted = data.get('adjusted', False)          # 是否复权
    factor_family_alias = data.get('factor_family_alias')
    factor_name = data.get('factor_name')
    # 兼容旧调用，保留 start_date/end_date，但优先使用 factor_dates 的范围
    start_date = data.get('start_date')
    end_date = data.get('end_date')

    try:
        global factor_testers
        tester = next((t for t in factor_testers if t.alias == str(submission_id)), None)
        if not tester:
            return jsonify({'error': '未找到测试器实例'}), 404

        # 获取因子对象
        factor_family = get_factor_family_instance(factor_family_alias)
        factors = factor_family.get_factors()
        factor = next((f for f in factors if f.name == factor_name), None)
        if not factor:
            return jsonify({'error': '未找到因子'}), 404

        # 获取产品对象
        product = next((p for p in tester.products if p.name == product_name), None)
        if not product:
            return jsonify({'error': '未找到产品'}), 404

        # 根据因子时间戳确定价格数据的时间范围
        assert factor_dates
        factor_idx = pd.to_datetime(factor_dates, unit='ms')
        start_date = factor_idx.min().strftime('%Y-%m-%d')
        end_date = factor_idx.max().strftime('%Y-%m-%d')

        # 获取价格数据（原始频率）
        raw_df = product.get_price_data(start_date, end_date, adjusted=adjusted)

        if raw_df is None or raw_df.empty:
            return jsonify({'error': '无价格数据'}), 404

        required = ['OPEN', 'HIGH', 'LOW', 'CLOSE'] if not adjusted else ['OPEN_ADJUSTED', 'HIGH_ADJUSTED', 'LOW_ADJUSTED', 'CLOSE_ADJUSTED']
        for col in required:
            if col not in raw_df.columns:
                return jsonify({'error': f'价格数据缺少列: {col}'}), 500

        # 确保索引为 DatetimeIndex
        if not isinstance(raw_df.index, pd.DatetimeIndex):
            raw_df.index = pd.to_datetime(raw_df.index.get_level_values(-1))

        # 对齐到因子时间点
        # 构建因子时间序列
        # 将因子时间戳转换为 pandas DatetimeIndex（假设为本地时区，无时区信息）
        factor_idx = pd.to_datetime(factor_dates, unit='ms')
        
        # 确保 raw_df 索引为 DatetimeIndex（可能带时区），将其转换为无时区的本地时间，以便与 factor_idx 对齐
        if raw_df.index.tz is not None:
            # 转换为本地无时区时间（假设 raw_df 索引时区与系统本地一致）
            raw_df.index = raw_df.index.tz_convert(None)
        
        # 构建区间：每个因子时间点作为右边界，左边界为上一个因子时间点（第一个左边界为数据开始）
        bins = factor_idx.union([raw_df.index.min()])  # 添加数据开始时间
        bins = bins.sort_values()
        # 使用 cut 将价格数据分到对应的区间（右闭？需要仔细）
        # 我们希望区间为 (left, right] 即包含右端点，左开右闭
        # 使用 pd.cut 的 right=True 参数
        labels = factor_idx  # 区间右端点作为标签
        # 将 raw_df 索引分到区间
        # 注意：pd.cut 要求 bins 严格递增，且 left 边界可能小于最小值，我们手动处理
        # 先创建区间索引
        intervals = pd.IntervalIndex.from_arrays(bins[:-1], bins[1:], closed='right')
        # 为每个价格时间点找到所属区间
        bin_indices = intervals.get_indexer(raw_df.index)
        # 过滤出属于有效区间的点（-1表示不在任何区间）
        mask = bin_indices >= 0
        raw_filtered = raw_df[mask]
        bin_indices = bin_indices[mask]
        
        # 分组聚合
        def agg_func(group):
            return pd.Series({
                'OPEN': group[required[0]].iloc[0],      # 区间内第一笔 open
                'HIGH': group[required[1]].max(),
                'LOW': group[required[2]].min(),
                'CLOSE': group[required[3]].iloc[-1]    # 区间内最后一笔 close
            })
        
        # 按 bin_indices 分组
        grouped = raw_filtered.groupby(bin_indices)
        ohlc = grouped.apply(agg_func).reindex(range(len(factor_idx)))
        ohlc = ohlc.replace({np.nan: None})
        # 将索引替换为因子时间点
        ohlc.index = factor_idx
        timestamps = ohlc.index.astype(np.int64) // 10**6

        return jsonify({
            'dates': factor_dates,  # timestamps.tolist()
            'OPEN': ohlc['OPEN'].tolist(),
            'HIGH': ohlc['HIGH'].tolist(),
            'LOW': ohlc['LOW'].tolist(),
            'CLOSE': ohlc['CLOSE'].tolist()
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/run_group_test', methods=['POST'])
def run_group_test():
    import pandas as pd
    data = request.get_json()
    submission_id = data.get('submission_id')
    factor_alias = data.get('factor_alias')
    n_groups = data.get('n_groups', 5)
    fee = data.get('fee', 0.0)  # 手续费率，暂未使用
    start_date = data.get('start_date')
    end_date = data.get('end_date')
    
    try:
        global factor_testers
        tester = next((t for t in factor_testers if t.alias == str(submission_id)), None)
        if not tester:
            return jsonify({'success': False, 'error': '未找到测试器实例'}), 404
        
        # 查找因子
        factor = next((f for f in tester.factors if f.alias == factor_alias), None)
        if not factor:
            return jsonify({'success': False, 'error': f'未找到因子 {factor_alias}'}), 404
        
        # 处理时间范围时区
        time_range = None
        if start_date and end_date:
            # 获取 tester 时间的时区（如果存在）
            tz = None
            if hasattr(tester.start_date, 'tz') and tester.start_date.tz is not None:
                tz = tester.start_date.tz
            start_dt = pd.to_datetime(start_date)
            end_dt = pd.to_datetime(end_date)
            if tz:
                start_dt = start_dt.tz_localize(tz)
                end_dt = end_dt.tz_localize(tz)
            time_range = (start_dt, end_dt)
        
        # 调用分组测试（不使用绘图）
        _, returns_dict, report_df = tester.test_by_group(
            factors=factor,
            n_groups=n_groups,
            time_range=time_range,
            plot_flag=False,
            save_plot=False,
            plot_show=False
        )
        
        # 提取时间点的辅助函数（处理可能的元组索引）
        def extract_time(key):
            if isinstance(key, tuple):
                # 假设时间在元组的最后一个位置
                return key[-1]
            return key
        
        # 收集所有唯一的时间点
        all_keys = set()
        for group_returns in returns_dict.values():
            all_keys.update(group_returns.keys())
        time_points = sorted(set(extract_time(k) for k in all_keys))
        
        # 构建每个分组的累积收益序列
        groups_data = []
        for group_idx in range(n_groups):
            group_returns = returns_dict.get(group_idx, {})
            # 建立时间到收益的映射
            time_ret_map = {}
            for key, ret in group_returns.items():
                t = extract_time(key)
                time_ret_map[t] = ret
            cum_returns = []
            timestamps = []
            cum = 1.0
            for t in time_points:
                ret = time_ret_map.get(t, 0.0)
                cum *= (1 + ret)
                cum_returns.append(cum)
                timestamps.append(int(t.timestamp() * 1000))  # 毫秒时间戳
            groups_data.append({
                'name': f'Group {group_idx+1}',
                'timestamps': timestamps,
                'cumulative_returns': cum_returns
            })
        
        # 统计指标
        metrics = {}
        if not report_df.empty:
            metrics = report_df.to_dict(orient='index')
        
        return jsonify({
            'success': True,
            'groups': groups_data,
            'metrics': metrics,
            'n_groups': n_groups
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

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
    
    # 启动一个线程，延时1秒后打开浏览器（等待服务器完全启动）
    def open_browser():
        time.sleep(1)
        webbrowser.open(url)
    
    threading.Thread(target=open_browser, daemon=True).start()
    
    app.run(host='localhost', port=port, debug=False, use_reloader=False)
    print("服务器已关闭。")

if __name__ == '__main__':
    run_flask_server(port=8000, directory='.')