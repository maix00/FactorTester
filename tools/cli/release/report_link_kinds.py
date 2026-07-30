"""Canonical typed links shared by every local report representation."""

REPORT_LINK_KINDS = frozenset({
    "evidence", "obligation", "task", "job", "claim", "artifact",
    "report_requirement", "graph_reference", "checkpoint", "run",
    "run_spec", "trial_plan", "delta",
    "factor", "profile", "profile_revision", "product",
    "contract", "continuous_contract",
    "profile_handoff", "report_section",
})

_REFERENCE_LINK_KINDS = (
    ("evidence:", "evidence"),
    ("obligation:", "obligation"),
    ("task:", "task"),
    ("job:", "job"),
    ("claim:", "claim"),
    ("artifact:", "artifact"),
    ("report-requirement:", "report_requirement"),
    ("trace:", "graph_reference"),
    ("report-checkpoint:", "graph_reference"),
    ("run:", "run"),
    ("runspec:", "run_spec"),
    ("trial-plan:", "trial_plan"),
    ("delta:", "delta"),
    ("factor:", "factor"),
    ("factor-family:", "factor"),
    ("profile-revision:", "profile_revision"),
    ("profile:", "profile"),
)


def report_link_kind_for_ref(target_ref: str) -> str:
    """Classify an explicit stable reference without guessing its object."""
    for prefix, kind in _REFERENCE_LINK_KINDS:
        if target_ref.startswith(prefix):
            return kind
    return "graph_reference"
