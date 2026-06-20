"""
FeeModification — domain model for fee overrides.

FeeModification is a tool-layer concept (not server-specific). It lives under
tools/products/transactions/ alongside future margin/commission models.

Usage:
    from tools.products.transactions.fees import (
        FeeModification, FeeModificationStore,
        VALID_FEE_FIELDS, clean_modifications, sort_modifications,
    )

FeeModification format (shared with frontend):
    {
        variety_code: str,       // uppercase, e.g. "AG"
        contract_name: str|null, // specific contract (Term Structure), null = variety-level
        fields: {
            open_ratio: 0.000123,
            open_fixed: 1.5,
            ...
        },
        time_from: str|null,     // "YYYY-MM-DD" or "YYYY-MM-DD HH:MM"
        time_to: str|null,
        timestamp: int,          // Unix ms — sort DESC, later wins
    }
"""
import json
import os
import time
from dataclasses import dataclass, field
from typing import Optional

# ── Constants ─────────────────────────────────────────────────────────────────

VALID_FEE_FIELDS = frozenset({
    'open_ratio', 'close_yesterday_ratio', 'close_today_ratio',
    'open_fixed', 'close_yesterday_fixed', 'close_today_fixed',
})


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class FeeModification:
    """A single fee override entry for a variety or contract within a time range."""
    variety_code: str
    fields: dict
    contract_name: Optional[str] = None
    time_from: Optional[str] = None
    time_to: Optional[str] = None
    timestamp: int = 0

    def __post_init__(self):
        self.variety_code = self.variety_code.upper()
        if self.timestamp == 0:
            self.timestamp = int(time.time() * 1000)

    def to_dict(self) -> dict:
        return {
            'variety_code': self.variety_code,
            'contract_name': self.contract_name or None,
            'fields': dict(self.fields),
            'time_from': self.time_from or None,
            'time_to': self.time_to or None,
            'timestamp': self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'FeeModification':
        return cls(
            variety_code=str(d.get('variety_code', '')).strip().upper(),
            contract_name=str(d.get('contract_name') or '') or None,
            fields=_clean_fields(d.get('fields')),
            time_from=str(d.get('time_from') or '') or None,
            time_to=str(d.get('time_to') or '') or None,
            timestamp=int(d.get('timestamp', 0) or 0),
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _clean_fields(fields: dict) -> dict:
    """Validate and clean a fields dict, keeping only VALID_FEE_FIELDS with numeric values."""
    if not isinstance(fields, dict):
        return {}
    cleaned = {}
    for fname, fval in fields.items():
        fname = str(fname).strip()
        if fname not in VALID_FEE_FIELDS:
            continue
        try:
            cleaned[fname] = float(fval)
        except (TypeError, ValueError):
            continue
    return cleaned


def clean_modifications(mods: list[dict]) -> list[FeeModification]:
    """Validate and clean a list of raw modification dicts from API / JSON.

    Returns FeeModification instances (valid entries only).
    """
    cleaned = []
    for m in mods:
        if not isinstance(m, dict):
            continue
        fm = FeeModification.from_dict(m)
        if not fm.fields or not fm.variety_code:
            continue
        cleaned.append(fm)
    return cleaned


def sort_modifications(mods: list[FeeModification]) -> list[FeeModification]:
    """Sort modifications by timestamp DESC (latest wins), then by variety_code."""
    return sorted(mods, key=lambda m: (-m.timestamp, m.variety_code))


# ── Persistent storage ────────────────────────────────────────────────────────

class FeeModificationStore:
    """Local JSON file storage for fee modifications, keyed by submission_id."""

    def __init__(self, base_dir: str = None):
        if base_dir is None:
            base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.fee_modifications')
        self._base_dir = base_dir

    def _file_path(self, submission_id: str) -> str:
        os.makedirs(self._base_dir, exist_ok=True)
        safe_id = "".join(c for c in str(submission_id) if c.isalnum() or c in '_-')
        return os.path.join(self._base_dir, f"{safe_id}.json")

    def load(self, submission_id: str) -> list[FeeModification]:
        path = self._file_path(submission_id)
        if not os.path.exists(path):
            return []
        try:
            with open(path, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            return clean_modifications(raw)
        except Exception:
            return []

    def save(self, submission_id: str, mods: list) -> None:
        path = self._file_path(submission_id)
        dicts = [
            m.to_dict() if isinstance(m, FeeModification)
            else FeeModification.from_dict(m).to_dict()
            for m in mods
        ]
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(dicts, f, ensure_ascii=False, indent=2)
