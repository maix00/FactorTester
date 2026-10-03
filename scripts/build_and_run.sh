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

# Xcode gives every worktree/test invocation its own DerivedData directory.
# Those Debug app bundles are discoverable by Spotlight and look like many
# installed clients even though only /Applications/FTClient.app is released.
# Keep the cleanup exact to this project's generated directories; never clean
# arbitrary DerivedData or the release output owned by this script.
cleanup_stale_debug_artifacts() {
  if test "${FTCLIENT_SKIP_DEBUG_CLEANUP:-0}" = "1"; then
    echo "skipping stale FTClient DerivedData cleanup (FTCLIENT_SKIP_DEBUG_CLEANUP=1)"
    return
  fi
  local derived_root="${HOME:-}/Library/Developer/Xcode/DerivedData"
  if test -z "${HOME:-}" || test "$HOME" = "/" ||
     test "$derived_root" != "$HOME/Library/Developer/Xcode/DerivedData" ||
     test ! -d "$derived_root"; then
    return
  fi
  local path
  while IFS= read -r -d '' path; do
    echo "removing stale FTClient Debug artifact: $path"
    rm -rf -- "$path"
  done < <(
    find "$derived_root" -maxdepth 1 -type d \
      -name 'FactorTester-Client-*' -print0
  )
}

# This script owns only the FTClient process.  FactorTester Manager, Docker
# Compose, WireGuard, and test-service ports are server deployment concerns;
# building or launching the client must never restart them.

STAGING_PATH=""
cleanup_staging() {
  if test -n "${STAGING_PATH:-}"; then
    rm -rf "$STAGING_PATH"
  fi
}
trap cleanup_staging EXIT

pkill -x "$APP_NAME" >/dev/null 2>&1 || true
cleanup_stale_debug_artifacts

xcodegen generate --spec "$APPLE_DIR/project.yml" --project "$APPLE_DIR"
XCODEBUILD_ARGS=(
  -project "$PROJECT"
  -scheme FactorTester-Client-macOS
  -configuration Release
  -derivedDataPath "$DERIVED_DATA"
  CODE_SIGNING_ALLOWED=NO
)
if test -n "${FTCLIENT_MARKETING_VERSION:-}"; then
  XCODEBUILD_ARGS+=("MARKETING_VERSION=$FTCLIENT_MARKETING_VERSION")
fi
if test -n "${FTCLIENT_BUILD_NUMBER:-}"; then
  XCODEBUILD_ARGS+=("CURRENT_PROJECT_VERSION=$FTCLIENT_BUILD_NUMBER")
fi
xcodebuild \
  "${XCODEBUILD_ARGS[@]}" build

SOURCE_REVISION="$(git -C "$ROOT_DIR" rev-parse HEAD)"
APP_VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' \
  "$APP_BUNDLE/Contents/Info.plist")"
PYTHON_BIN="${FTCLIENT_PYTHON:-$(command -v python || command -v python3)}"
if ! "$PYTHON_BIN" -c \
    'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "FTClient runtime build requires Python 3.11 or newer: $PYTHON_BIN" >&2
  exit 1
fi
(
  cd "$ROOT_DIR"
  "$PYTHON_BIN" -m scripts.release.embed_runtime \
    --app "$APP_BUNDLE" \
    --version "bundle-$APP_VERSION-r$SOURCE_REVISION" \
    --source-revision "$SOURCE_REVISION"
)

