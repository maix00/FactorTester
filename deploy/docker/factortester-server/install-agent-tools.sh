#!/bin/sh
# Shared pinned upstream Agent tools for local and public Manager images.
set -eu
: "${TARGETARCH:?set TARGETARCH}" "${CODEX_VERSION:?set CODEX_VERSION}" "${CODEX_NPM_REGISTRY:?set CODEX_NPM_REGISTRY}"
case "$TARGETARCH" in
  amd64)
    codex_target=x86_64-unknown-linux-musl
    codex_platform=linux-x64
    codex_sha512=0W9MBxPpWW0cSkNqrTDN2jR7rzzT7oNMhQY5446lT2Lw5cz5yhDTck4Va9rjkQEm+HlFzP/dmEMSZbXfJsINmw==
    cc_switch_archive=/tmp/cc-switch-linux-x64-musl.tgz
    cc_switch_sha256=8065c5bae9eda270747c1766cefbb2091d9625655dbf409ad7764eb47c0a8635
    ;;
  arm64)
    codex_target=aarch64-unknown-linux-musl
    codex_platform=linux-arm64
    codex_sha512=SLC1JXw2TYfr/c3HhrJubyyLelq7vTOLWVmiThFA+z0+WgzCPmaseJ/kzDD3Gge/TO7fCnnj7UcPmC0d2c8XAg==
    cc_switch_archive=/tmp/cc-switch-linux-arm64-musl.tgz
    cc_switch_sha256=b25c77f7eebbe3968c53022e1b5e703e324203e94e5c6379320bcd1bbe268e63
    ;;
  *) echo "unsupported Agent architecture: $TARGETARCH" >&2; exit 2 ;;
esac
test "$CODEX_VERSION" = 0.147.0 || { echo 'unverified Codex version' >&2; exit 2; }
codex_url="${CODEX_NPM_REGISTRY%/}/@openai/codex/-/codex-${CODEX_VERSION}-${codex_platform}.tgz"
curl --fail --location --retry 5 --retry-delay 2 --connect-timeout 20 --max-time 900 \
  --output /tmp/codex.tgz "$codex_url"
python -c 'import base64, hashlib, sys; expected = base64.b64decode(sys.argv[1]); actual = hashlib.file_digest(open(sys.argv[2], "rb"), "sha512").digest(); assert actual == expected, "Codex platform package integrity check failed"' \
  "$codex_sha512" /tmp/codex.tgz
mkdir -p /tmp/codex-package
tar -xzf /tmp/codex.tgz --strip-components=1 -C /tmp/codex-package
install -m 0555 "/tmp/codex-package/vendor/${codex_target}/bin/codex" /usr/local/bin/codex
install -m 0555 "/tmp/codex-package/vendor/${codex_target}/bin/codex-code-mode-host" /usr/local/bin/codex-code-mode-host
test "$(codex --version)" = "codex-cli ${CODEX_VERSION}"
codex-code-mode-host --help >/tmp/codex-code-mode-host-help
grep -F 'Usage: codex-code-mode-host' /tmp/codex-code-mode-host-help >/dev/null
echo "${cc_switch_sha256}  ${cc_switch_archive}" | sha256sum --check --status
tar -xzf "$cc_switch_archive" -C /tmp
install -m 0555 /tmp/cc-switch /usr/local/bin/cc-switch
cc-switch --version
rm -rf /tmp/codex-package /tmp/codex.tgz /tmp/codex-code-mode-host-help /tmp/cc-switch /tmp/cc-switch-linux-*.tgz
