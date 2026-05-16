from __future__ import annotations

import time
import uuid


def make_submission_id(raw_id=None) -> str:
    """Return a stable frontend submission id, generating one when omitted."""
    if raw_id is not None and str(raw_id).strip():
        return str(raw_id)
    return f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"
