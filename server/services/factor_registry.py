"""
FactorFamily 加载、缓存与失效管理。

三级缓存策略：
  1. _factor_family_cache       —— 公共因子（Factors/ 目录下的 .py 文件）全局单例缓存
  2. _custom_factor_cache       —— 自定义因子（用户目录 custom_factors/）按 (username, id) 缓存
  3. _chinese_names_cache       —— 因子的中文名（desc 属性）一次性加载缓存

核心函数：
  get_factor_family_instance()  加载因子族实例 → 先查公共因子缓存，再查自定义因子
  invalidate_factor_family_cache()  失效特定的或全部公共因子缓存
  invalidate_custom_factor_cache()  失效特定用户的或某用户全部的的自定义因子缓存
  get_factor_groups()           返回按前缀分组的因子名列表（Mm/Oi/Vl/Vp 等）
  factor_group_key()            从类名提取分组前缀（MmRet → Mm）
"""

from __future__ import annotations

import importlib.util
import os
import threading

from flask import session

from tools.factors.FactorFamily import FactorFamily
from server.services.user_storage import user_data_dir


_factor_family_cache: dict = {}
_factor_family_cache_lock = threading.Lock()
_custom_factor_cache: dict = {}
_custom_factor_cache_lock = threading.Lock()
_chinese_names_cache: dict = {}


def get_factor_family_instance(module_name, username: str | None = None):
    """Load a public FactorFamily first, then fall back to the current/user custom family."""
    with _factor_family_cache_lock:
        if module_name in _factor_family_cache:
            return _factor_family_cache[module_name]

    factors_dir = os.path.join(os.getcwd(), "Factors")
    module_path = os.path.join(factors_dir, f"{module_name}.py")
    if os.path.exists(module_path):
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is not None and spec.loader is not None:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            ff = getattr(module, module_name)()
            assert isinstance(ff, FactorFamily)
            with _factor_family_cache_lock:
                _factor_family_cache[module_name] = ff
            return ff

    if username is None:
        username = session.get('username')
    if username:
        custom_factor = get_custom_factor_instance(username, module_name)
        if custom_factor is not None:
            return custom_factor

        custom_dir = os.path.join(user_data_dir(username), 'custom_factors')
        if os.path.isdir(custom_dir):
            for filename in os.listdir(custom_dir):
                if not filename.endswith('.py'):
                    continue
                factor_id = os.path.splitext(filename)[0]
                custom_factor = get_custom_factor_instance(username, factor_id)
                if custom_factor is not None and custom_factor.__class__.__name__ == module_name:
                    return custom_factor

    raise ImportError(f"Cannot load factor '{module_name}' from '{module_path}'")


def _build_custom_factor_family(username: str, factor_id: str) -> FactorFamily | None:
    custom_path = os.path.join(user_data_dir(username), 'custom_factors', f'{factor_id}.py')
    if not os.path.exists(custom_path):
        return None

    module_name = f'_cf_{username}_{factor_id}'
    try:
        spec = importlib.util.spec_from_file_location(module_name, custom_path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            if isinstance(obj, type) and issubclass(obj, FactorFamily) and obj is not FactorFamily:
                return obj()
        return None
    except Exception:
        return None


def get_custom_factor_instance(username: str, factor_id: str) -> FactorFamily | None:
    cache_key = (username, factor_id)
    with _custom_factor_cache_lock:
        if cache_key in _custom_factor_cache:
            return _custom_factor_cache[cache_key]
    instance = _build_custom_factor_family(username, factor_id)
    if instance is not None:
        with _custom_factor_cache_lock:
            _custom_factor_cache[cache_key] = instance
    return instance


def invalidate_custom_factor_cache(username: str, factor_id: str | None = None):
    with _custom_factor_cache_lock:
        if factor_id is not None:
            _custom_factor_cache.pop((username, factor_id), None)
        else:
            keys_to_remove = [key for key in _custom_factor_cache if key[0] == username]
            for key in keys_to_remove:
                _custom_factor_cache.pop(key, None)


def invalidate_factor_family_cache(factor_name: str | None = None):
    with _factor_family_cache_lock:
        if factor_name:
            _factor_family_cache.pop(factor_name, None)
        else:
            _factor_family_cache.clear()


def _load_chinese_names(factors_dir):
    result = {}
    for filename in os.listdir(factors_dir):
        if not filename.endswith('.py'):
            continue
        name = os.path.splitext(filename)[0]
        try:
            factor_family = get_factor_family_instance(name)
            chinese_name = getattr(factor_family, 'desc', '') or getattr(factor_family, 'chinese_name', '') or ''
            result[name] = chinese_name
        except Exception:
            result[name] = ''
    return result


def get_chinese_names(factors_dir):
    if not _chinese_names_cache:
        _chinese_names_cache.update(_load_chinese_names(factors_dir))
    return _chinese_names_cache


def factor_group_key(name: str) -> str:
    group = ""
    upper_count = 0
    for char in name:
        if char.isupper():
            upper_count += 1
            if upper_count == 1:
                group += char
            elif upper_count == 2:
                break
        elif upper_count == 1:
            group += char
    return group if group else name


def get_factor_groups(factors_dir):
    factor_files = [filename for filename in os.listdir(factors_dir) if filename.endswith(".py")]
    factor_names = [os.path.splitext(filename)[0] for filename in factor_files]

    groups = {}
    for name in factor_names:
        group = factor_group_key(name)
        groups.setdefault(group, []).append(name)
    return groups, factor_names
