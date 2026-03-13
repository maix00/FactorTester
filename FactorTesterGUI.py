# factor_gui.py
from flask import Flask, render_template_string, request, jsonify
import threading

# 复制您提供的 HTML 模板
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>FactorFamily Tester GUI</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background: #f8fafc; }
        .container { max-width: 600px; margin-top: 40px; }
        .btn { min-width: 120px; }
        #output { white-space: pre-wrap; background: #f0f0f0; padding: 16px; border-radius: 6px; min-height: 80px; margin-top: 24px; font-size: 1.05em; }
        h2 { margin-bottom: 32px; }
    </style>
</head>
<body>
    <div class="container shadow-sm bg-white p-4 rounded">
        <h2 class="text-center text-primary">FactorFamily Tester GUI</h2>
        <div class="d-flex flex-wrap justify-content-center gap-3 mb-3">
            <button class="btn btn-outline-primary" onclick="runStep('sift')">1. 筛选产品</button>
            <button class="btn btn-outline-success" onclick="runStep('calc_factor')">2. 计算因子</button>
            <button class="btn btn-outline-warning" onclick="runStep('calc_ic')">3. 计算IC</button>
            <button class="btn btn-outline-info" onclick="runStep('test_by_group')">4. 分组测试</button>
            <button class="btn btn-primary" onclick="runStep('all')">全部步骤</button>
        </div>
        <div id="output"></div>
    </div>
    <script>
        function runStep(step) {
            document.getElementById('output').innerText = '正在运行: ' + step + ' ...';
            fetch('/run_step', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({step: step})
            }).then(r => r.json()).then(data => {
                document.getElementById('output').innerText = data.result;
            });
        }
    </script>
</body>
</html>
"""

app = Flask(__name__)

# 用于保存 FactorFamily 和 FactorTest 对象的全局缓存（线程内共享）
# 注意：Flask 在多线程环境下，这些全局变量需要妥善管理，简单场景下可用
tester_cache = {}
factor_family_ref = None

def set_objects(factor_family, factor_test):
    """由主脚本调用，将对象引用传入 Flask 应用"""
    global factor_family_ref, tester_cache
    factor_family_ref = factor_family
    tester_cache['tester'] = factor_test

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/run_step', methods=['POST'])
def run_step():
    step = request.json.get('step')
    output = ""
    # 使用全局变量中的对象
    ff = factor_family_ref
    tester = tester_cache.get('tester')
    if ff is None or tester is None:
        return jsonify({'result': 'FactorFamily 或 FactorTest 未初始化，请先调用 set_objects()'})

    # ... 原来的处理逻辑，但需要调整：
    # 1. 移除 global factor_family, tester_cache 的重复声明（已在函数外定义）
    # 2. 确保使用的变量名一致（ff, tester）
    # 3. 注意 default_test_start_date 等变量需在别处定义或从对象获取
    try:
        if step == 'sift':
            # 假设 tester 有 sift_product_by_category 方法
            tester.sift_product_by_category(categories=None)
            output = f"筛选产品完成，产品数量: {len(tester.products)}"
        elif step == 'calc_factor':
            factors = ff.get_factors()
            tester.calc_factor(factors)
            tester_cache['factors'] = factors
            output = "计算因子完成。"
        elif step == 'calc_ic':
            factors = tester_cache.get('factors')
            if factors is None:
                output = "请先执行计算因子。"
            else:
                ic_df, ic_stats_df = tester.calc_ic(factors=factors)
                output = f"IC计算完成。\nIC统计:\n{ic_stats_df.head()}"
        elif step == 'test_by_group':
            factors = tester_cache.get('factors')
            if factors is None:
                output = "请先执行计算因子。"
            else:
                _, _, report_df = tester.test_by_group(factors=factors)
                output = f"分组测试完成。\n报告:\n{report_df.head()}"
        elif step == 'all':
            # 假设 tester 有 sift_product_by_category 等方法
            tester.sift_product_by_category(categories=None)
            factors = ff.get_factors()
            tester.calc_factor(factors)
            ic_df, ic_stats_df = tester.calc_ic(factors=factors)
            _, _, report_df = tester.test_by_group(factors=factors)
            output = f"全部步骤完成。\n产品数量: {len(tester.products)}\nIC统计:\n{ic_stats_df.head()}\n报告:\n{report_df.head()}"
        else:
            output = "未知步骤。"
    except Exception as e:
        output = f"运行出错: {str(e)}"

    return jsonify({'result': output})

def start_gui(host='127.0.0.1', port=5000, debug=False, use_reloader=False, threaded=True):
    """
    启动 Flask 服务器。
    如果需要在后台线程运行，请设置 threaded=True（但必须禁用 reloader）。
    """
    if threaded:
        # 在后台线程中启动，必须禁用 reloader
        threading.Thread(target=lambda: app.run(host=host, port=port, debug=debug, use_reloader=False), daemon=True).start()
        print(f"Flask GUI 已在后台线程启动，访问 http://{host}:{port}")
    else:
        # 在主线程中启动，可以启用 reloader（如果 debug=True）
        app.run(host=host, port=port, debug=debug, use_reloader=use_reloader)

import os
import importlib.util

FACTOR_DIR = './Factors'

def list_factor_files():
    files = []
    for fname in os.listdir(FACTOR_DIR):
        if fname.endswith('.py') and not fname.startswith('__'):
            files.append(fname[:-3])  # 去掉.py
    return files

def import_factor_class(factor_name):
    file_path = os.path.join(FACTOR_DIR, f"{factor_name}.py")
    spec = importlib.util.spec_from_file_location(factor_name, file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    factor_class = getattr(module, factor_name)
    return factor_class

@app.route('/list_factors')
def list_factors():
    factors = list_factor_files()
    return jsonify({'factors': factors})

@app.route('/run_factor_test', methods=['POST'])
def run_factor_test():
    factor_name = request.json.get('factor')
    try:
        factor_class = import_factor_class(factor_name)
        factor_instance = factor_class()
        # 假设 factor_instance 有 test() 方法
        result = factor_instance.test()
        return jsonify({'result': f"{factor_name} 测试结果:\n{result}"})
    except Exception as e:
        return jsonify({'result': f"运行出错: {str(e)}"})