"""Resolve current family intent before a detail or edit needs source bytes."""
import hashlib

from tools.data.account_manage import can_view_user_scope
from tools.data.sqlite.factor_family_heads import family_head
from tools.data.sqlite.factor_source_store import load_factor_source
from server.manager.services.factor_source_hydration import FactorSourceHydrator


def ensure_current_family(state, kind, factor_id, *, principal, owner=''):
    owner = '' if kind == 'public' else owner or principal
    if kind == 'custom' and owner != principal and not can_view_user_scope(principal, owner):
        raise PermissionError('factor family is outside your visible scope')
    head = family_head(kind, owner, factor_id)
    if head and head['deleted']:
        return False
    current = load_factor_source(kind, owner, factor_id)
    expected = (head or {}).get('payload', {}).get('source_sha256')
    if current and (not expected or hashlib.sha256(current.encode()).hexdigest() == expected):
        return True
    return FactorSourceHydrator(state).hydrate(
        f"{'public' if kind == 'public' else owner}:{factor_id}", principal=principal,
    )
