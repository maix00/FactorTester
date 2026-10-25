#!/usr/bin/env bash
# Health check for the local/intranet React-shell acceptance instance.
set -euo pipefail
BASE="${BASE:-http://127.0.0.1:8770}"
status="$(curl -sS -o /dev/null -w '%{http_code}' "$BASE/app")"
if [ "$status" != "200" ]; then
  echo "FAIL /app -> $status" >&2
  exit 1
fi
echo "OK /app -> 200"
for name in ft-couchdb ft-rabbit ft-keycloak; do
  if docker ps --format '{{.Names}}' | grep -qx "$name"; then
    echo "OK container $name"
  else
    echo "WARN container $name is not running" >&2
  fi
done
