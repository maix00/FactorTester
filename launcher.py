#!/usr/bin/env python3
import os
import sys
import threading
import webbrowser
import time
import socket
import logging

from utils.path_manager import get_log_file, get_data_root, set_data_root, get_factors_func_dir, set_factors_func_dir

# 添加当前目录到 sys.path（打包后需要）
if getattr(sys, 'frozen', False):
    base_path = getattr(sys, '_MEIPASS', os.getcwd())
    sys.path.insert(0, base_path)

# 导入我们的路径管理器
try:
    from utils.path_manager import get_data_root, set_data_root
except ImportError:
    # 如果导入失败（比如首次运行还没有 utils），给出错误提示
    print("错误: 无法导入路径管理器")
    sys.exit(1)

# 配置日志
log_file = get_log_file()
logging.basicConfig(filename=log_file, level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

def ensure_data_root():
    """确保数据根目录存在，如果不存在则弹出对话框让用户选择"""
    try:
        root = get_data_root()
        logging.info(f"数据根目录已配置: {root}")
        return True
    except FileNotFoundError:
        # 数据根目录未配置，弹出选择对话框
        logging.warning("数据根目录未找到，弹出选择对话框")
        try:
            import tkinter as tk
            from tkinter import filedialog, messagebox
            root = tk.Tk()
            root.withdraw()  # 隐藏主窗口
            messagebox.showinfo("需要数据目录", 
                "请选择包含 sectors.csv 和 main_mink 等子目录的数据根目录。\n"
                "例如：/Users/你的用户名/Documents/GTHT/data")
            selected = filedialog.askdirectory(title="选择数据根目录")
            if selected:
                # 验证所选目录是否包含 sectors.csv
                if os.path.exists(os.path.join(selected, 'sectors.csv')):
                    set_data_root(selected)
                    logging.info(f"用户选择数据根目录: {selected}")
                    return True
                else:
                    messagebox.showerror("错误", "所选目录不包含 sectors.csv，请重新选择")
                    return ensure_data_root()  # 递归重试
            else:
                messagebox.showerror("错误", "未选择数据目录，应用将退出")
                return False
        except Exception as e:
            logging.error(f"无法打开对话框: {e}")
            return False
        
def ensure_factors_func_dir():
    try:
        get_factors_func_dir()
        return True
    except FileNotFoundError:
        # 弹窗让用户选择
        import tkinter as tk
        from tkinter import filedialog, messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo("需要因子函数目录", "请选择包含因子 .py 文件的目录（例如开发时的 Codes/Factors）")
        selected = filedialog.askdirectory(title="选择因子函数目录")
        if selected:
            set_factors_func_dir(selected)
            return True
        else:
            return False

def wait_for_port(port, host='localhost', timeout=5):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except (socket.timeout, ConnectionRefusedError):
            time.sleep(0.3)
    return False

def run_flask():
    try:
        from factor_server import app
        app.run(host='localhost', port=8000, debug=False, use_reloader=False, threaded=True)
    except Exception as e:
        logging.error(f"Flask 服务器启动失败: {e}", exc_info=True)

def main():
    logging.info("启动 launcher")

    # 确保数据根目录存在
    if not ensure_data_root():
        sys.exit(1)

    # 确保因子函数目录存在
    if not ensure_factors_func_dir():
        logging.error("因子函数目录未设置，应用将退出")
        sys.exit(1)

    # 启动 Flask 线程
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # 等待端口就绪
    if wait_for_port(8000, timeout=8):
        logging.info("端口 8000 已就绪，打开浏览器")
        webbrowser.open('http://localhost:8000')
    else:
        logging.error("端口 8000 未能在超时内就绪")
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("启动失败", "服务器未能启动，请查看日志：~/factor_tester.log")
            root.destroy()
        except:
            pass

    flask_thread.join()

if __name__ == '__main__':
    main()