from __future__ import annotations

import pandas as pd

from tools.data.hub import DataHub
from tools.products.AdjustableTermStructure import TermStructureStore


def test_store_reuses_artifact_and_filters_each_request(monkeypatch, tmp_path) -> None:
    path = str(tmp_path / "term-structure.parquet")
    source = pd.DataFrame({
        "PRODUCT": ["A", "A", "B"],
        "TRADING_DAY": pd.to_datetime([
            "2025-01-02",
            "2025-01-03",
            "2025-01-02",
        ]),
        "CONTRACT_UID": ["A1", "A2", "B1"],
    })
    reads = []

    def read_parquet(requested_path, **kwargs):
        reads.append(requested_path)
        frame = source
        for column, operator, value in kwargs.get("filters") or ():
            assert operator == "=="
            frame = frame[frame[column] == value]
        columns = kwargs.get("columns")
        return frame if columns is None else frame[columns]

    monkeypatch.setattr(pd, "read_parquet", read_parquet)
    hub = DataHub.get_instance()
    hub.invalidate("term_structure", path)
    store = TermStructureStore(path)

    first = store.load(product="A", columns=["CONTRACT_UID"])
    second = store.load(product="B", trading_day="2025-01-02")

    assert reads == [path]
    assert first.to_dict("records") == [{"CONTRACT_UID": "A1"}, {"CONTRACT_UID": "A2"}]
    assert second["CONTRACT_UID"].tolist() == ["B1"]
    hub.invalidate("term_structure", path)
