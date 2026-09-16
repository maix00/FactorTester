FROM python:3.14-slim@sha256:ce40764625a4ff50df3548277632e7f96c4e77fe75fa848aae9885476e7df5a4 AS factortester-public-deps

ARG FACTORTESTER_UID=1000
ARG FACTORTESTER_GID=1000
ARG DEBIAN_MIRROR=https://deb.debian.org/debian
ARG DEBIAN_SECURITY_MIRROR=https://deb.debian.org/debian-security
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG CODEX_VERSION=0.147.0
ARG CODEX_NPM_REGISTRY=https://registry.npmjs.org
ARG TARGETARCH
ARG MIHOMO_ARCHIVE_SHA256=db214c7a2517e63c150d123178d16d102e03a241ccdae4e5e07ffbe9cf56c6f9

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN sed -i \
        -e "s|https\?://deb.debian.org/debian|${DEBIAN_MIRROR}|g" \
        -e "s|https\?://deb.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR}|g" \
        /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install --yes --no-install-recommends \
        ca-certificates \
        bubblewrap \
        curl \
        fonts-noto-cjk \
        git \
        gosu \
        iproute2 \
        iptables \
        procps \
        ripgrep \
        tini \
        wireguard-tools \
    && chmod u+s /usr/bin/bwrap \
    && rm -rf /var/lib/apt/lists/*

COPY deploy/requirements-public-linux.txt /tmp/requirements-public-linux.txt
RUN python -m pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" --upgrade pip \
    && python -m pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" \
        -r /tmp/requirements-public-linux.txt

FROM factortester-public-deps AS factortester-cli-builder

COPY tools/cli /runtime/tools/cli
COPY deploy/docker/factortester-public/factortester-cli /build/factortester-cli
RUN python -m compileall -q -b /runtime \
    && find /runtime -type f -name '*.py' -delete \
    && find /runtime -type d -name __pycache__ -prune -exec rm -rf {} + \
    && PYTHONPATH=/runtime /build/factortester-cli --help \
        >/tmp/factortester-help \
    && grep -F 'FactorTester CLI' /tmp/factortester-help >/dev/null

FROM factortester-public-deps AS factortester-public

# The npm package is a small launcher around the platform package. Install
# only the official native Linux binary, so the image needs neither npm nor a
# second Node runtime and the existing Python dependency layer stays cached.
ARG CODEX_VERSION=0.147.0
ARG CODEX_NPM_REGISTRY=https://registry.npmjs.org
ARG TARGETARCH
RUN set -eu; \
    case "${TARGETARCH}" in \
        amd64) \
            codex_target=x86_64-unknown-linux-musl; \
            codex_platform=linux-x64; \
            codex_sha512=0W9MBxPpWW0cSkNqrTDN2jR7rzzT7oNMhQY5446lT2Lw5cz5yhDTck4Va9rjkQEm+HlFzP/dmEMSZbXfJsINmw== ;; \
        arm64) \
            codex_target=aarch64-unknown-linux-musl; \
            codex_platform=linux-arm64; \
            codex_sha512=SLC1JXw2TYfr/c3HhrJubyyLelq7vTOLWVmiThFA+z0+WgzCPmaseJ/kzDD3Gge/TO7fCnnj7UcPmC0d2c8XAg== ;; \
        *) echo "unsupported Codex architecture: ${TARGETARCH}" >&2; exit 2 ;; \
    esac; \
    codex_url="${CODEX_NPM_REGISTRY%/}/@openai/codex/-/codex-${CODEX_VERSION}-${codex_platform}.tgz"; \
    curl --fail --location --retry 5 --retry-delay 2 \
        --connect-timeout 20 --max-time 900 \
        --output /tmp/codex.tgz "${codex_url}"; \
    python -c 'import base64, hashlib, sys; expected = base64.b64decode(sys.argv[1]); actual = hashlib.file_digest(open(sys.argv[2], "rb"), "sha512").digest(); assert actual == expected, "Codex platform package integrity check failed"' \
        "${codex_sha512}" /tmp/codex.tgz; \
    mkdir -p /tmp/codex-package; \
    tar -xzf /tmp/codex.tgz --strip-components=1 -C /tmp/codex-package; \
    install -m 0555 \
        "/tmp/codex-package/vendor/${codex_target}/bin/codex" \
        /usr/local/bin/codex; \
    install -m 0555 \
        "/tmp/codex-package/vendor/${codex_target}/bin/codex-code-mode-host" \
        /usr/local/bin/codex-code-mode-host; \
    test "$(codex --version)" = "codex-cli ${CODEX_VERSION}"; \
    test -x /usr/local/bin/codex-code-mode-host; \
    codex-code-mode-host --help >/tmp/codex-code-mode-host-help; \
    grep -F 'Usage: codex-code-mode-host' /tmp/codex-code-mode-host-help >/dev/null; \
    rm -f /tmp/codex-code-mode-host-help; \
    rm -rf /tmp/codex-package /tmp/codex.tgz

# CC Switch owns provider routing and wire-protocol conversion. FactorTester
# invokes this pinned headless CLI on loopback with one private state directory
# per Profile Agent session; it does not copy or fork the conversion code.
ARG CC_SWITCH_VERSION=5.10.2
COPY deploy/docker/factortester-public/cc-switch-cli-linux-x64-musl-v5.10.2.tar.gz /tmp/cc-switch-linux-x64-musl.tgz
COPY deploy/docker/factortester-public/cc-switch-cli-linux-arm64-musl-v5.10.2.tar.gz /tmp/cc-switch-linux-arm64-musl.tgz
RUN set -eu; \
    case "${TARGETARCH}" in \
        amd64) \
            cc_switch_archive=/tmp/cc-switch-linux-x64-musl.tgz; \
            cc_switch_sha256=8065c5bae9eda270747c1766cefbb2091d9625655dbf409ad7764eb47c0a8635 ;; \
        arm64) \
            cc_switch_archive=/tmp/cc-switch-linux-arm64-musl.tgz; \
            cc_switch_sha256=b25c77f7eebbe3968c53022e1b5e703e324203e94e5c6379320bcd1bbe268e63 ;; \
        *) echo "unsupported CC Switch architecture: ${TARGETARCH}" >&2; exit 2 ;; \
    esac; \
    echo "${cc_switch_sha256}  ${cc_switch_archive}" | sha256sum --check --status; \
    tar -xzf "${cc_switch_archive}" -C /tmp; \
    install -m 0555 /tmp/cc-switch /usr/local/bin/cc-switch; \
    cc-switch --version; \
    rm -f /tmp/cc-switch /tmp/cc-switch-linux-*.tgz

# Pin the upstream Mihomo binary in the image. The Manager never publishes
# its controller or mixed proxy ports; both remain loopback-only.
COPY deploy/docker/factortester-public/mihomo-linux-amd64-v1.19.30.gz /tmp/mihomo.gz
RUN set -eu; \
    echo "${MIHOMO_ARCHIVE_SHA256}  /tmp/mihomo.gz" | sha256sum --check --status; \
    gzip -dc /tmp/mihomo.gz > /usr/local/bin/mihomo; \
    chmod 0555 /usr/local/bin/mihomo; \
    rm -f /tmp/mihomo.gz

ARG FACTORTESTER_REVISION
RUN set -eu; \
    case "${FACTORTESTER_REVISION:-}" in \
        *[!0-9a-f]*|'') echo 'FACTORTESTER_REVISION must be a full Git SHA' >&2; exit 2 ;; \
    esac; \
    test "${#FACTORTESTER_REVISION}" = 40; \
    if ! getent group "${FACTORTESTER_GID}" >/dev/null; then \
        groupadd --gid "${FACTORTESTER_GID}" factortester; \
    fi; \
    group_name="$(getent group "${FACTORTESTER_GID}" | cut -d: -f1)"; \
    useradd --create-home --uid "${FACTORTESTER_UID}" \
        --gid "${group_name}" --shell /bin/sh factortester; \
    install -d -o root -g root -m 0755 /opt/factortester/app; \
    install -d -o factortester -g "${group_name}" /state /data; \
    install -d -m 0700 /etc/wireguard

WORKDIR /opt/factortester/app
COPY server server
COPY tools tools
COPY sources sources
COPY scripts scripts
COPY static static
COPY docs docs
COPY product_docs product_docs
COPY skills skills
COPY apple/Resources apple/Resources
COPY apple/Sources/Navigation apple/Sources/Navigation
COPY settings.py start_server.py ./
COPY deploy/docker/factortester-public/factortester-entrypoint.sh \
    /usr/local/bin/factortester-public-entrypoint
COPY deploy/docker/factortester-public/start-fixed-service.py \
    /usr/local/bin/start-fixed-service
COPY --from=factortester-cli-builder /runtime \
    /usr/local/lib/factortester-cli
COPY deploy/docker/factortester-public/factortester-cli \
    /usr/local/bin/factortester
RUN set -eu; \
    rm -f /usr/local/bin/factortester-manager; \
    test -x /usr/local/bin/factortester; \
    test ! -e /usr/local/bin/factortester-manager; \
    factortester --help >/tmp/factortester-help; \
    grep -F 'FactorTester CLI' /tmp/factortester-help >/dev/null; \
    rm -f /tmp/factortester-help; \
    mkdir /opt/factortester/app/.git; \
    printf '%s\n' "$FACTORTESTER_REVISION" > /opt/factortester/app/.deployment-revision; \
    chmod 0555 /usr/local/bin/factortester \
        /usr/local/bin/factortester-public-entrypoint \
        /usr/local/bin/start-fixed-service; \
    find /opt/factortester/app -type d -exec chmod 0555 {} +; \
    find /opt/factortester/app -type f -exec chmod 0444 {} +

LABEL org.opencontainers.image.revision="$FACTORTESTER_REVISION"

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/factortester-public-entrypoint"]
