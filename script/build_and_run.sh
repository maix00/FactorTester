#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-run}"
APP_NAME="FTClient"
BUNDLE_ID="com.gtht.client"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APPLE_DIR="$ROOT_DIR/apple"
PROJECT="$APPLE_DIR/FactorTester-Client.xcodeproj"
DERIVED_DATA="$APPLE_DIR/build"
APP_BUNDLE="$DERIVED_DATA/Build/Products/Release/$APP_NAME.app"
APP_BINARY="$APP_BUNDLE/Contents/MacOS/$APP_NAME"
INSTALLED_APP="/Applications/$APP_NAME.app"
DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
export DEVELOPER_DIR

pkill -x "$APP_NAME" >/dev/null 2>&1 || true

xcodegen generate --spec "$APPLE_DIR/project.yml" --project "$APPLE_DIR"
xcodebuild \
  -project "$PROJECT" \
  -scheme FactorTester-Client-macOS \
  -configuration Release \
  -derivedDataPath "$DERIVED_DATA" \
  CODE_SIGNING_ALLOWED=NO \
  build

open_app() {
  /usr/bin/open -n "$APP_BUNDLE"
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
}

case "$MODE" in
  run)
    open_app
    ;;
  --debug|debug)
    lldb -- "$APP_BINARY"
    ;;
  --logs|logs)
    open_app
    /usr/bin/log stream --info --style compact \
      --predicate "process == \"$APP_NAME\""
    ;;
  --telemetry|telemetry)
    open_app
    /usr/bin/log stream --info --style compact \
      --predicate "subsystem == \"$BUNDLE_ID\""
    ;;
  --verify|verify)
    open_app
    sleep 2
    pgrep -x "$APP_NAME" >/dev/null
    ;;
  --install|install)
    staging="/Applications/.$APP_NAME.staging.$$"
    trap 'rm -rf "$staging"' EXIT
    test -f "$APP_BUNDLE/Contents/Resources/FactorTester/bundle-receipt.json"
    rm -rf "$staging"
    ditto "$APP_BUNDLE" "$staging"
    verify_install "$APP_BUNDLE" "$staging"
    rm -rf "$INSTALLED_APP"
    mv "$staging" "$INSTALLED_APP"
    verify_install "$APP_BUNDLE" "$INSTALLED_APP"
    ;;
  *)
    echo "usage: $0 [run|--debug|--logs|--telemetry|--verify|--install]" >&2
    exit 2
    ;;
esac
