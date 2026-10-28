# Persistent Py3.14/Rust builder for vendor/nautilus_trader.
# The wheel still builds from the local submodule; this image only removes
# repeated apt/rustup/maturin downloads from every release.
FROM python:3.14-slim
ARG RUSTUP_DIST_SERVER=https://rsproxy.cn
ARG RUSTUP_UPDATE_ROOT=https://rsproxy.cn/rustup
ENV RUSTUP_DIST_SERVER=$RUSTUP_DIST_SERVER \
    RUSTUP_UPDATE_ROOT=$RUSTUP_UPDATE_ROOT \
    CARGO_HOME=/root/.cargo \
    RUSTUP_HOME=/root/.rustup
RUN sed -i s/deb.debian.org/mirrors.aliyun.com/g /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential curl pkg-config libssl-dev patchelf cmake clang \
    && rm -rf /var/lib/apt/lists/* \
    && curl --proto '=https' --tlsv1.2 -sSf https://rsproxy.cn/rustup-init.sh \
        | sh -s -- -y --default-toolchain 1.99.0 --profile minimal \
    && python -m pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple maturin==1.15.0 \
    && mkdir -p /root/.cargo \
    && printf '[source.crates-io]\nreplace-with = "rsproxy-sparse"\n[source.rsproxy-sparse]\nregistry = "sparse+https://rsproxy.cn/index/"\n' > /root/.cargo/config.toml
WORKDIR /src
