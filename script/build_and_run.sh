#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-run}"
APP_NAME="FTClient"
BUNDLE_ID="com.gtht.client"
SIGNING_IDENTITY="${FTCLIENT_SIGNING_IDENTITY:-FTClient Beta Release}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APPLE_DIR="$ROOT_DIR/apple"
PROJECT="$APPLE_DIR/FactorTester-Client.xcodeproj"
DERIVED_DATA="$APPLE_DIR/build"
APP_BUNDLE="$DERIVED_DATA/Build/Products/Release/$APP_NAME.app"
APP_BINARY="$APP_BUNDLE/Contents/MacOS/$APP_NAME"
INSTALLED_APP="/Applications/$APP_NAME.app"
DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
export DEVELOPER_DIR

STAGING_PATH=""
cleanup_staging() {
  if test -n "${STAGING_PATH:-}"; then
    rm -rf "$STAGING_PATH"
  fi
}
trap cleanup_staging EXIT

pkill -x "$APP_NAME" >/dev/null 2>&1 || true

xcodegen generate --spec "$APPLE_DIR/project.yml" --project "$APPLE_DIR"
xcodebuild \
  -project "$PROJECT" \
  -scheme FactorTester-Client-macOS \
  -configuration Release \
  -derivedDataPath "$DERIVED_DATA" \
  CODE_SIGNING_ALLOWED=NO \
  build

sign_app() {
  if ! /usr/bin/security find-identity -v -p codesigning |
      /usr/bin/grep -Fq "\"$SIGNING_IDENTITY\""; then
    echo "missing stable code-signing identity: $SIGNING_IDENTITY" >&2
    echo "refusing an ad-hoc build because it invalidates macOS privacy grants after updates" >&2
    exit 1
  fi
  /usr/bin/codesign --force --deep --sign "$SIGNING_IDENTITY" \
    --options runtime --timestamp=none "$APP_BUNDLE"
  /usr/bin/codesign --verify --deep --strict "$APP_BUNDLE"
  local requirement
  requirement="$(designated_requirement "$APP_BUNDLE")"
  if test -z "$requirement" || [[ "$requirement" == *"cdhash"* ]]; then
    echo "stable designated requirement was not produced" >&2
    exit 1
  fi
}

designated_requirement() {
  /usr/bin/codesign -dr - "$1" 2>&1 |
    /usr/bin/sed -n 's/^designated => /designated => /p'
}

require_same_identity() {
  local candidate="$1"
  local current="$2"
  test -d "$current" || return 0
  local candidate_requirement current_requirement
  candidate_requirement="$(designated_requirement "$candidate")"
  current_requirement="$(designated_requirement "$current")"
  if test -z "$candidate_requirement" ||
      test "$candidate_requirement" != "$current_requirement"; then
    echo "signature identity changed; refusing to replace $current" >&2
    echo "candidate: $candidate_requirement" >&2
    echo "current:   $current_requirement" >&2
    exit 1
  fi
}

sign_app

open_app() {
  /usr/bin/open -n "$INSTALLED_APP"
}

bundle_hash() {
  (
    cd "$1"
    find . -type f -print0 | LC_ALL=C sort -z |
      xargs -0 shasum -a 256 | shasum -a 256 | awk '{print $1}'
  )
}

verify_install() {
  local source="$1"
  local installed="$2"
  local source_plist="$source/Contents/Info.plist"
  local installed_plist="$installed/Contents/Info.plist"
  local key
  for key in CFBundleIdentifier CFBundleShortVersionString CFBundleVersion; do
    test "$(/usr/libexec/PlistBuddy -c "Print :$key" "$source_plist")" = \
      "$(/usr/libexec/PlistBuddy -c "Print :$key" "$installed_plist")"
  done
  test "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$installed_plist")" = \
    "$BUNDLE_ID"
  test "$(bundle_hash "$source")" = "$(bundle_hash "$installed")"
  local cli="Contents/Resources/FactorTester/bin/factortester"
  local receipt="Contents/Resources/FactorTester/bundle-receipt.json"
  test -x "$installed/$cli"
  test -f "$installed/$receipt"
  test "$(shasum -a 256 "$source/$cli" | awk '{print $1}')" = \
    "$(shasum -a 256 "$installed/$cli" | awk '{print $1}')"
  /usr/bin/python3 - "$installed" <<'PY'
import hashlib, json, pathlib, sys
app = pathlib.Path(sys.argv[1])
root = app / "Contents/Resources/FactorTester"
receipt = json.loads((root / "bundle-receipt.json").read_text())
cli = root / "bin/factortester"
assert hashlib.sha256(cli.read_bytes()).hexdigest() == receipt["files"]["bin/factortester"]
PY
  require_same_identity "$source" "$installed"
}

install_app() {
  STAGING_PATH="/Applications/.$APP_NAME.staging.$$"
  test -f "$APP_BUNDLE/Contents/Resources/FactorTester/bundle-receipt.json"
  require_same_identity "$APP_BUNDLE" "$INSTALLED_APP"
  rm -rf "$STAGING_PATH"
  ditto "$APP_BUNDLE" "$STAGING_PATH"
  verify_install "$APP_BUNDLE" "$STAGING_PATH"
  rm -rf "$INSTALLED_APP"
  mv "$STAGING_PATH" "$INSTALLED_APP"
  STAGING_PATH=""
  verify_install "$APP_BUNDLE" "$INSTALLED_APP"
}

case "$MODE" in
  run)
    install_app
    open_app
    ;;
  --debug|debug)
    lldb -- "$APP_BINARY"
    ;;
  --logs|logs)
    install_app
    open_app
    /usr/bin/log stream --info --style compact \
      --predicate "process == \"$APP_NAME\""
    ;;
  --telemetry|telemetry)
    install_app
    open_app
    /usr/bin/log stream --info --style compact \
      --predicate "subsystem == \"$BUNDLE_ID\""
    ;;
  --verify|verify)
    install_app
    open_app
    sleep 2
    pgrep -x "$APP_NAME" >/dev/null
    ;;
  --install|install)
    install_app
    ;;
  *)
    echo "usage: $0 [run|--debug|--logs|--telemetry|--verify|--install]" >&2
    exit 2
    ;;
esac
