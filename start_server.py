import os, threading, webbrowser, time, sys, importlib
from pathlib import Path

# When running under the VS Code debugger (pydevd.settrace with
# patch_multiprocessing=True), multiprocessing.resource_tracker is
# started. At process exit, the tracker's cleanup triggers a debugger
# breakpoint inside <string> bytecode.  Since this Flask app does not
# use multiprocessing shared resources, neuter the resource tracker
# early so it never starts.
try:
    from multiprocessing import resource_tracker as _rt
    _rt.register = _rt.unregister = _rt.ensure_running = lambda *a, **kw: None
    if hasattr(_rt, '_resource_tracker'):
        _rt._resource_tracker._pid = None  # type: ignore[reportAttributeAccessIssue]
except Exception:
    pass

from flask import request, jsonify, session
from waitress import serve
from server import create_app
from tools.data.account_manage import accounts_lock, load_accounts
from server.services.session_runtime import current_user
from tools.data.cache.IdleResourceManager import IdleResourceManager
import settings
from server.services.logging_config import configure_logging

configure_logging(settings.logger_dir_path_default)
app = create_app()


# ═══════════════════════════════════════════════════════════════════
# 热插拔：文件监控 + 自动 reload（生产模式）
# ═══════════════════════════════════════════════════════════════════

# 需要监控的项目模块前缀（改这些模块时自动 reload）
_WATCH_PREFIXES = ('Factors.', 'tools.', 'server.', 'sources.')
# 精确匹配的模块名（不以 '.' 为前缀的顶层模块）
_WATCH_EXACT = {'settings'}

# 不 reload 的模块（有复杂全局状态，reload 会出问题）
_SKIP_RELOAD = {
    'start_server',          # 自己
    'tools.data.types.base',
    'tools.data.cache.IdleResourceManager',
}
# 前缀匹配 — 整个子树都不参与热重载（单元测试勿 reload）
_SKIP_RELOAD_PREFIXES = ('tests.',)

def _is_skip_reload(name: str) -> bool:
    if name in _SKIP_RELOAD:
        return True
    return any(name.startswith(p) for p in _SKIP_RELOAD_PREFIXES)

def _get_watched_modules() -> dict[str, float]:
    """返回所有可监控模块及其源文件的当前 mtime。"""
    result = {}
    for name, mod in sorted(sys.modules.items()):
        if _is_skip_reload(name):
            continue
        if name not in _WATCH_EXACT and not any(name.startswith(p) for p in _WATCH_PREFIXES):
            continue
        f = getattr(mod, '__file__', None)
        if f and os.path.isfile(f):
            result[name] = os.path.getmtime(f)
    return result


def _reload_changed_modules(old_mtimes: dict[str, float]) -> list[str]:
    """检测变化的模块并 reload（按依赖顺序，顶层先于底层）。返回 reload 的模块名列表。"""
    reloaded = []
    # 找出所有变化的模块
    changed = []
    for name, mod in sorted(sys.modules.items()):
        if _is_skip_reload(name):
            continue
        if name not in _WATCH_EXACT and not any(name.startswith(p) for p in _WATCH_PREFIXES):
            continue
        f = getattr(mod, '__file__', None)
        if not f or not os.path.isfile(f):
            continue
        new_mtime = os.path.getmtime(f)
        if name not in old_mtimes or new_mtime > old_mtimes[name] + 0.01:
            changed.append(name)

    if not changed:
        return reloaded

    # 按 import 深度排序：被依赖的（更底层的）先 reload
    def _depth(n: str) -> int:
        return n.count('.')

    changed.sort(key=_depth)  # Factors.MmRet (1层) < tools.factors.FactorExpr (3层)

    for name in changed:
        try:
            importlib.reload(sys.modules[name])
            reloaded.append(name)
        except Exception as e:
            print(f"[hot-reload] ⚠ reload {name} 失败: {e}")

    return reloaded


