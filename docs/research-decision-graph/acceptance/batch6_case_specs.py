"""Frozen case identities and initial obligations for Batch 6 acceptance."""

CASES = {
    "sgccs": {
        "workspace_id": "dd2322e53fa14847816deb3ded4436a1",
        "configuration_id": "11fa046eaa3147649a24ee8cee066c49",
        "configuration_revision": 3,
        "configuration_fingerprint": (
            "4b771453efbf0bd9bd0768e169b1e7391570dbafe85557a35e361031fd69ec9f"
        ),
        "instance_id": "0b995bad6b4d483599ad8394995edb82",
        "branch_id": "b786b559dc474f59aabc439a6c0fe3fc",
        "factor_family": "18717974771:SgCCS",
        "factor_family_version": (
            "shared-owner-qualified@configuration-revision-3"
        ),
        "factor_alias": "18717974771:SgCCS|N:2m|$F:1m|$Rev",
        "sample_start": "2026-01-01",
        "sample_end": "2026-01-31",
        "sample_role": "confirmation",
        "run_spec_hash": (
            "eaa703eda036e2b577790e286eb875549ecd253c03cae5f21a9a0bbb79188e80"
        ),
        "analyses": ["backtest"],
        "decision": "assess_bounded_confirmation_and_v1_compatibility",
        "claim_ref": "sgccs_current_scope_ranking_and_execution",
        "claim_type": "single_factor_confirmation",
        "obligations": [
            (
                "sgccs_execution_identity",
                "backend_execution_identity",
                "Does the authoritative run preserve the frozen RunSpec, "
                "shared-factor owner identity, timing, product mask, and "
                "terminal backend assurance without source disclosure?",
                "Confirm the bound RunSpec and trusted terminal assurance; "
                "record any product-scope drift as a bounded limitation.",
            ),
            (
                "sgccs_parameter_grid_robustness",
                "parameter_and_frequency_robustness",
                "Across the preregistered N and signal-frequency grid, is any "
                "ordering evidence broad enough that one isolated parameter "
                "does not determine the bounded decision?",
                "Use only the frozen grid results and record concentration, "
                "turnover, costs, and failed or null members.",
            ),
            (
                "sgccs_blind_baseline_compatibility",
                "sealed_baseline_compatibility",
                "After new-graph closure, are direction, scope, and material "
                "metrics compatible with the sealed v1 result on the current "
                "runtime universe or its explicit intersection?",
                "Keep v1 sealed until closure, then compare immutable "
                "identities and report scope differences without rewriting "
                "the new decision.",
            ),
        ],
    },
    "trend": {
        "workspace_id": "6e5dcfbb83ef486fa8bff8c596c380f6",
        "configuration_id": "b667384a4ca64c17bfc229003da4620f",
        "configuration_revision": 2,
        "configuration_fingerprint": (
            "6b051d70b8e3a22e9a991fa6f23e72d2b0b679a6395bf66b52b6a218e2af408e"
        ),
        "instance_id": "a13ab3b0fb58440ca640a8e9c6968ace",
        "branch_id": "b02c333a065645939b6291bd1b762560",
        "factor_family": "TrDualMomentum",
        "factor_family_version": (
            "git:f5309af98bbd7b6678413fc8632e390e9e240f6f"
        ),
        "factor_alias": "TrDualMomentum|P:CA|L:20d|S:5d|$F:1d",
        "sample_start": "2025-01-02",
        "sample_end": "2025-03-31",
        "sample_role": "selection",
        "run_spec_hash": (
            "c1faaaf9a33ad2ff3cbf8986f3a4b0a1135d100727117652f069a86cf0a00fc6"
        ),
        "analyses": [
            "ic",
            "factor_evaluation",
            "factor_type_analysis",
            "backtest",
        ],
        "decision": "assess_new_single_factor_for_confirmation_design",
        "claim_ref": "trend_dual_horizon_single_factor_signal",
        "claim_type": "single_factor_selection",
        "obligations": [
            (
                "trend_semantic_and_timing",
                "factor_semantics_and_causal_timing",
                "Is the dual-horizon construction one causal single-factor "
                "signal whose aligned values are available before the "
                "declared next execution point?",
                "Require deterministic expression validation, workspace type "
                "checking, finite aligned values, and no future-data timing.",
            ),
            (
                "trend_selection_evidence",
                "selection_sample_effect_and_execution",
                "Does the preregistered selection sample show coherent IC, "
                "factor diagnostics, and costed backtest behavior rather than "
                "an implementation or concentration artifact?",
                "Use the frozen four-analysis RunSpec and retain failed/null "
                "evidence, coverage, turnover, concentration, and costs.",
            ),
            (
                "trend_untouched_confirmation",
                "untouched_confirmation",
                "Does any selection-sample finding survive an untouched later "
                "sample under a newly frozen TrialPlan version?",
                "Do not strengthen the Claim from selection evidence alone; "
                "freeze a later confirmation RunSpec before inspecting it.",
            ),
            (
                "trend_roll_window_discontinuity",
                "continuous_contract_measurement",
                "Could continuous-contract roll-window discontinuities "
                "materially drive the observed trend signal or execution "
                "outcome?",
                "Use authoritative roll identities for a preregistered "
                "inside/outside or exclusion test; otherwise retain a bounded "
                "backend-capability limitation.",
            ),
        ],
    },
}
