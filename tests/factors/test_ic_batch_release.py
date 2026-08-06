from __future__ import annotations

from types import SimpleNamespace

from tools.data.types import DataFreq
from tools.factors.evaluation.batch import (
    PreparedEvaluationBatch,
    release_evaluation_batch,
)


def test_release_evaluation_batch_invalidates_each_product_frequency_prefix(monkeypatch):
    calls = []

    class _Hub:
        def invalidate_prefix(self, namespace, prefix):
            calls.append((namespace, prefix))
            return 1

    class _View:
        def get_current_source(self):
            return SimpleNamespace(key="SRC")

        def _resource_id_for_source(self, source):
            return f"{source.key}:P:MIN1"

    product = SimpleNamespace(MIN1=_View())
    prepared = PreparedEvaluationBatch(
        products=(product,),
        freq=DataFreq.MIN1,
        start_dt=None,
        end_dt=None,
        warmup_window=None,
        preloaded=None,
        panel_timeline=None,
    )
    monkeypatch.setattr(
        "tools.data.hub.DataHub.get_instance", lambda: _Hub(),
    )

    assert release_evaluation_batch(prepared) == 1
    assert calls == [("datameta", "SRC:P:MIN1")]