def _start_hot_reload_watcher(interval: float = 2.0):
    """启动后台线程，定时扫描模块变化并自动 reload。"""
    mtimes = _get_watched_modules()

    def _watch_loop():
        nonlocal mtimes
        while True:
            time.sleep(interval)
            try:
                new_mtimes = _get_watched_modules()
                reloaded = _reload_changed_modules(mtimes)
                if reloaded:
                    print(f"[hot-reload] ✓ reloaded: {', '.join(reloaded)}")
                mtimes = new_mtimes
            except Exception as e:
                print(f"[hot-reload] ⚠ watcher error: {e}")

    t = threading.Thread(target=_watch_loop, daemon=True, name='hot-reload-watcher')
    t.start()
    print("[hot-reload] 文件监控已启动 (scan interval: {}s)".format(interval))


@app.route('/shutdown', methods=['POST'])
def shutdown():
    username = current_user()
    if not username:
        return jsonify({'success': False, 'error': '请先登录'}), 401
    with accounts_lock:
        accounts = load_accounts()
    acct = next((a for a in accounts if a['username'] == username), None)
    if not acct or not acct.get('is_admin', False):
        return jsonify({'success': False, 'error': '无权限'}), 403
    # waitress 没有内置 shutdown 机制，直接退出进程
    threading.Thread(target=lambda: (time.sleep(0.5), os._exit(0))).start()
    return '', 200


def _get_lan_ip() -> str | None:
    """获取本机局域网 IP（优先取非回环、非 link-local 的第一个 inet 地址）。"""
    import socket
    try:
        # 用 UDP 小技巧获取对外出口 IP（不产生实际流量）
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.0)
        s.connect(('8.8.8.8', 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def run_flask_server(port=8000, directory='.'):
    os.chdir(directory)
    url = f"http://localhost:{port}/"
    lan_ip = _get_lan_ip()
    print(f"Serving Flask on {url} from {os.path.abspath(directory)}")
    if lan_ip:
        print(f"  局域网访问: http://{lan_ip}:{port}/")

    # 启动全局空闲资源清理守护线程（idle 10s 后释放）
    IdleResourceManager.get_instance().start(idle_timeout=10, scan_interval=5)
    print("IdleResourceManager started.")

    use_werkzeug_reloader = os.environ.get("FACTORTESTER_WERKZEUG_RELOADER", "1") != "0"
    debug_reloader_child = (
        os.environ.get("FLASK_DEBUG") != "1"
        or not use_werkzeug_reloader
        or os.environ.get("WERKZEUG_RUN_MAIN") == "true"
    )
    if os.environ.get("DERIVED_ARTIFACT_AUTO_ENSURE", "1") == "1" and debug_reloader_child:
        from sources import load_all_sources
        from tools.data.artifacts import start_background_ensure

        load_all_sources()
        start_background_ensure()
        print("Derived artifact ensure started in background.")

    # 开发模式：使用 Flask 内置服务器。默认保留 Werkzeug reloader，
    # 这样通过 7998 启动的 worktree 子进程仍会出现在 VS Code/debugpy
    # call stack 中；需要排查热重载时可设 FACTORTESTER_WERKZEUG_RELOADER=0。
    if os.environ.get('FLASK_DEBUG') == '1':
        reload_status = "已启用" if use_werkzeug_reloader else "已关闭"
        print(f"开发模式 (VS Code debugger, Werkzeug reloader {reload_status})")
        # debugpy owns exception handling; Werkzeug's debugger otherwise pauses
        # on normal WSGI iterator shutdown (GeneratorExit) when a client leaves.
        app.run(
            host='0.0.0.0',
            port=port,
            debug=True,
            use_reloader=use_werkzeug_reloader,
            use_debugger=False,
        )
    else:
        wt = settings.WAITRESS_THREADS
        print(f"生产模式 (waitress, threads={wt}, platform={sys.platform})")
        # 启动热插拔文件监控
        _start_hot_reload_watcher(interval=3.0)
        def open_browser():
            time.sleep(1)
            webbrowser.open(url)
        threading.Thread(target=open_browser, daemon=True).start()
        serve(app, host='0.0.0.0', port=port, threads=wt)
    print("服务器已关闭。")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    run_flask_server(port=args.port, directory='.')
