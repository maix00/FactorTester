"""User-scoped persistent mirror for reusable Evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from tools.cli.core.sqlite import connect_client_sqlite
from tools.cli.release.research_reporting.authoring.tree_store import (
    atomic_write,
)


_DIRECTORIES = {
    "source": "sources",
    "fragment": "fragments",
    "evidence": "evidence",
    "tag": "tags",
}


class EvidenceLibrary:
    def __init__(self, personal_workspace: Path) -> None:
        self.root = Path(personal_workspace) / "evidence-library"
        for name in (*_DIRECTORIES.values(), "artifacts", "pending"):
            (self.root / name).mkdir(parents=True, exist_ok=True)

    def record_source(self, value: dict[str, Any]) -> Path:
        return self._record("source", str(value["source_ref"]), value)

    def record_fragment(self, value: dict[str, Any]) -> Path:
        return self._record("fragment", str(value["fragment_ref"]), value)

    def record_evidence(self, value: dict[str, Any]) -> Path:
        return self._record("evidence", str(value["evidence_ref"]), value)

    def record_tag(self, value: dict[str, Any]) -> Path:
        return self._record("tag", str(value["tag_ref"]), value)

    def path_for(self, kind: str, reference: str) -> Path:
        directory = _DIRECTORIES[kind]
        digest = hashlib.sha256(reference.encode()).hexdigest()
        return self.root / directory / f"{digest}.json"

    def record_artifact(
        self,
        *,
        source_ref: str,
        name: str,
        content: bytes,
    ) -> dict[str, str]:
        digest = hashlib.sha256(content).hexdigest()
        safe_name = "".join(
            character if character.isalnum() or character in "._-" else "_"
            for character in name
        ).strip("._") or "artifact.bin"
        source_id = hashlib.sha256(source_ref.encode()).hexdigest()[:16]
        relative = Path("artifacts") / source_id / f"{digest[:16]}-{safe_name}"
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(target, content)
        return {
            "relative_path": relative.as_posix(),
            "content_hash": digest,
        }

    def rebuild_index(self) -> dict[str, int]:
        index = self.root / "index.sqlite"
        temporary = self.root / "pending" / "index.sqlite.tmp"
        temporary.unlink(missing_ok=True)
        counts = {name: 0 for name in _DIRECTORIES}
        with connect_client_sqlite(temporary) as conn:
            conn.executescript("""
                CREATE TABLE catalog (
                    kind TEXT NOT NULL,
                    ref TEXT NOT NULL,
                    title_zh TEXT NOT NULL,
                    description_zh TEXT NOT NULL,
                    payload_path TEXT NOT NULL,
                    PRIMARY KEY(kind, ref)
                );
                CREATE INDEX idx_catalog_title ON catalog(title_zh);
            """)
            for kind, directory in _DIRECTORIES.items():
                for path in sorted((self.root / directory).glob("*.json")):
                    try:
                        value = json.loads(path.read_text(encoding="utf-8"))
                        reference = str(value[f"{kind}_ref"])
                    except (KeyError, OSError, json.JSONDecodeError, TypeError):
                        continue
                    conn.execute(
                        "INSERT INTO catalog VALUES (?, ?, ?, ?, ?)",
                        (
                            kind,
                            reference,
                            str(value.get("title_zh") or ""),
                            str(
                                value.get("description_zh")
                                or value.get("summary_zh")
                                or ""
                            ),
                            path.relative_to(self.root).as_posix(),
                        ),
                    )
                    counts[kind] += 1
        atomic_write(index, temporary.read_bytes())
        temporary.unlink(missing_ok=True)
        return {
            "sources": counts["source"],
            "fragments": counts["fragment"],
            "evidence": counts["evidence"],
            "tags": counts["tag"],
        }

    def _record(
        self, kind: str, reference: str, value: dict[str, Any],
    ) -> Path:
        target = self.path_for(kind, reference)
        payload = json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        ).encode() + b"\n"
        atomic_write(target, payload)
        return target
