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
import tempfile
import threading

from flask import session

from tools.factors.FactorFamily import FactorFamily
from server.services.user_storage import user_data_dir
from server.modules.custom_factors.storage import load_factor_source, load_public_factor_source


_factor_family_cache: dict = {}
_factor_family_cache_lock = threading.Lock()
_custom_factor_cache: dict = {}
_custom_factor_cache_lock = threading.Lock()
_chinese_names_cache: dict = {}


def _build_factor_from_source(module_name: str, source_code: str) -> FactorFamily | None:
    if not source_code:
        return None
    tmpdir = tempfile.mkdtemp(prefix='factor_src_')
    tmpfile = os.path.join(tmpdir, f'{module_name}.py')
    try:
        with open(tmpfile, 'w', encoding='utf-8') as file:
            file.write(source_code)
        spec = importlib.util.spec_from_file_location(module_name, tmpfile)
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
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def get_factor_family_instance(module_name, username: str | None = None):
    """Load a public FactorFamily first, then fall back to the current/user custom family."""
    with _factor_family_cache_lock:
        if module_name in _factor_family_cache:
            return _factor_family_cache[module_name]

    factors_dir = os.path.join(os.getcwd(), "Factors")
    module_path = os.path.join(factors_dir, f"{module_name}.py")
    source_code = load_public_factor_source(module_name) or ''
    ff = _build_factor_from_source(module_name, source_code)
    if ff is not None:
        with _factor_family_cache_lock:
            _factor_family_cache[module_name] = ff
        return ff

    if username is None:
        username = session.get('username')
    if username:
        custom_source = load_factor_source(username, module_name) or ''
        custom_factor = _build_factor_from_source(module_name, custom_source)
        if custom_factor is not None:
            with _custom_factor_cache_lock:
                _custom_factor_cache[(username, module_name)] = custom_factor
            return custom_factor

        custom_dir = os.path.join(user_data_dir(username), 'custom_factors')
        custom_path = os.path.join(custom_dir, f'{module_name}.py')
        raise ImportError(f"Cannot load factor '{module_name}': not found in '{module_path}' or '{custom_path}' (user '{username}')")

    raise ImportError(f"Cannot load factor '{module_name}': not found in '{module_path}' and no active user session")


def _build_custom_factor_family(username: str, factor_id: str) -> FactorFamily | None:
    source_code = load_factor_source(username, factor_id) or ''
    if not source_code:
        return None
    return _build_factor_from_source(f'_cf_{username}_{factor_id}', source_code)


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
