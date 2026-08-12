#!/bin/sh
set -eu

# Hosted and UI tests launch an FTClient bundle with the production bundle ID.
# Running that host unsigned makes macOS treat it as a different application
# and invalidates the user's existing Documents authorization.
identity="${FTCLIENT_CODE_SIGN_IDENTITY:-FTClient Beta Release}"
project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
developer_dir="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"

if ! /usr/bin/security find-identity -p codesigning -v \
    | /usr/bin/grep -F "\"${identity}\"" >/dev/null; then
    echo "Missing persistent FTClient signing identity: ${identity}" >&2
    exit 2
fi

exec /usr/bin/env DEVELOPER_DIR="${developer_dir}" \
    /usr/bin/xcodebuild test \
    -project "${project_root}/FactorTester-Client.xcodeproj" \
    -scheme FactorTester-Client-macOS \
    -configuration Debug \
    -destination "platform=macOS,arch=arm64" \
    -derivedDataPath "${project_root}/build/DerivedData" \
    CODE_SIGN_STYLE=Manual \
    CODE_SIGN_IDENTITY="${identity}" \
    "$@"
