#!/usr/bin/env bash

set -Eeuo pipefail

backup_dir="${1:-/data/backups/field-history}"
retention="${2:-3}"

if [[ ! "$retention" =~ ^[1-9][0-9]*$ ]]; then
  echo "field-history backup retention must be a positive integer" >&2
  exit 2
fi

mkdir -p "$backup_dir"
python - "$backup_dir" "$retention" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
retention = int(sys.argv[2])
backups = sorted(
    root.glob("unifieddata-before-*.sqlite"),
    key=lambda path: path.stat().st_mtime_ns,
    reverse=True,
)
for path in backups[retention:]:
    path.unlink(missing_ok=True)
    Path(f"{path}-wal").unlink(missing_ok=True)
    Path(f"{path}-shm").unlink(missing_ok=True)
print(
    f"field_history_backups_retained={min(len(backups), retention)} "
    f"pruned={max(len(backups) - retention, 0)}"
)
PY
