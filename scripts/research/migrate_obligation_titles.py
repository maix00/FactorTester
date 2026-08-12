"""One-time CLI for reviewed Research Cycle Chinese-title migration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from server.services.research_graph.obligation_title_migration import (
    migrate_obligation_titles,
)


DEFAULT_TITLES = (
    Path(__file__).resolve().parents[2]
    / "server/services/research_graph/obligation_title_migration"
    / "reviewed_titles.v1.json"
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", required=True, type=Path)
    parser.add_argument(
        "--title-file", type=Path, default=DEFAULT_TITLES,
        help="Reviewed JSON object containing an obligations title map",
    )
    args = parser.parse_args()
    value = json.loads(args.title_file.read_text(encoding="utf-8"))
    titles = value.get("obligations") if isinstance(value, dict) else None
    result = migrate_obligation_titles(
        db_path=args.db_path,
        titles=titles,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
