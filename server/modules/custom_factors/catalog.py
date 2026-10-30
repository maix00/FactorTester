"""Catalog helpers for public and user custom factor families."""

from __future__ import annotations

import importlib.util
import os
import tempfile
import time

from server.modules.shared.param_meta import serialize_param_meta
from tools.data.factor_workspace.storage import load_public_factor_source
from tools.data.sqlite.factor_source_store import (
    get_factor_source_metadata,
    list_factor_sources,
)
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
    """Return the persisted family summaries for one owner."""
    from tools.data.sqlite.factor_metadata import list_factor_summaries
    return list_factor_summaries("custom", username)


def list_public_factors() -> list:
    """Return public summaries without loading executable source."""
    from tools.data.sqlite.factor_metadata import list_factor_summaries
    return list_factor_summaries("public")


def get_public_factor_detail(factor_name: str) -> dict | None:
    """Return public factor source and expression metadata."""
    try:
        source_code = load_public_factor_source(factor_name) or ''
        factor_cls, _ = _load_factor_family_from_source(source_code, factor_name)
        if factor_cls is None:
            return None
        ff = factor_cls()
        metadata = get_factor_source_metadata('public', '', factor_name)
        tree_repr = ''
        try:
            if ff.expr is not None:
                tree_repr = ff.expr.tree_repr()
        except Exception:
            pass

        return {
            'id': factor_name,
            'name': factor_name,
            'chinese_name': metadata.get('chinese_name', ''),
            'description': metadata.get('description', ''),
            'category': metadata.get('category', ''),
            'math_expr': getattr(ff, 'math_expr', '') or '',
            'source_code': source_code,
            'family_formula_fingerprint': ff.expr.semantic_fingerprint(),
            'tree_repr': tree_repr,
            'params': [serialize_param_meta(param) for param in ff.params],
            'is_public': True,
            'source': 'public',
            'factor_kind': 'public',
            'owner_username': '__public_jobs__',
            'owner_alias': '公共因子库',
            'factor_owner_ref': '__public_jobs__',
            'factor_family_alias': factor_name,
        }
    except Exception:
        return None
