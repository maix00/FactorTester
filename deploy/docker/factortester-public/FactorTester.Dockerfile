FROM python:3.14-slim@sha256:ce40764625a4ff50df3548277632e7f96c4e77fe75fa848aae9885476e7df5a4

ARG FACTORTESTER_REVISION
ARG FACTORTESTER_UID=1000
ARG FACTORTESTER_GID=1000
ARG DEBIAN_MIRROR=https://deb.debian.org/debian
ARG DEBIAN_SECURITY_MIRROR=https://deb.debian.org/debian-security
ARG PIP_INDEX_URL=https://pypi.org/simple

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
        curl \
        git \
        gosu \
        iproute2 \
        iptables \
        procps \
        tini \
        wireguard-tools \
    && rm -rf /var/lib/apt/lists/*

COPY deploy/requirements-public-linux.txt /tmp/requirements-public-linux.txt
RUN python -m pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" --upgrade pip \
    && python -m pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" \
        -r /tmp/requirements-public-linux.txt

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
COPY templates templates
COPY static static
COPY docs docs
COPY apple/Resources apple/Resources
COPY settings.py start_server.py ./
COPY deploy/docker/factortester-public/factortester-entrypoint.sh \
    /usr/local/bin/factortester-public-entrypoint
COPY deploy/docker/factortester-public/start-fixed-service.py \
    /usr/local/bin/start-fixed-service
RUN set -eu; \
    mkdir /opt/factortester/app/.git; \
    printf '%s\n' "$FACTORTESTER_REVISION" > /opt/factortester/app/.deployment-revision; \
    chmod 0555 /usr/local/bin/factortester-public-entrypoint \
        /usr/local/bin/start-fixed-service; \
    find /opt/factortester/app -type d -exec chmod 0555 {} +; \
    find /opt/factortester/app -type f -exec chmod 0444 {} +

LABEL org.opencontainers.image.revision="$FACTORTESTER_REVISION"

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/factortester-public-entrypoint"]
