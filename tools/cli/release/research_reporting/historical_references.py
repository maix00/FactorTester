"""Inert citations retained when an old report's authority has been retired."""
from __future__ import annotations

import hashlib
import base64
import json
import re

RETIRED_REFERENCE_KINDS = frozenset({
    'graph_reference', 'checkpoint', 'obligation', 'claim', 'delta',
    'entry_requirement', 'report_requirement',
})
_REF = re.compile(r'historical-ref:v1:[0-9a-f]{64}')


def historical_reference(kind: str, target_ref: str) -> str:
    if not isinstance(kind, str) or not kind or not isinstance(target_ref, str) or not target_ref:
        raise ValueError('historical reference identity is invalid')
    raw = json.dumps([kind, target_ref], ensure_ascii=False, separators=(',', ':')).encode()
    if len(raw) > 8192:
        raise ValueError('historical reference identity exceeds its limit')
    return 'historical-ref:v1:' + hashlib.sha256(raw).hexdigest()


def require_historical_reference(value: str) -> str:
    if not isinstance(value, str) or _REF.fullmatch(value) is None:
        raise ValueError('historical reference must identify an inert citation')
    return value


def historical_anchor(value: str) -> str:
    """Compact document marker; renderers keep it inert instead of navigating."""
    require_historical_reference(value)
    encoded = base64.urlsafe_b64encode(bytes.fromhex(value.rsplit(':', 1)[1])).decode().rstrip('=')
    return '#tr-history-' + encoded
