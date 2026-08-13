FROM alpine:3.22@sha256:14358309a308569c32bdc37e2e0e9694be33a9d99e68afb0f5ff33cc1f695dce

RUN apk add --no-cache \
        iproute2 \
        iptables \
        wireguard-tools

COPY deploy/docker/factortester-server/wireguard-entrypoint.sh \
    /usr/local/bin/wireguard-entrypoint
COPY deploy/docker/factortester-server/wireguard-healthcheck.sh \
    /usr/local/bin/wireguard-healthcheck
RUN chmod 0755 \
    /usr/local/bin/wireguard-entrypoint \
    /usr/local/bin/wireguard-healthcheck

ENTRYPOINT ["/usr/local/bin/wireguard-entrypoint"]
