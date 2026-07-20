"""Frozen case identities and initial obligations for Batch 6 acceptance."""

CASES = {
    "sgccs": {
        "workspace_id": "dd2322e53fa14847816deb3ded4436a1",
        "configuration_id": "11fa046eaa3147649a24ee8cee066c49",
        "configuration_revision": 3,
        "configuration_fingerprint": (
            "4b771453efbf0bd9bd0768e169b1e7391570dbafe85557a35e361031fd69ec9f"
        ),
        "instance_id": "723d7bcb5ffe414795adade39f849a08",
        "branch_id": "3e7fae879aad4453b3fdc17987d69295",
        "factor_family": "18717974771:SgCCS",
        "factor_family_version": (
            "shared-owner-qualified@configuration-revision-3"
        ),
        "factor_alias": "18717974771:SgCCS|N:2m|$F:1m|$Rev",
        "sample_start": "2026-01-01",
        "sample_end": "2026-01-31",
        "sample_role": "selection",
        "sample_hash": (
            "6471ae3d74cf0659e44ed009edd38e6d21708ccd1bbcd32c263dd68055ecbbcd"
        ),
        "run_spec_hashes": {
            "backtest": (
                "6c7088b9b4542be6d6392c3b515206871aa74edb6ca72d32ef9d1ae7b44fa005"
            ),
        },
        "analyses": ["backtest"],
        "decision": "assess_bounded_historical_replay_and_v1_compatibility",
        "claim_ref": "sgccs_current_scope_historical_replay",
        "claim_type": "single_factor_historical_replay",
        "initial_obligation_ids": [
            "sgccs_execution_identity",
            "sgccs_parameter_grid_robustness",
        ],
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
        "instance_id": "13822bc5a8454fcb850aa4f7bc60bfba",
        "branch_id": "43efeeed072a4c3eba4191ab24d34e95",
        "factor_family": "TrDualMomentum",
        "factor_family_version": (
            "git:c12d3cd1b583d7f13a89edc99676593e6c42964f"
        ),
        "factor_alias": "TrDualMomentum|P:CA|L:20d|S:5d|$F:1d",
        "sample_start": "2025-01-02",
        "sample_end": "2025-03-31",
        "sample_role": "selection",
        "sample_hash": (
            "cd977dfbc43be6aa6505dbbf9ca3e5e5e679e2f2883843e2bcf1b80406874869"
        ),
        "run_spec_hashes": {
            "ic": (
                "47aba88530e532bb24b869cce27c0d3e1b2852c5fc261ab75176e395b09f98f8"
            ),
            "factor_evaluation": (
                "4bbc12010c1f5fa1fb4317a8bc9dee102df58a855bff9707d01163bfda4c0158"
            ),
            "factor_type_analysis": (
                "16c8fbf9da556b7ff3e153630e1fad37cbd85fd0e370e174dadb0f8d1a778c0d"
            ),
            "backtest": (
                "6e0155631e1d67791a2555a13a67c14e60a5c9e26ff8439cf7ec7b89684e941d"
            ),
        },
        "analyses": [
            "ic",
            "factor_evaluation",
            "factor_type_analysis",
            "backtest",
        ],
        "decision": "assess_new_single_factor_for_confirmation_design",
        "claim_ref": "trend_dual_horizon_single_factor_signal",
        "claim_type": "single_factor_selection",
        "initial_obligation_ids": [
            "trend_semantic_and_timing",
            "trend_selection_evidence",
        ],
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
