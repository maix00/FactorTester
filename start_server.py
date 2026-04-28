import os, threading, webbrowser, time
from flask import request, jsonify, session
from server import create_app
from server.shared import _current_user, _load_accounts, _accts_lock

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

    def open_browser():
        time.sleep(1)
        webbrowser.open(url)

    threading.Thread(target=open_browser, daemon=True).start()
    app.run(host='localhost', port=port, debug=False, use_reloader=False)
    print("服务器已关闭。")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    run_flask_server(port=args.port, directory='.')
