"""Canonical typed links shared by every local report representation."""

REPORT_LINK_KINDS = frozenset({
    "evidence", "obligation", "task", "job", "claim", "artifact",
    "report_requirement", "graph_reference", "checkpoint", "run",
    "run_spec", "trial_plan", "delta",
    "factor", "profile", "profile_revision", "product",
    "contract", "continuous_contract",
    "profile_handoff", "report_section",
})
