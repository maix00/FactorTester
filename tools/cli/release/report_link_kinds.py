"""Canonical typed links shared by every local report representation."""

REPORT_LINK_KINDS = frozenset({
    "evidence", "job", "artifact", "report_copy", "run",
    "run_spec", "trial_plan",
    "factor", "profile", "profile_revision", "product",
    "contract", "continuous_contract",
    "report_section",
})

_REFERENCE_LINK_KINDS = (
    ("evidence:", "evidence"),
    ("job:", "job"),
    ("artifact:", "artifact"),
    ("report-copy:", "report_copy"),
    ("run:", "run"),
    ("runspec:", "run_spec"),
    ("trial-plan:", "trial_plan"),
    ("factor:", "factor"),
    ("factor-family:", "factor"),
    ("factor-set:", "factor"),
    ("profile-revision:", "profile_revision"),
    ("profile:", "profile"),
)


def report_link_kind_for_ref(target_ref: str) -> str:
    """Classify an explicit stable reference without guessing its object."""
    for prefix, kind in _REFERENCE_LINK_KINDS:
        if target_ref.startswith(prefix):
            return kind
    raise ValueError("unknown report reference kind")
