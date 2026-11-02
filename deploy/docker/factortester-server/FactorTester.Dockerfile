# Build the pinned alpha submodule for the deployment architecture once.
FROM rust:1.99-slim AS alpha-builder
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv python3-dev \
    && python3 -m venv /build-env && /build-env/bin/pip install --no-cache-dir maturin==1.15.0
COPY vendor/py-alpha-lib /src/alpha
ENV CARGO_BUILD_JOBS=2
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/src/alpha/target \
    /build-env/bin/maturin build --release --manifest-path /src/alpha/py-binding/Cargo.toml \
    --interpreter /build-env/bin/python --out /wheels

FROM python:3.14-slim@sha256:ce40764625a4ff50df3548277632e7f96c4e77fe75fa848aae9885476e7df5a4 AS manager-base

ARG FACTORTESTER_UID=1000
ARG FACTORTESTER_GID=1000

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    sed -i 's|http://deb.debian.org|https://deb.debian.org|g' \
        /etc/apt/sources.list.d/debian.sources \
    && apt-get \
        -o Acquire::Retries=5 \
        -o Acquire::http::Timeout=30 \
        -o Acquire::https::Timeout=30 \
        update \
    && apt-get \
        -o Acquire::Retries=5 \
        -o Acquire::http::Timeout=30 \
        -o Acquire::https::Timeout=30 \
        install --yes --no-install-recommends \
        ca-certificates \
        curl \
        git \
        lsof \
        procps \
        tini

COPY deploy/requirements-linux.txt /tmp/requirements-linux.txt
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r /tmp/requirements-linux.txt

RUN set -eu; \
    if ! getent group "${FACTORTESTER_GID}" >/dev/null; then \
        groupadd --gid "${FACTORTESTER_GID}" factortester; \
    fi; \
    group_name="$(getent group "${FACTORTESTER_GID}" | cut -d: -f1)"; \
    useradd \
        --create-home \
        --uid "${FACTORTESTER_UID}" \
        --gid "${group_name}" \
        --shell /bin/sh \
        factortester; \
    git config --system --add safe.directory '*'

COPY deploy/docker/factortester-server/manager-entrypoint.sh \
    /usr/local/bin/factortester-manager-entrypoint
COPY deploy/docker/factortester-server/start-fixed-service.py \
    /usr/local/bin/start-fixed-service
RUN chmod 0555 \
    /usr/local/bin/factortester-manager-entrypoint \
    /usr/local/bin/start-fixed-service

USER factortester
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/factortester-manager-entrypoint"]

# Keep native alpha outside the reusable Python dependency base. Even when
# manager-base is supplied as an immutable image, this stage installs the exact
# checked-out alpha wheel, replacing any older alpha bundled in that image.
FROM manager-base AS manager-runtime
USER root
COPY --from=alpha-builder /wheels /tmp/alpha-wheels
RUN python -m pip install --no-cache-dir --no-deps --force-reinstall /tmp/alpha-wheels/*.whl \
    && rm -rf /tmp/alpha-wheels \
    && python -c "from alpha.factor.annotations import ExpressionAnnotations"
USER factortester

# The CLI is the same small, isolated package used in the public image.
FROM manager-runtime AS traderesearch-local-cli-builder
USER root
COPY tools/cli /runtime/tools/cli
COPY deploy/docker/factortester-public/traderesearch-cli /build/traderesearch-cli
RUN python -m compileall -q -b /runtime \
    && find /runtime -type f -name '*.py' -delete \
    && find /runtime -type d -name __pycache__ -prune -exec rm -rf {} + \
    && PYTHONPATH=/runtime /build/traderesearch-cli --help >/tmp/traderesearch-help \
    && grep -F 'TradeResearch CLI' /tmp/traderesearch-help >/dev/null

# Keep Agent layers after the pinned alpha runtime. A reviewed immutable
# manager-base override reuses only the unchanged Python/system dependencies.
FROM manager-runtime AS traderesearch-local-manager
USER root
ARG TARGETARCH
ARG CODEX_VERSION=0.147.0
ARG CODEX_NPM_REGISTRY=https://registry.npmjs.org
ARG DEBIAN_MIRROR=https://deb.debian.org/debian
ARG DEBIAN_SECURITY_MIRROR=https://deb.debian.org/debian-security
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    sed -i \
      -e "s|https\\?://deb.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR}|g" \
      -e "s|https\\?://deb.debian.org/debian|${DEBIAN_MIRROR}|g" \
      /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install --yes --no-install-recommends bubblewrap=0.12.0-1~deb13u1 \
    && chmod 0755 /usr/bin/bwrap
COPY deploy/docker/factortester-public/cc-switch-cli-linux-x64-musl-v5.10.2.tar.gz /tmp/cc-switch-linux-x64-musl.tgz
COPY deploy/docker/factortester-public/cc-switch-cli-linux-arm64-musl-v5.10.2.tar.gz /tmp/cc-switch-linux-arm64-musl.tgz
COPY deploy/docker/factortester-server/install-agent-tools.sh /tmp/install-agent-tools.sh
RUN TARGETARCH="${TARGETARCH}" CODEX_VERSION="${CODEX_VERSION}" CODEX_NPM_REGISTRY="${CODEX_NPM_REGISTRY}" \
    sh /tmp/install-agent-tools.sh && rm -f /tmp/install-agent-tools.sh
COPY --from=traderesearch-local-cli-builder /runtime /usr/local/lib/traderesearch-cli
COPY deploy/docker/factortester-public/traderesearch-cli /usr/local/bin/traderesearch
RUN set -eu; \
    rm -f /usr/local/bin/factortester /usr/local/bin/factortester-manager; \
    chmod 0555 /usr/local/bin/traderesearch; \
    test -x /usr/local/bin/bwrap; \
    test ! -e /usr/local/bin/factortester; \
    test ! -e /usr/local/bin/factortester-manager; \
    traderesearch --help >/tmp/traderesearch-help; \
    grep -F 'TradeResearch CLI' /tmp/traderesearch-help >/dev/null; \
    rm -f /tmp/traderesearch-help
USER factortester
