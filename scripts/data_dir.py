"""
统一的数据目录解析模块。

规则：
- 向上查找 .git 文件/目录，跳过 .workspace/ 下的嵌套 worktree，找到仓库根（feat/master）。
- .settings 文件 **仅** 位于仓库根的上一层目录。
- 数据目录、artifact 目录等路径完全由 .settings 决定，不做 fallback。
"""
import os as _os
import json as _json
from pathlib import Path as _Path


_SETTINGS_FILE = '.settings'


def _find_repo_root(start_dir: str) -> str:
    """从 start_dir 向上查找仓库（主 worktree）根目录。

    跳过 .workspace/ 下的嵌套 worktree（如 .workspace/fix/issue-N-xxx/），
    最终定位到 feat/master 等主 worktree 根目录。
    """
    current = _os.path.abspath(start_dir)
    while True:
        git_marker = _os.path.join(current, '.git')
        if _os.path.isdir(git_marker) or _os.path.isfile(git_marker):
            # 找到了 git 工作树根目录 — 确保不是嵌套在 .workspace/ 下的
            if '.workspace' not in _os.path.normpath(current).split(_os.sep):
                return current
            # 在 .workspace/ 下，继续向上跳过嵌套 worktree
        parent = _os.path.dirname(current)
        if parent == current:
            raise FileNotFoundError(
                "Cannot locate repo root: no .git marker found "
                f"above {start_dir!r}"
            )
        current = parent


def _load_settings() -> dict:
    """从仓库根上一层目录加载 .settings 文件。

    .settings 路径 = <repo_root>/../.settings
    """
    root = _find_repo_root(_os.path.dirname(__file__))
    settings_path = _os.path.join(_os.path.dirname(root), _SETTINGS_FILE)
    if not _os.path.isfile(settings_path):
        raise FileNotFoundError(
            f"{_SETTINGS_FILE} not found at {settings_path!r}. "
            f"Create it with at least {{\"data_dir\": \"...\"}}"
        )
    with open(settings_path, 'r', encoding='utf-8') as f:
        return _json.load(f)


def load_runtime_settings() -> dict:
    """Return repository runtime settings without exposing lookup details."""
    return _load_settings()


def get_feat_root() -> str:
    """返回仓库（主 worktree）根目录绝对路径。"""
    return _find_repo_root(_os.path.dirname(__file__))


# ---- 模块级常量，一次性解析 ----

FEAT_ROOT = get_feat_root()
_settings = _load_settings()
DATA_DIR = _os.path.abspath(_settings['data_dir'])


CACHE_DB_PATH = _Path(_settings['sqlite_db_path']).expanduser().resolve()
