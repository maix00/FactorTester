"""Catalog helpers for public and user custom factor families."""

from __future__ import annotations

import importlib.util
import os
import tempfile
import time

from server.modules.custom_factors.source_helpers import strip_factor_meta
from server.modules.shared.param_meta import serialize_param_meta
from tools.data.account_manage import (
    account_display_name,
    visible_accounts_for,
)
from server.services.factor_registry import get_factor_family_instance
from tools.data.factor_workspace.storage import load_public_factor_source
from tools.data.sqlite.factor_source_store import list_factor_sources
from tools.factors import FactorFamily


def _factor_family_name(factor_cls: type, default: str = 'FactorFamily') -> str:
    for base in factor_cls.__bases__:
        if base is not FactorFamily and issubclass(base, FactorFamily):
            return base.__name__
    return default


def _load_factor_family_from_source(source_code: str, module_name: str) -> tuple[type | None, object | None]:
    if not source_code:
        return None, None
    tmpdir = tempfile.mkdtemp(prefix='factor_catalog_')
    tmpfile = os.path.join(tmpdir, f'{module_name}.py')
    try:
        with open(tmpfile, 'w', encoding='utf-8') as file:
            file.write(source_code)
        spec = importlib.util.spec_from_file_location(module_name, tmpfile)
        if spec is None or spec.loader is None:
            return None, None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        from tools.factors import FactorFamily
        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            if isinstance(obj, type) and issubclass(obj, FactorFamily) and obj is not FactorFamily:
                return obj, module
        return None, module
    except Exception:
        return None, None
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def list_custom_factors(username: str) -> list:
    """List a user's custom FactorFamily rows from the database."""
    factors = []
    rows = [row for row in list_factor_sources('custom') if row.get('owner_username') == username]

    for row in rows:
        factor_id = str(row.get('factor_id') or '')
        source_code = str(row.get('source_code') or '')
        updated_at = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(float(row.get('updated_at') or time.time())))
        factor_cls, module = _load_factor_family_from_source(source_code, f'_cf_{username}_{factor_id}')
        if factor_cls is None:
            factors.append({
                'id': factor_id,
                'name': factor_id,
                'category': '自编',
                'factor_family': 'FactorFamily',
                'chinese_name': '',
                'description': '',
                'params': [],
                'source_code': strip_factor_meta(source_code),
                'is_public': False,
                'updated_at': updated_at,
                'load_error': True,
            })
            continue

        try:
            ff = factor_cls()
            family = _factor_family_name(factor_cls)
            factors.append({
                'id': factor_id,
                'name': factor_cls.__name__,
                'category': getattr(ff, 'category', '') or '自编',
                'factor_family': family,
                'chinese_name': getattr(ff, 'desc', '') or '',
                'description': getattr(ff, 'description', '') or '',
                'math_expr': getattr(ff, 'math_expr', '') or '',
                'source_code': strip_factor_meta(source_code),
                'params': [serialize_param_meta(param) for param in ff.params],
                'is_public': False,
                'updated_at': updated_at,
            })
        except Exception:
            factors.append({
                'id': factor_id,
                'name': factor_id,
                'category': '自编',
                'factor_family': 'FactorFamily',
                'chinese_name': '',
                'description': '',
                'params': [],
                'source_code': strip_factor_meta(source_code),
                'is_public': False,
                'updated_at': updated_at,
                'load_error': True,
            })
    factors.sort(key=lambda factor: factor.get('updated_at', ''), reverse=True)
    return factors


def list_visible_custom_factors(username: str) -> list:
    factors = []
    for account in visible_accounts_for(username, include_self=True):
        owner_username = account.get('username')
        if not owner_username:
            continue
        owner_alias = account_display_name(account)
        for factor in list_custom_factors(owner_username):
            item = dict(factor)
            # Visibility and editability are separate permissions. A direct
            # parent may inspect a subordinate's registered family formula and
            # read-only source, but only the owner may edit it.
            item['source_access'] = True
            item['owner_username'] = owner_username
            item['owner_alias'] = owner_alias
            item['owner_organization_id'] = account.get('organization_id') or ''
            item['owner_organization_name'] = account.get('organization_name') or ''
            item['can_edit'] = owner_username == username
            factors.append(item)
    return factors


def list_public_factors() -> list:
    """List public FactorFamily classes from the SQLite source registry."""
    result = []
    rows = list_factor_sources('public')

    for row in rows:
        name = str(row.get('factor_id') or '')
        source_code = str(row.get('source_code') or '')
        updated_at = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(float(row.get('updated_at') or time.time())))
        factor_cls, _ = _load_factor_family_from_source(source_code, name)
        if factor_cls is None:
            result.append({
                'id': name,
                'name': name,
                'category': '',
                'factor_family': 'FactorFamily',
                'chinese_name': '',
                'description': '',
                'params': [],
                'source_code': strip_factor_meta(source_code),
                'is_public': True,
                'updated_at': updated_at,
                'load_error': True,
            })
            continue
        try:
            ff = factor_cls()
            family = _factor_family_name(factor_cls)
            result.append({
                'id': name,
                'name': name,
                'category': getattr(ff, 'category', '') or family,
                'factor_family': family,
                'chinese_name': getattr(ff, 'desc', '') or getattr(ff, 'chinese_name', '') or '',
                'description': getattr(ff, 'description', '') or '',
                'math_expr': getattr(ff, 'math_expr', '') or '',
                'source_code': strip_factor_meta(source_code),
                'params': [serialize_param_meta(param) for param in ff.params],
                'is_public': True,
                'updated_at': updated_at,
            })
        except Exception:
            result.append({
                'id': name,
                'name': name,
                'category': '',
                'factor_family': 'FactorFamily',
                'chinese_name': '',
                'description': '',
                'params': [],
                'source_code': strip_factor_meta(source_code),
                'is_public': True,
                'updated_at': updated_at,
                'load_error': True,
            })
    return result


def get_public_factor_detail(factor_name: str) -> dict | None:
    """Return public factor source and expression metadata."""
    try:
        source_code = load_public_factor_source(factor_name) or ''
        factor_cls, _ = _load_factor_family_from_source(source_code, factor_name)
        if factor_cls is None:
            return None
        ff = factor_cls()
        tree_repr = ''
        try:
            if ff.expr is not None:
                tree_repr = ff.expr.tree_repr()
        except Exception:
            pass

        return {
            'id': factor_name,
            'name': factor_name,
            'chinese_name': getattr(ff, 'desc', '') or getattr(ff, 'chinese_name', '') or '',
            'description': getattr(ff, 'description', '') or '',
            'math_expr': getattr(ff, 'math_expr', '') or '',
            'source_code': strip_factor_meta(source_code),
            'tree_repr': tree_repr,
            'params': [serialize_param_meta(param) for param in ff.params],
            'is_public': True,
        }
    except Exception:
        return None
