"""
FactorFamily 加载、缓存与失效管理。

生命周期：
  - FactorFamily 实例由 page_uuid 持有，不设全局强引用缓存
  - 页面关闭/超时时自动回收
  - Factor 缓存同样由 page_uuid 管理（FactorFamily.get_factor 优先查页级缓存）

元数据：
  - 因子中文名/描述从 SQLite factor_family_catalog 表读取（懒加载，不实例化）
  - 因子列表 get_factor_groups() 从文件系统扫描（不实例化）

核心函数：
  get_factor_family_instance()  加载因子族实例 → 优先从 page 级缓存查找
  invalidate_factor_family_cache()  失效特定的或全部公共因子缓存
  invalidate_custom_factor_cache()  失效特定用户的或某用户全部的的自定义因子缓存
  get_factor_groups()           返回按前缀分组的因子名列表（Mm/Oi/Vl/Vp 等）
  factor_group_key()            从类名提取分组前缀（MmRet → Mm）
"""

from __future__ import annotations

import importlib.util
import os
import sqlite3
import tempfile
import threading
from typing import TYPE_CHECKING

from flask import session

from tools.factors.FactorFamily import FactorFamily
from tools.data.factor_workspace.storage import load_factor_source, load_public_factor_source

if TYPE_CHECKING:
    from tools.factors.Factors import Factor

import Settings

# ── 页级缓存（由 page_uuid 持有，替代全局强引用） ──
# page_families: {page_uuid: {module_name: FactorFamily}}
# page_factors:   {page_uuid: {factor_name: Factor}}
page_families: dict[str, dict[str, FactorFamily]] = {}
page_factors: dict[str, dict[str, 'Factor']] = {}
_page_cache_lock = threading.Lock()

# 自定义因子缓存（按 (username, factor_id) 缓存，自定义因子量少）
_custom_factor_cache: dict = {}
_custom_factor_cache_lock = threading.Lock()

# 中文名缓存（从 SQLite 一次性加载，轻量，不实例化 FactorFamily）
_chinese_names_cache: dict = {}
_chinese_names_cache_loaded = False


# ── 页级缓存操作 ──

def register_page(page_uuid: str) -> None:
    """注册新页面。"""
    with _page_cache_lock:
        page_families.setdefault(page_uuid, {})
        page_factors.setdefault(page_uuid, {})


def unregister_page(page_uuid: str) -> None:
    """注销页面，释放其持有的 FactorFamily 和 Factor。"""
    with _page_cache_lock:
        families = page_families.pop(page_uuid, {})
        factors = page_factors.pop(page_uuid, {})
    # 清理 Factor（调 clear 释放中间数据）
    for f in factors.values():
        try:
            f.clear()
            f.delete()
        except Exception:
            pass
    # FactorFamily 实例随 dict 回收自然释放（无其他强引用）


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


def get_factor_family_instance(module_name, username: str | None = None, page_uuid: str | None = None):
    """Load a FactorFamily instance.

    Priority:
      1. page_uuid 的 page_families 缓存
      2. 构建新实例（公共因子或自定义因子）并写入 page 缓存
    """
    # 1. 检查 page 级缓存
    if page_uuid:
        with _page_cache_lock:
            ff_dict = page_families.get(page_uuid, {})
            if module_name in ff_dict:
                return ff_dict[module_name]

    # 2. 公共因子
    factors_dir = os.path.join(os.getcwd(), "Factors")
    module_path = os.path.join(factors_dir, f"{module_name}.py")
    if os.path.isfile(module_path):
        source_code = load_public_factor_source(module_name) or ''
        ff = _build_factor_from_source(module_name, source_code)
        if ff is None:
            raise ImportError(f"Cannot load factor '{module_name}': source exists but no FactorFamily class found in '{module_path}'")
    else:
        # 3. 自定义因子
        if username is None:
            username = session.get('username')
        if username:
            custom_source = load_factor_source(username, module_name) or ''
            ff = _build_factor_from_source(module_name, custom_source)
            if ff is not None:
                with _custom_factor_cache_lock:
                    _custom_factor_cache[(username, module_name)] = ff
                return ff
            raise ImportError(f"Cannot load factor '{module_name}': not found in public sources or database for user '{username}'")
        raise ImportError(f"Cannot load factor '{module_name}': not found in '{module_path}' and no active user session")

    # 4. 写入 page 级缓存
    if page_uuid:
        with _page_cache_lock:
            page_families.setdefault(page_uuid, {})[module_name] = ff

    return ff


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


