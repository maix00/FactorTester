#!/usr/bin/env bash
set -Eeuo pipefail

state_root="${FACTORTESTER_STATE_ROOT:-/data/state}"
root_min_gb="${FACTORTESTER_MIN_ROOT_FREE_GB:-10}"
data_min_gb="${FACTORTESTER_MIN_DATA_FREE_GB:-10}"
mem_min_mb="${FACTORTESTER_MIN_MEM_AVAILABLE_MB:-1024}"
status=0
alert_file="${FACTORTESTER_CAPACITY_ALERT_FILE:-}"

free_gb() { df -Pk "$1" | awk 'NR==2 {print int($4/1024/1024)}'; }
root_free="$(free_gb /)"
data_free="$(free_gb /data 2>/dev/null || echo 0)"
mem_available="$(awk '/MemAvailable:/ {print int($2/1024)}' /proc/meminfo)"
index="$state_root/job-index.sqlite"
index_gb=0
events=0
if [[ -f "$index" ]]; then
  index_gb="$(du -m "$index" | awk '{print int($1/1024)}')"
  events="$(python3 - "$index" <<'PY'
import sqlite3, sys
try:
    connection = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
    print(connection.execute("SELECT COUNT(*) FROM control_events").fetchone()[0])
except Exception:
    print(0)
PY
)"
fi

printf 'root_free_gb=%s data_free_gb=%s mem_available_mb=%s job_index_gb=%s control_events=%s\n' \
  "$root_free" "$data_free" "$mem_available" "$index_gb" "$events"
(( root_free >= root_min_gb )) || { echo "root free space below ${root_min_gb}G" >&2; status=1; }
(( data_free >= data_min_gb )) || { echo "data free space below ${data_min_gb}G" >&2; status=1; }
(( mem_available >= mem_min_mb )) || { echo "MemAvailable below ${mem_min_mb}MB" >&2; status=1; }
if [[ -n "$alert_file" ]]; then
  if (( status != 0 )); then
    mkdir -p "$(dirname "$alert_file")"
    date -u +%Y-%m-%dT%H:%M:%SZ > "$alert_file"
  else
    rm -f "$alert_file"
  fi
fi
exit "$status"
