FROM postgres:15.18-bookworm@sha256:e8db9bd3e9e1751eb639fb17be53cc6d1b62a322adf75b99e791767a7a16ce69

ARG DEBIAN_MIRROR=https://deb.debian.org/debian
ARG DEBIAN_SECURITY_MIRROR=https://deb.debian.org/debian-security
ARG DEBIAN_BOOTSTRAP_MIRROR=http://deb.debian.org/debian
ARG DEBIAN_BOOTSTRAP_SECURITY_MIRROR=http://deb.debian.org/debian-security

RUN rm -f /etc/apt/sources.list.d/pgdg.list \
    && sed -i \
        -e "s|https\?://deb.debian.org/debian|${DEBIAN_BOOTSTRAP_MIRROR}|g" \
        -e "s|https\?://deb.debian.org/debian-security|${DEBIAN_BOOTSTRAP_SECURITY_MIRROR}|g" \
        /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install --yes --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN sed -i \
        -e "s|https\?://deb.debian.org/debian|${DEBIAN_MIRROR}|g" \
        -e "s|https\?://deb.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR}|g" \
        /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install --yes --no-install-recommends \
        iproute2 \
        iptables \
        procps \
        wireguard-tools \
    && rm -rf /var/lib/apt/lists/* \
    && install -d -m 0700 /etc/wireguard \
    && install -d -m 0755 /run/factortester-postgres

COPY deploy/docker/factortester-public/postgres-entrypoint.sh \
    /usr/local/bin/factortester-postgres-entrypoint
COPY deploy/docker/factortester-public/postgres-init-control.sh \
    /docker-entrypoint-initdb.d/20-factortester-control.sh
RUN chmod 0555 \
    /usr/local/bin/factortester-postgres-entrypoint \
    /docker-entrypoint-initdb.d/20-factortester-control.sh

ENTRYPOINT ["/usr/local/bin/factortester-postgres-entrypoint"]
CMD ["postgres"]
