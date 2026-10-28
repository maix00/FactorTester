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

FROM python:3.14-slim@sha256:ce40764625a4ff50df3548277632e7f96c4e77fe75fa848aae9885476e7df5a4

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

COPY --from=alpha-builder /wheels /tmp/alpha-wheels
RUN python -m pip install --no-cache-dir --no-deps /tmp/alpha-wheels/*.whl \
    && rm -rf /tmp/alpha-wheels \
    && python -c "from alpha.factor.annotations import ExpressionAnnotations"

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