sign_app() {
  if ! /usr/bin/security find-identity -v -p codesigning |
      /usr/bin/grep -Fq "\"$SIGNING_IDENTITY\""; then
    echo "missing stable code-signing identity: $SIGNING_IDENTITY" >&2
    echo "refusing an ad-hoc build because it invalidates macOS privacy grants after updates" >&2
    exit 1
  fi
  local entitlements="$APPLE_DIR/Resources/macOS/FactorTester-Client.entitlements"
  test -f "$entitlements"
  /usr/bin/codesign --force --deep --sign "$SIGNING_IDENTITY" \
    --options runtime --timestamp=none \
    --entitlements "$entitlements" "$APP_BUNDLE"
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
  local source_build installed_build
  source_build="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$source_plist")"
  installed_build="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$installed_plist")"
  if test "$source_build" -lt "$installed_build"; then
    echo "refusing to install an older client build: $source_build < $installed_build" >&2
    return 1
  fi
  local cli="Contents/Resources/FactorTester/bin/factortester"
  local manager_cli="Contents/Resources/FactorTester/bin/factortester-manager"
  local report_renderer="Contents/Resources/FactorTester/bin/factortester-report-renderer"
  local receipt="Contents/Resources/FactorTester/bundle-receipt.json"
  test -x "$installed/$cli"
  test -x "$installed/$manager_cli"
  test -x "$installed/$report_renderer"
  test -f "$installed/$receipt"
  test "$(shasum -a 256 "$source/$cli" | awk '{print $1}')" = \
    "$(shasum -a 256 "$installed/$cli" | awk '{print $1}')"
  if ! /usr/bin/codesign -d --entitlements :- "$installed" 2>&1 |
      /usr/bin/grep -Fq "com.apple.security.cs.disable-library-validation"; then
    echo "installed app is missing Sparkle library-validation entitlement" >&2
    return 1
  fi
  /usr/bin/python3 - "$installed" <<'PY'
import hashlib, json, pathlib, sys
import re
app = pathlib.Path(sys.argv[1])
root = app / "Contents/Resources/FactorTester"
receipt = json.loads((root / "bundle-receipt.json").read_text())
cli = root / "bin/factortester"
manager_cli = root / "bin/factortester-manager"
renderer = root / "bin/factortester-report-renderer"
assert hashlib.sha256(cli.read_bytes()).hexdigest() == receipt["files"]["bin/factortester"]
assert hashlib.sha256(manager_cli.read_bytes()).hexdigest() == receipt["files"]["bin/factortester-manager"]
assert hashlib.sha256(renderer.read_bytes()).hexdigest() == receipt["files"]["bin/factortester-report-renderer"]
assert re.fullmatch(r"[0-9a-f]{40}", str(receipt["source_revision"]))
PY
  "$installed/$cli" --help >/dev/null
  "$installed/$manager_cli" --help >/dev/null
  "$installed/$research_cli" --help >/dev/null
  "$installed/$report_renderer" --help >/dev/null
  require_same_identity "$source" "$installed"
}

install_app() {
  STAGING_PATH="/Applications/.$APP_NAME.staging.$$"
  test -f "$APP_BUNDLE/Contents/Resources/FactorTester/bundle-receipt.json"
  require_same_identity "$APP_BUNDLE" "$INSTALLED_APP"
  rm -rf "$STAGING_PATH"
  ditto "$APP_BUNDLE" "$STAGING_PATH"
  verify_install "$APP_BUNDLE" "$STAGING_PATH"
  if test -d "$INSTALLED_APP"; then
    /usr/bin/python3 - "$STAGING_PATH" "$INSTALLED_APP" <<'PY'
import ctypes
import os
import sys

libc = ctypes.CDLL(None, use_errno=True)
renameatx_np = libc.renameatx_np
renameatx_np.argtypes = [
    ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p,
    ctypes.c_uint,
]
renameatx_np.restype = ctypes.c_int
AT_FDCWD = -2
RENAME_SWAP = 0x00000002
source, target = (os.fsencode(value) for value in sys.argv[1:3])
if renameatx_np(
    AT_FDCWD, source, AT_FDCWD, target, RENAME_SWAP
) != 0:
    error = ctypes.get_errno()
    raise OSError(error, os.strerror(error))
PY
    # After the atomic exchange the staging path contains the previous app.
    rm -rf "$STAGING_PATH"
    STAGING_PATH=""
  else
    mv "$STAGING_PATH" "$INSTALLED_APP"
    STAGING_PATH=""
  fi
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
