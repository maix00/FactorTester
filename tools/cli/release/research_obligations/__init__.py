"""Git-tracked branch-local research obligation ledger."""

from .ledger import (
    MAX_LEDGER_BYTES,
    append_event,
    canonicalize_ledger,
    initialize_ledger,
    ledger_hash,
    ledger_path,
    load_ledger,
    projection_hash,
    write_ledger,
)
from .projection import (
    apply_obligation_deltas,
    project_requirement_coverage,
)
from .inheritance import inherit_obligation_ledger
from .migration import ledger_from_history
from .packet import (
    branch_identity,
    checkpoint_ref,
    obligations,
    requirement_union,
    requirements,
)

__all__ = [
    "MAX_LEDGER_BYTES",
    "append_event",
    "canonicalize_ledger",
    "apply_obligation_deltas",
    "branch_identity",
    "checkpoint_ref",
    "initialize_ledger",
    "inherit_obligation_ledger",
    "ledger_hash",
    "ledger_from_history",
    "ledger_path",
    "load_ledger",
    "obligations",
    "project_requirement_coverage",
    "projection_hash",
    "requirement_union",
    "requirements",
    "write_ledger",
]
