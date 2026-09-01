from tools.testers.backtest.engines.native.flow import Phase, phase_label
def test_phase_labels_are_declared_by_phase() -> None:
    assert phase_label("pre_replay") == Phase.PRE_REPLAY.label
    assert phase_label("per_event") == Phase.PER_EVENT.label
    assert phase_label("post_replay") == Phase.POST_REPLAY.label