def invalidate_factor_family_cache(factor_name: str | None = None, page_uuid: str | None = None):
    """失效 FactorFamily 缓存。

    - 指定 factor_name + page_uuid：从该页面缓存中移除
    - 指定 factor_name 无 page_uuid：从所有页面缓存中移除
    - 不指定 factor_name：清空指定页面（或所有页面）的 families + factors
    """
    with _page_cache_lock:
        if factor_name:
            if page_uuid:
                ff_dict = page_families.get(page_uuid, {})
                ff_dict.pop(factor_name, None)
            else:
                for ff_dict in page_families.values():
                    ff_dict.pop(factor_name, None)
        else:
            if page_uuid:
                page_families.pop(page_uuid, None)
                page_factors.pop(page_uuid, None)
            else:
                page_families.clear()
                page_factors.clear()


def _load_chinese_names_from_sqlite() -> dict[str, str]:
    """从 SQLite factor_family_catalog 表加载所有公共因子的中文名。
    
    不实例化 FactorFamily，纯 SQL 读取，快且懒加载友好。
    """
    result: dict[str, str] = {}
    db_path = str(Settings.CACHE_DB_PATH)
    if not os.path.isfile(db_path):
        return result
    try:
        conn = sqlite3.connect(db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT factor_id, chinese_name FROM factor_family_catalog "
            "WHERE source_kind='public' AND load_error=0"
        ).fetchall()
        conn.close()
        for row in rows:
            name = row["factor_id"] or ""
            cn = row["chinese_name"] or ""
            if name:
                result[name] = cn
    except Exception:
        pass
    return result


def get_chinese_names(factors_dir=None) -> dict[str, str]:
    """返回所有公共因子的 {模块名: 中文名} 映射。从 SQLite 懒加载。"""
    global _chinese_names_cache_loaded, _chinese_names_cache
    if not _chinese_names_cache_loaded:
        _chinese_names_cache = _load_chinese_names_from_sqlite()
        _chinese_names_cache_loaded = True
    return _chinese_names_cache


# 保留 _load_chinese_names 兼容旧调用（但不实例化 FactorFamily）
def _load_chinese_names(factors_dir):
    """[兼容] 返回中文名映射，委托给 SQLite 加载。"""
    return get_chinese_names()


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


# ── Page 级 Factor 缓存操作 ──

def get_page_factor(page_uuid: str, factor_alias: str) -> 'Factor | None':
    """从 page 级缓存获取 Factor。"""
    with _page_cache_lock:
        pf = page_factors.get(page_uuid, {})
        return pf.get(factor_alias)


def set_page_factor(page_uuid: str, factor_alias: str, factor: 'Factor') -> None:
    """将 Factor 写入 page 级缓存。"""
    with _page_cache_lock:
        page_factors.setdefault(page_uuid, {})[factor_alias] = factor


def get_page_cached_factors(factor_family: FactorFamily, page_uuid: str, **kwargs):
    """[server 层] 带 page 级 Factor 缓存的 get_factors 包装。

    FactorFamily.get_factors() 纯计算 → 逐个检查 page 缓存：
    - 已缓存（alias 相同）→ 用缓存版替换（保留已有数据）
    - 未缓存 → 写入 page 缓存

    这是 server 层专有逻辑，tools 层不感知 page_uuid。
    """
    all_factors = factor_family.get_factors(**kwargs)

    if not page_uuid:
        return all_factors

    # 按 alias 检查 page 缓存 → 替换或写入
    result = []
    for factor in all_factors:
        alias = factor.alias
        cached = get_page_factor(page_uuid, alias)
        if cached is not None:
            result.append(cached)
        else:
            set_page_factor(page_uuid, alias, factor)
            result.append(factor)

    return result
