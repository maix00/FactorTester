import os, threading, webbrowser, time
from flask import request, jsonify, session
from waitress import serve
from server import create_app
from server.shared import _current_user, _load_accounts, _accts_lock
from tools.base.IdleResourceManager import IdleResourceManager

app = create_app()

@app.route('/shutdown', methods=['POST'])
def shutdown():
    username = _current_user()
    if not username:
        return jsonify({'success': False, 'error': '请先登录'}), 401
    with _accts_lock:
        accounts = _load_accounts()
    acct = next((a for a in accounts if a['username'] == username), None)
    if not acct or not acct.get('is_admin', False):
        return jsonify({'success': False, 'error': '无权限'}), 403
    # waitress 没有内置 shutdown 机制，直接退出进程
    threading.Thread(target=lambda: (time.sleep(0.5), os._exit(0))).start()
    return '', 200


def run_flask_server(port=8000, directory='.'):
    os.chdir(directory)
    url = f"http://localhost:{port}/"
    print(f"Serving Flask on {url} from {os.path.abspath(directory)}")

    # 启动全局空闲资源清理守护线程（idle 10s 后释放）
    IdleResourceManager.get_instance().start(idle_timeout=10, scan_interval=5)
    print("IdleResourceManager started.")

    def open_browser():
        time.sleep(1)
        webbrowser.open(url)

    threading.Thread(target=open_browser, daemon=True).start()
    print(f"服务器已启动 (waitress, threads=8)")
    serve(app, host='0.0.0.0', port=port, threads=8)
    print("服务器已关闭。")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    run_flask_server(port=args.port, directory='.')
