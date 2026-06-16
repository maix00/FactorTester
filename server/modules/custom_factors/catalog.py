"""Catalog helpers for public and user custom factor families."""

from __future__ import annotations

import importlib.util
import os
import time

from server.modules.custom_factors.source_helpers import strip_factor_meta
from server.modules.custom_factors.storage import custom_factor_dir
from server.modules.shared.param_meta import serialize_param_meta
from server.services.accounts import (
    account_display_name,
    visible_accounts_for,
)
from server.services.factor_registry import get_factor_family_instance
from tools.factors import FactorFamily


def _factor_family_name(factor_cls: type, default: str = 'FactorFamily') -> str:
    for base in factor_cls.__bases__:
        if base is not FactorFamily and issubclass(base, FactorFamily):
            return base.__name__
    return default


def list_custom_factors(username: str) -> list:
    """List a user's custom FactorFamily files with loaded metadata."""
    directory = custom_factor_dir(username)
    factors = []
    if not os.path.exists(directory):
        return factors
    for filename in sorted(os.listdir(directory), reverse=True):
        if not filename.endswith('.py'):
            continue
        factor_id = os.path.splitext(filename)[0]
        filepath = os.path.join(directory, filename)
        mtime = os.path.getmtime(filepath)
        updated_at = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(mtime))
        source_code = ''
        try:
            with open(filepath, 'r', encoding='utf-8') as file:
                source_code = file.read()
        except Exception:
            source_code = ''

        try:
            module_name = f'_cf_{username}_{factor_id}'
            spec = importlib.util.spec_from_file_location(module_name, filepath)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            factor_cls = None
            for attr_name in dir(module):
                obj = getattr(module, attr_name)
                if isinstance(obj, type) and issubclass(obj, FactorFamily) and obj is not FactorFamily:
                    factor_cls = obj
                    break
            if factor_cls is None:
                continue

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
                'source_code': '',
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
            item['owner_username'] = owner_username
            item['owner_alias'] = owner_alias
            item['owner_organization_id'] = account.get('organization_id') or ''
            item['owner_organization_name'] = account.get('organization_name') or ''
            item['can_edit'] = owner_username == username
            factors.append(item)
    return factors


def list_public_factors() -> list:
    """List public FactorFamily classes from the Factors directory."""
    factors_dir = os.path.join(os.getcwd(), 'Factors')
    result = []
    if not os.path.exists(factors_dir):
        return result
    for filename in sorted(os.listdir(factors_dir)):
        if not filename.endswith('.py') or filename.startswith('__'):
            continue
        name = os.path.splitext(filename)[0]
        try:
            ff = get_factor_family_instance(name)
            family = _factor_family_name(ff.__class__)
            mtime = os.path.getmtime(os.path.join(factors_dir, filename))
            updated_at = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(mtime))
            source_code = ''
            try:
                with open(os.path.join(factors_dir, filename), 'r', encoding='utf-8') as file:
                    source_code = file.read()
            except Exception:
                source_code = ''
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
                'source_code': '',
                'is_public': True,
                'updated_at': '',
                'load_error': True,
            })
    return result


def get_public_factor_detail(factor_name: str) -> dict | None:
    """Return public factor source and expression metadata."""
    try:
        ff = get_factor_family_instance(factor_name)
        source_path = os.path.join(os.getcwd(), 'Factors', f'{factor_name}.py')
        source_code = ''
        if os.path.exists(source_path):
            with open(source_path, 'r', encoding='utf-8') as file:
                source_code = file.read()

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
            'source_code': strip_factor_meta(source_code),
            'tree_repr': tree_repr,
            'params': [serialize_param_meta(param) for param in ff.params],
            'is_public': True,
        }
    except Exception:
        return None
