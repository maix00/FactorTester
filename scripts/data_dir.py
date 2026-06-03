"""
统一的数据目录解析模块。

规则：
- 向上查找包含 .workspace/ 子目录的祖先目录，那就是 Codes/（feat 根）。
- 无论从 feat 还是子 worktree（.workspace/fix/...）调用，最终都定位到 Codes/。
- data/ 目录 = Codes/../data/（即与 Codes/ 平级的 data/）。
- 若未找到 .workspace/ 标记，回退到环境变量 FT_DATA_DIR，再回退到相对于本文件的路径。
"""
import os as _os


def _find_feat_root(start_dir: str) -> str | None:
    """从 start_dir 向上查找包含 .workspace/ 子目录的最近祖先目录（即 Codes/ feat 根）。"""
    current = _os.path.abspath(start_dir)
    while True:
        marker = _os.path.join(current, '.workspace')
        if _os.path.isdir(marker):
            return current
        parent = _os.path.dirname(current)
        if parent == current:  # 到达文件系统根
            return None
        current = parent


def get_data_dir() -> str:
    """返回统一的 data/ 目录绝对路径。

    优先级：
    1. 环境变量 FT_DATA_DIR
    2. 向上查找 .workspace/ 目录，data = <feat_root>/../data/
    3. 相对于本文件的 ../../data/（即 Codes/../data/）
    """
    env_dir = _os.environ.get('FT_DATA_DIR')
    if env_dir:
        return env_dir

    root = _find_feat_root(_os.path.dirname(__file__))
    if root is not None:
        return _os.path.normpath(_os.path.join(root, '..', 'data'))

    # 最终回退：本文件在 scripts/ 下，data/ 在 ../../data/
    return _os.path.normpath(_os.path.join(_os.path.dirname(__file__), '..', '..', 'data'))


# 模块级常量，方便直接 import
DATA_DIR = get_data_dir()
