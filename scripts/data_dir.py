"""
统一的数据目录解析模块。

规则：
- 向上查找包含 .workspace/ 子目录的祖先目录，那就是 Codes/（feat 根）。
- 无论从 feat 还是子 worktree（.workspace/fix/...）调用，最终都定位到 Codes/。
- data/ 目录 = Codes/../data/（即与 Codes/ 平级的 data/）。
- 若未找到 .workspace/ 标记，回退到环境变量 FT_DATA_DIR，再回退到相对于本文件的路径。
"""
import os as _os
import json as _json


_SETTINGS_FILE = '.settings'


def _load_settings(start_dir: str) -> dict | None:
    """从 start_dir 向上查找 .settings 文件，返回解析后的 dict。"""
    current = _os.path.abspath(start_dir)
    while True:
        candidate = _os.path.join(current, _SETTINGS_FILE)
        if _os.path.isfile(candidate):
            try:
                with open(candidate, 'r', encoding='utf-8') as f:
                    return _json.load(f)
            except (OSError, _json.JSONDecodeError):
                return None
        parent = _os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def _find_feat_root(start_dir: str) -> str | None:
    """从 start_dir 向上查找包含 .workspace/fix/ 子目录的最近祖先目录（即 Codes/ feat 根）。
    
    排除 worktree 自身：worktree 下的 .workspace/ 只有 flask-manager 等辅助目录,
    没有 fix/ 子目录，因此不会被误判为 feat 根。
    """
    current = _os.path.abspath(start_dir)
    while True:
        marker = _os.path.join(current, '.workspace')
        if _os.path.isdir(marker) and _os.path.isdir(_os.path.join(marker, 'fix')):
            return current
        parent = _os.path.dirname(current)
        if parent == current:  # 到达文件系统根
            return None
        current = parent


def get_data_dir() -> str:
    """返回统一的 data/ 目录绝对路径。

    优先级：
    1. .settings 文件中的 data_dir（向上查找）
    2. 环境变量 FT_DATA_DIR
    3. 向上查找 .workspace/ 目录，data = <feat_root>/../data/
    4. 相对于本文件的 ../../data/（即 Codes/../data/）
    """
    # 优先级 1：.settings 文件
    settings = _load_settings(_os.path.dirname(__file__))
    if settings and 'data_dir' in settings:
        candidate = settings['data_dir']
        if candidate:
            return _os.path.abspath(candidate)

    # 优先级 2：环境变量
    env_dir = _os.environ.get('FT_DATA_DIR')
    if env_dir:
        return env_dir

    # 优先级 3：feat root 检测
    root = _find_feat_root(_os.path.dirname(__file__))
    if root is not None:
        return _os.path.normpath(_os.path.join(root, '..', 'data'))

    # 优先级 4：最终回退
    return _os.path.normpath(_os.path.join(_os.path.dirname(__file__), '..', '..', 'data'))


# 模块级常量，方便直接 import
DATA_DIR = get_data_dir()


def _get_cache_db_dir() -> str:
    """返回 sqlite 数据库文件所在目录的绝对路径。

    优先级：
    1. .settings 文件中的 sqlite_dir（向上查找）
    2. 默认 DATA_DIR/cache/localdata（与 fix/issue-110 的 CACHE_DIR 一致）
    """
    settings = _load_settings(_os.path.dirname(__file__))
    if settings and 'sqlite_dir' in settings:
        candidate = settings['sqlite_dir']
        if candidate:
            return _os.path.abspath(candidate)

    return _os.path.join(DATA_DIR, 'cache', 'localdata')


CACHE_DB_DIR = _get_cache_db_dir()
CACHE_DB_PATH = _os.path.join(CACHE_DB_DIR, 'unifieddata.sqlite')
