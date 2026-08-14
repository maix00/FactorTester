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
RUN chmod 0555 /usr/local/bin/factortester-manager-entrypoint

USER factortester
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/factortester-manager-entrypoint"]
