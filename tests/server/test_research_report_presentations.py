from server.services.research_report_presentations import (
    run_spec_presentation,
    strict_process_batch_candidate_key,
    trial_plan_presentation,
)


def _spec(*, analysis: str, session: str, fee_mode: str) -> dict:
    session_zh = "夜盘" if session == "night" else "日盘"
    return {
        "run_spec_version": 3,
        "configuration_revision": 4,
        "analyses": [analysis],
        "retention_mode": "summary",
        "step_mode": False,
        "configuration": {
            "shared": {},
            "analyses": {
                analysis: {
                    "factor_selections": [{
                        "alias": "SgCPS|P:[CA]|N:20d|$F:1m|$Rev",
                    }],
                    "product_path_selection": {
                        "label": f"MaxA SgCPS 2024 {session_zh}合格组",
                        "paths": [
                            "Product/Futures/CNFutures/日夜盘/"
                            f"{session_zh}/_products/SI.GFE",
                        ],
                    },
                    **({
                        "local_settings": {
                            "fee_mode": fee_mode,
                            "factor": (
                                "SgCPS|P:[CA]|N:20d|$F:1m|$Rev"
                            ),
                        },
                        "groups": [{
                            "name": f"中国期货{session_zh} · SgCPS",
                            "fee_mode": fee_mode,
                        }],
                    } if analysis == "backtest" else {}),
                },
            },
        },
    }


def test_maxa_six_run_specs_get_readable_chips_and_complete_parameters():
    sample = {
        "sample_start": "2024-01-02",
        "sample_end": "2024-12-31",
        "sample_hash": "f" * 64,
    }
    cases = [
        ("ic", "day", "none", "截面 IC", "日盘"),
        ("ic", "night", "none", "截面 IC", "夜盘"),
        ("backtest", "day", "none", "回测", "无手续费"),
        ("backtest", "night", "none", "回测", "无手续费"),
        ("backtest", "day", "historical", "回测", "历史手续费"),
        ("backtest", "night", "historical", "回测", "历史手续费"),
    ]
    projections = [
        run_spec_presentation(
            _spec(analysis=analysis, session=session, fee_mode=fee),
            run_spec_hash=str(index) * 64,
            sample_identity=sample,
        )
        for index, (analysis, session, fee, _, _) in enumerate(
            cases, start=1,
        )
    ]
    for projection, case in zip(projections, cases, strict=True):
        assert case[3] in projection["alias_zh"]
        assert case[4].replace("历史手续费", "历史/交易所手续费") in (
            projection["alias_zh"]
        )
        assert "2024-01-02—2024-12-31" in projection["alias_zh"]
        assert "SgCPS" in projection["alias_zh"]
        assert projection["complete_parameters"]["run_spec_version"] == 3
        assert projection["complete_parameters_json"].startswith("{")
        assert "运行前拟提交配置" in projection["summary_zh"]


def test_submitted_run_spec_is_described_as_server_frozen_provenance():
    projection = run_spec_presentation(
        _spec(analysis="ic", session="day", fee_mode="none"),
        run_spec_hash="a" * 64,
        run_id="run-1",
    )

    assert projection["target_ref"] == "run:run-1"
    assert "服务器接受后的冻结配置" in projection["summary_zh"]


def test_batch_key_rejects_same_dates_when_execution_semantics_differ():
    sample = {
        "sample_start": "2024-01-02",
        "sample_end": "2024-12-31",
        "sample_hash": "f" * 64,
    }
    day_gross = _spec(
        analysis="backtest", session="day", fee_mode="none",
    )
    assert strict_process_batch_candidate_key(
        day_gross, sample_identity=sample,
    ) == strict_process_batch_candidate_key(
        day_gross, sample_identity=sample,
    )
    assert strict_process_batch_candidate_key(
        day_gross, sample_identity=sample,
    ) != strict_process_batch_candidate_key(
        _spec(
            analysis="backtest",
            session="night",
            fee_mode="none",
        ),
        sample_identity=sample,
    )
    assert strict_process_batch_candidate_key(
        day_gross, sample_identity=sample,
    ) != strict_process_batch_candidate_key(
        _spec(
            analysis="backtest",
            session="day",
            fee_mode="historical",
        ),
        sample_identity=sample,
    )
    assert strict_process_batch_candidate_key(
        day_gross, sample_identity=sample,
    ) != strict_process_batch_candidate_key(
        _spec(analysis="ic", session="day", fee_mode="none"),
        sample_identity=sample,
    )


def test_trial_plan_presentation_is_readable_and_keeps_full_plan():
    plan = {
        "schema_version": 5,
        "trial_plan_id": "plan:sgcps-canonical-2024-v1",
        "version": 1,
        "trial_family": "family:sgcps-canonical-baseline",
        "samples": [
            {"sample_ref": "sample:2024-day-ic"},
            {"sample_ref": "sample:2024-night-ic"},
            {"sample_ref": "sample:2024-day-gross"},
            {"sample_ref": "sample:2024-night-gross"},
            {"sample_ref": "sample:2024-day-net"},
            {"sample_ref": "sample:2024-night-net"},
        ],
        "stage_policy": {
            "ordered_stage_ids": [
                "in-sample-ic",
                "gross-backtest",
                "net-backtest",
            ],
        },
    }
    projection = trial_plan_presentation(plan)
    assert projection["alias_zh"] == (
        "sgcps-canonical-baseline · 3 个阶段 · 6 个样本定义"
    )
    assert "in-sample-ic → gross-backtest → net-backtest" in (
        projection["summary_zh"]
    )
    assert projection["complete_parameters"] == plan
