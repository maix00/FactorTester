"""Exact canonical Graph v1-v3 recovery artifact metadata."""

from __future__ import annotations

from pathlib import Path


_SOURCES = {
    1: "689e141e78c90d5cbb6d7b96e236919056db7525",
    2: "689e141e78c90d5cbb6d7b96e236919056db7525",
    3: "f1ac3d3b46e17120647ac958ba369f0999e90a4c",
}


def compressed_history_artifacts() -> dict[int, tuple[str, str]]:
    root = Path(__file__).with_name("history")
    return {
        version: (
            source_commit,
            (root / f"factor-research-v{version}.json.gz.b64")
            .read_text(encoding="ascii")
            .strip(),
        )
        for version, source_commit in _SOURCES.items()
    }

