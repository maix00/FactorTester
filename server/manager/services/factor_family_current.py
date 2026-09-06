"""Resolve current family intent before a detail or edit needs source bytes."""
import hashlib
import settings

from tools.data.account_manage import can_view_user_scope
from tools.data.sqlite.factor_family_heads import family_head
from tools.data.sqlite.factor_source_store import load_factor_source, upsert_factor_source
from server.manager.objects.adapters.factor_source import FactorSourceStore
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
    # The current pointer and the mutable source copy can arrive separately.
    # Reuse an exact resident snapshot before asking another provider; the
    # authoritative provider can be this server itself. Never substitute a
    # different source merely because it has the same semantic fingerprint.
    if expected:
        object_id = f"{'public' if kind == 'public' else owner}:{factor_id}"
        try:
            source = FactorSourceStore(database=settings.CACHE_DB_PATH).source(
                object_id, expected_sha256=expected,
            )
        except FileNotFoundError:
            source = ''
        if source and hashlib.sha256(source.encode()).hexdigest() == expected:
            payload = head['payload']
            upsert_factor_source(
                kind, owner, factor_id, payload.get('factor_name') or factor_id,
                source, chinese_name=payload.get('chinese_name') or '',
                description=payload.get('description') or '',
                category=payload.get('category') or '',
                family_formula_fingerprint=payload.get('family_formula_fingerprint') or '',
                publish_family=False,
            )
            return True
    return FactorSourceHydrator(state).hydrate(
        f"{'public' if kind == 'public' else owner}:{factor_id}", principal=principal,
    )
