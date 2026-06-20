from __future__ import annotations

from pathlib import Path

from tools.data.tech_docs import data_dictionary_cache as cache_module


def test_data_dictionary_cache_reuses_payload_when_state_unchanged(monkeypatch):
    payload = {"generated_at": "2026-06-17 12:00:00"}
    calls: list[str] = []

    monkeypatch.setattr(
        cache_module,
        "_build_cache_state",
        lambda: (("tools/a.py", 1),),
    )
    monkeypatch.setattr(
        cache_module,
        "build_data_dictionary",
        lambda: calls.append("build") or object(),
    )
    monkeypatch.setattr(
        cache_module,
        "data_dictionary_to_dict",
        lambda _: payload,
    )

    cache_module.invalidate_data_dictionary_cache()
    assert cache_module.load_data_dictionary_cache() == payload
    assert cache_module.load_data_dictionary_cache() == payload
    assert calls == ["build"]


def test_data_dictionary_cache_rebuilds_after_state_changes(monkeypatch):
    states = iter([
        (("tools/a.py", 1),),
        (("tools/a.py", 2),),
    ])
    payloads = iter([
        {"generated_at": "a"},
        {"generated_at": "b"},
    ])

    monkeypatch.setattr(cache_module, "_build_cache_state", lambda: next(states))
    monkeypatch.setattr(cache_module, "build_data_dictionary", lambda: object())
    monkeypatch.setattr(cache_module, "data_dictionary_to_dict", lambda _: next(payloads))

    cache_module.invalidate_data_dictionary_cache()
    assert cache_module.load_data_dictionary_cache()["generated_at"] == "a"
    assert cache_module.load_data_dictionary_cache()["generated_at"] == "b"


def test_iter_tracked_files_only_collects_python_inputs(monkeypatch, tmp_path: Path):
    root = tmp_path / "repo"
    tools_dir = root / "tools"
    tools_dir.mkdir(parents=True)
    (root / "Settings.py").write_text("X = 1\n")
    (tools_dir / "a.py").write_text("pass\n")
    (tools_dir / "b.pyi").write_text("...\n")
    (tools_dir / "c.txt").write_text("ignored\n")
    (root / "Factors").mkdir()
    (root / "sources").mkdir()

    monkeypatch.setattr(cache_module, "_repo_root", lambda: root)
    files = cache_module._iter_tracked_files()
    names = {path.name for path in files}
    assert names == {"Settings.py", "a.py", "b.pyi"}
