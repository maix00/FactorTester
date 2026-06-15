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
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
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
    monkeypatch.setattr(_store, "CACHE_DB_PATH", tmp_path / "localdata" / "unifieddata.sqlite")

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
