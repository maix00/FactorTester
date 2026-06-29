from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_module(module_name: str, relative_path: str):
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_source = _load_module(
    "guosen_limit_order_volume_source_test",
    "sources/Guosen/LimitOrderVolume/_source.py",
)
_store = _load_module(
    "guosen_limit_order_volume_store_test",
    "sources/Guosen/LimitOrderVolume/_store.py",
)


class _DummyResponse:
    def __init__(self, html: str):
        self._html = html.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self._html


def _sample_html() -> str:
    return """
    <html>
      <body>
        <table>
          <tr>
            <th>交易所</th>
            <th>品种</th>
            <th colspan="2">最大下单数量</th>
            <th>备注</th>
          </tr>
          <tr>
            <th></th>
            <th></th>
            <th>限价指令</th>
            <th>市价指令</th>
            <th></th>
          </tr>
          <tr>
            <td>上海期货交易所</td>
            <td>铜</td>
            <td>500手</td>
            <td>0手</td>
            <td>每笔最小下单数量均为1手</td>
          </tr>
        </table>
      </body>
    </html>
    """


def test_fetch_table_adds_source_columns(monkeypatch):
    monkeypatch.setattr(
        pd,
        "read_html",
        lambda *args, **kwargs: [
            pd.DataFrame(
                [
                    ["header-1", "header-1", "header-1", "header-1", "header-1"],
                    ["header-2", "header-2", "header-2", "header-2", "header-2"],
                    ["上海期货交易所", "铜", "500手", "0手", "每笔最小下单数量均为1手"],
                ]
            )
        ],
    )
    monkeypatch.setattr(
        _source,
        "urlopen",
        lambda req, timeout=15: _DummyResponse(_sample_html()),
    )

    df = _source.fetch_table(
        url="https://www.guosenqh.com.cn/main/a/20260519/12800.shtml",
        source_url="https://www.guosenqh.com.cn/main/a/20260519/12800.shtml",
        source_date="2026-05-19",
    )

    assert "source_url" in df.columns
    assert "source_date" in df.columns
    assert df.iloc[0]["source_url"] == "https://www.guosenqh.com.cn/main/a/20260519/12800.shtml"
    assert df.iloc[0]["source_date"] == "2026-05-19"


def test_store_roundtrip_reads_latest_source_metadata(monkeypatch, tmp_path: Path):
    from tools.data.hub import SQLiteStore

    db_path = tmp_path / "localdata" / "unifieddata.sqlite"
    _store.DataHub.get_instance().register_sqlite_store(SQLiteStore(
        key="openctp",
        label="test",
        path_getter=lambda: str(db_path),
    ))

    df = pd.DataFrame(
        [
            {
                "exchange": "上海期货交易所",
                "product": "铜",
                "limit_order": "500手",
                "market_order": "0手",
                "note": "每笔最小下单数量均为1手",
                "source_url": "https://www.guosenqh.com.cn/main/a/20260519/12800.shtml",
                "source_date": "2026-05-19",
            }
        ]
    )

    _store.save_table(df)

    latest = _store.load_latest_table()
    assert latest is not None
    assert latest.loc[0, "source_url"] == "https://www.guosenqh.com.cn/main/a/20260519/12800.shtml"

    metadata = _store.load_latest_source_metadata()
    assert metadata == ("https://www.guosenqh.com.cn/main/a/20260519/12800.shtml", "2026-05-19")


def test_event_store_roundtrip_preserves_product_identity(monkeypatch, tmp_path: Path):
    from tools.data.hub import SQLiteStore

    db_path = tmp_path / "localdata" / "unifieddata.sqlite"
    _store.DataHub.get_instance().register_sqlite_store(SQLiteStore(
        key="openctp",
        label="test-events",
        path_getter=lambda: str(db_path),
    ))

    _store.save_events([
        {
            "exchange": "DCE",
            "product_label": "纯苯",
            "product_code": "BZ",
            "product_codes": ["BZ"],
            "product_code_match_status": "matched",
            "instrument_type": "future",
            "contract_codes": ["2606", "2607"],
            "field": "MinLimitOrderVolume",
            "old_value": None,
            "new_value": 8.0,
            "effective_date": "2026-03-09",
            "source_url": "https://www.guosenqh.com.cn/main/a/20260519/12800.shtml",
            "source_date": "2026-05-19",
            "raw_note": "自2026年3月9日起调整为8手",
            "is_product_level": False,
        }
    ])

    latest = _store.load_latest_events()
    assert latest is not None
    assert latest.loc[0, "product_label"] == "纯苯"
    assert latest.loc[0, "product_code"] == "BZ"
    assert latest.loc[0, "product_codes"] == '["BZ"]'
    assert latest.loc[0, "product_code_match_status"] == "matched"
    assert latest.loc[0, "instrument_type"] == "future"
    assert latest.loc[0, "contract_codes"] == '["2606", "2607"]'


def test_parse_all_futures_row_expands_product_codes_and_min_order():
    from sources.Guosen.LimitOrderVolume._analysis import parse_row_to_alter_events

    events = parse_row_to_alter_events(
        exchange_name="上海期货交易所",
        product_str="所有期货品种",
        limit_order="500手",
        market_order="0手",
        note="每笔最小下单数量均为 1手",
        source_url="https://example.test",
        source_date="2026-06-23",
    )

    by_field = {event["field"]: event for event in events}
    assert set(by_field) == {"MaxLimitOrderVolume", "MaxMarketOrderVolume", "MinLimitOrderVolume"}
    assert by_field["MaxLimitOrderVolume"]["product_code"] == ""
    assert "CU" in by_field["MaxLimitOrderVolume"]["product_codes"]
    assert by_field["MaxLimitOrderVolume"]["instrument_type"] == "future"
    assert by_field["MinLimitOrderVolume"]["new_value"] == 1.0


def test_parse_option_list_propagates_option_suffix_to_all_items():
    from sources.Guosen.LimitOrderVolume._analysis import parse_row_to_alter_events

    events = parse_row_to_alter_events(
        exchange_name="中国金融期货交易所",
        product_str="沪深300、中证1000、上证50股指期权合约",
        limit_order="20手",
        market_order="0手",
        note="每笔最小下单数量均为 1手",
        source_url="https://example.test",
        source_date="2026-06-23",
    )

    assert {event["product_code"] for event in events} == {"IF", "IM", "IH"}
    assert {event["instrument_type"] for event in events} == {"option"}
    assert {event["field"] for event in events} == {
        "MaxLimitOrderVolume",
        "MaxMarketOrderVolume",
        "MinLimitOrderVolume",
    }
