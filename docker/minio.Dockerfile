# syntax=docker/dockerfile:1

# MinIO Community stopped publishing maintained binaries/images.  Build the
# final upstream security release from its checksum-pinned source archive so
# the zero-account local stack does not fall back to the vulnerable September
# 2025 registry image.  This is a local compatibility fixture, not a production
# storage recommendation.
FROM --platform=linux/amd64 debian:bookworm-20260713-slim@sha256:7b140f374b289a7c2befc338f42ebe6441b7ea838a042bbd5acbfca6ec875818 AS minio-build

ARG DEBIAN_SNAPSHOT=20260714T000000Z
ARG HBCB_MINIO_RECIPE_ID=unmeasured

RUN set -eux; \
    sed -i \
      -e "s|http://deb.debian.org/debian-security|http://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT}|g" \
      -e "s|http://deb.debian.org/debian|http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT}|g" \
      /etc/apt/sources.list.d/debian.sources; \
    printf '%s\n' 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99snapshot; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install --yes --no-install-recommends ca-certificates; \
    rm -rf /var/lib/apt/lists/*

ADD --checksum=sha256:6842c516ca66c89d648a7f1dbe28e28c47b61b59f8f06633eb2ceb1188e9251d \
    https://go.dev/dl/go1.24.8.linux-amd64.tar.gz /tmp/go1.24.8.linux-amd64.tar.gz
ADD --checksum=sha256:be6d0bd3696c3a13a35f02d3a0280b64319c67918b4501c5c3d87f96d000085c \
    https://github.com/minio/minio/archive/refs/tags/RELEASE.2025-10-15T17-29-55Z.tar.gz \
    /tmp/minio.RELEASE.2025-10-15T17-29-55Z.tar.gz

RUN set -eux; \
    tar -xzf /tmp/go1.24.8.linux-amd64.tar.gz -C /usr/local; \
    mkdir -p /src /out; \
    tar -xzf /tmp/minio.RELEASE.2025-10-15T17-29-55Z.tar.gz \
      -C /src --strip-components=1; \
    cd /src; \
    PATH=/usr/local/go/bin:/usr/bin:/bin \
      GOTOOLCHAIN=local \
      CGO_ENABLED=0 \
      GOOS=linux \
      GOARCH=amd64 \
      go build \
        -mod=readonly \
        -buildvcs=false \
        -trimpath \
        -tags kqueue \
        -ldflags '-s -w -X github.com/minio/minio/cmd.Version=2025-10-15T17:29:55Z -X github.com/minio/minio/cmd.CopyrightYear=2025 -X github.com/minio/minio/cmd.ReleaseTag=RELEASE.2025-10-15T17-29-55Z -X github.com/minio/minio/cmd.CommitID=9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a -X github.com/minio/minio/cmd.ShortCommitID=9e49d5e7a648 -X github.com/minio/minio/cmd.GOPATH=/go -X github.com/minio/minio/cmd.GOROOT=/usr/local/go' \
        -o /out/minio .; \
    /out/minio --version | grep -F 'RELEASE.2025-10-15T17-29-55Z'; \
    cp /src/LICENSE /out/MINIO-LICENSE; \
    cp /src/CREDITS /out/MINIO-CREDITS


FROM --platform=linux/amd64 debian:bookworm-20260713-slim@sha256:7b140f374b289a7c2befc338f42ebe6441b7ea838a042bbd5acbfca6ec875818 AS minio

ARG DEBIAN_SNAPSHOT=20260714T000000Z
ARG HBCB_MINIO_RECIPE_ID=unmeasured

LABEL org.opencontainers.image.title="MinIO local compatibility fixture" \
      org.opencontainers.image.source="https://github.com/minio/minio/tree/RELEASE.2025-10-15T17-29-55Z" \
      org.opencontainers.image.revision="9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later" \
      org.opencontainers.image.version="RELEASE.2025-10-15T17-29-55Z" \
      io.hbcb.recipe-id="${HBCB_MINIO_RECIPE_ID}" \
      io.hbcb.scope="local-development-only"

RUN set -eux; \
    sed -i \
      -e "s|http://deb.debian.org/debian-security|http://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT}|g" \
      -e "s|http://deb.debian.org/debian|http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT}|g" \
      /etc/apt/sources.list.d/debian.sources; \
    printf '%s\n' 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99snapshot; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install --yes --no-install-recommends ca-certificates; \
    rm -rf /var/lib/apt/lists/*; \
    mkdir -p /data /work/home /licenses/minio; \
    chown -R 65532:65532 /data /work; \
    chmod 0700 /data /work/home

COPY --from=minio-build /out/minio /usr/local/bin/minio
COPY --from=minio-build /out/MINIO-LICENSE /licenses/minio/LICENSE
COPY --from=minio-build /out/MINIO-CREDITS /licenses/minio/CREDITS
ADD --checksum=sha256:01f866e9c5f9b87c2b09116fa5d7c06695b106242d829a8bb32990c00312e891 \
    https://dl.min.io/client/mc/release/linux-amd64/archive/mc.RELEASE.2025-08-13T08-35-41Z \
    /usr/local/bin/mc

RUN set -eux; \
    chmod 0555 /usr/local/bin/minio /usr/local/bin/mc; \
    chmod -R a-w /licenses/minio; \
    /usr/local/bin/minio --version | grep -F 'RELEASE.2025-10-15T17-29-55Z'; \
    /usr/local/bin/mc --version | grep -F 'RELEASE.2025-08-13T08-35-41Z'

ENV HOME="/work/home" \
    MC_CONFIG_DIR="/tmp/mc" \
    MINIO_BROWSER="off" \
    MINIO_UPDATE="off"

VOLUME ["/data"]
EXPOSE 9000
USER 65532:65532
STOPSIGNAL SIGTERM
ENTRYPOINT ["/usr/local/bin/minio"]
CMD ["server", "/data", "--address", ":9000"]
