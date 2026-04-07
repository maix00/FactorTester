# utils/path_manager.py
import os
import json
from pathlib import Path

CONFIG_FILE = os.path.expanduser('~/.factor_tester_config.json')

def _save_data_root(path: str):
    """保存用户选择的数据根目录到配置文件"""
    config = {}
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
    config['data_root'] = path
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

def _load_data_root() -> str | None:
    """从配置文件加载用户选择的数据根目录"""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
            return config.get('data_root')
    return None

def get_data_root() -> str:
    """
    返回数据根目录的绝对路径。
    优先级：
    1. 环境变量 FACTOR_DATA_DIR
    2. 配置文件 ~/.factor_tester_config.json 中的 data_root
    3. 用户主目录下的 factor_data
    4. 开发环境：Codes 的上一级目录中的 data
    """
    # 1. 环境变量
    env_dir = os.environ.get('FACTOR_DATA_DIR')
    if env_dir and os.path.exists(env_dir):
        return env_dir

    # 2. 配置文件
    config_root = _load_data_root()
    if config_root and os.path.exists(config_root):
        return config_root

    # 3. 用户主目录下的 factor_data
    home_data = Path.home() / 'factor_data'
    if home_data.exists():
        return str(home_data)

    # 4. 开发环境
    current_file = Path(__file__).resolve()
    codes_dir = current_file.parent.parent
    data_dir = codes_dir.parent / 'data'
    if data_dir.exists():
        return str(data_dir)

    # 都没找到，抛出异常
    raise FileNotFoundError(
        "无法找到数据根目录。请通过环境变量 FACTOR_DATA_DIR 或配置文件设置。"
    )

def set_data_root(path: str):
    """设置数据根目录（保存到配置文件）"""
    if not os.path.exists(path):
        raise FileNotFoundError(f"路径不存在: {path}")
    _save_data_root(path)

def get_data_file_path(relative_path: str) -> str:
    root = get_data_root()
    full_path = os.path.join(root, relative_path)
    if not os.path.exists(full_path):
        raise FileNotFoundError(f"数据文件不存在: {full_path}")
    return full_path

def get_data_dir(subdir: str) -> str:
    root = get_data_root()
    return os.path.join(root, subdir)
    
# 因子函数目录
def get_factors_func_dir() -> str:
    """返回用户指定的因子函数目录（存放 .py 因子定义文件）"""
    # 1. 环境变量
    env_dir = os.environ.get('FACTOR_FUNCTIONS_DIR')
    if env_dir and os.path.exists(env_dir):
        return env_dir
    # 2. 配置文件
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
            func_dir = config.get('factors_func_dir')
            if func_dir and os.path.exists(func_dir):
                return func_dir
    # 3. 开发环境默认
    default_dir = os.path.join(Path(__file__).resolve().parent.parent, 'Factors')
    if os.path.exists(default_dir):
        return str(default_dir)
    raise FileNotFoundError("未找到因子函数目录，请设置环境变量 FACTOR_FUNCTIONS_DIR 或通过配置文件指定")

def set_factors_func_dir(path: str):
    """保存用户指定的因子函数目录到配置文件"""
    config = {}
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
    config['factors_func_dir'] = path
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

def get_log_dir() -> str:
    """返回日志目录（位于数据根目录下的 logs）"""
    data_root = get_data_root()
    log_dir = os.path.join(data_root, 'logs')
    os.makedirs(log_dir, exist_ok=True)
    return log_dir

def get_log_file() -> str:
    return os.path.join(get_log_dir(), 'factor_tester.log')

def get_cache_dir() -> str:
    """返回缓存根目录"""
    data_root = get_data_root()
    cache_dir = os.path.join(data_root, 'cache')
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir

def get_ic_cache_dir() -> str:
    return os.path.join(get_cache_dir(), 'ic_cache')

def get_factor_cache_dir() -> str:
    return os.path.join(get_cache_dir(), 'factor_cache')

def get_user_factors_data_dir() -> str:
    """返回用户可写的因子数据目录（位于数据根目录下的 Factors）"""
    data_root = get_data_root()
    user_factors = os.path.join(data_root, 'Factors')
    os.makedirs(user_factors, exist_ok=True)
    return user_factors