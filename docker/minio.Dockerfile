# syntax=docker/dockerfile:1.25@sha256:0adf442eae370b6087e08edc7c50b552d80ddf261576f4ebd6421006b2461f12

# MinIO Community stopped publishing maintained binaries/images.  Build the
# final upstream source revisions from checksum-pinned archives.  The build
# also advances the security-sensitive Go modules to the reviewed 2026 fixes.
# Checked-in go.mod/go.sum overlays make that transformation reviewable, and
# read-only module builds fail closed if Go's selection changes.  This remains
# a local compatibility fixture, not a production storage recommendation.
FROM --platform=linux/amd64 debian:bookworm-20260803-slim@sha256:abd67ffcfa541b485a3dff59865ab629aa048a6c613e639d36e7456b0b229241 AS minio-build

ARG DEBIAN_SNAPSHOT=20260804T000000Z
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

ADD --checksum=sha256:234828b7a89e0e303d2556310ee549fbcf253d28de937bac3da13d6294262ac1 \
    https://go.dev/dl/go1.25.12.linux-amd64.tar.gz /tmp/go1.25.12.linux-amd64.tar.gz
ADD --checksum=sha256:71794c2df26aad0cc99e8421c58b7aa2dd55969f979b0e7d1e931042e9fabcd6 \
    https://github.com/minio/minio/archive/7aac2a2c5b7c882e68c1ce017d8256be2feea27f.tar.gz \
    /tmp/minio.7aac2a2c5b7c882e68c1ce017d8256be2feea27f.tar.gz
ADD --checksum=sha256:167415edd21bc29f5360943dac64272aa5cda0a39f3070b15cfeca671c43d975 \
    https://github.com/minio/mc/archive/77f82e18b5401a65958f1619df6ebb994634bd88.tar.gz \
    /tmp/mc.77f82e18b5401a65958f1619df6ebb994634bd88.tar.gz

COPY docker/minio-modules/minio.go.mod /tmp/minio.go.mod
COPY docker/minio-modules/minio.go.sum /tmp/minio.go.sum
COPY docker/minio-modules/mc.go.mod /tmp/mc.go.mod
COPY docker/minio-modules/mc.go.sum /tmp/mc.go.sum

RUN set -eux; \
    tar -xzf /tmp/go1.25.12.linux-amd64.tar.gz -C /usr/local; \
    mkdir -p /src/minio /src/mc /out; \
    tar -xzf /tmp/minio.7aac2a2c5b7c882e68c1ce017d8256be2feea27f.tar.gz \
      -C /src/minio --strip-components=1; \
    tar -xzf /tmp/mc.77f82e18b5401a65958f1619df6ebb994634bd88.tar.gz \
      -C /src/mc --strip-components=1; \
    install -m 0444 /tmp/minio.go.mod /src/minio/go.mod; \
    install -m 0444 /tmp/minio.go.sum /src/minio/go.sum; \
    install -m 0444 /tmp/mc.go.mod /src/mc/go.mod; \
    install -m 0444 /tmp/mc.go.sum /src/mc/go.sum; \
    cd /src/minio; \
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
        -ldflags '-s -w -X github.com/minio/minio/cmd.Version=2026-02-12T20:18:48Z -X github.com/minio/minio/cmd.CopyrightYear=2026 -X github.com/minio/minio/cmd.ReleaseTag=DEVELOPMENT.GOGET -X github.com/minio/minio/cmd.CommitID=7aac2a2c5b7c882e68c1ce017d8256be2feea27f -X github.com/minio/minio/cmd.ShortCommitID=7aac2a2c5b7c -X github.com/minio/minio/cmd.GOPATH=/go -X github.com/minio/minio/cmd.GOROOT=/usr/local/go' \
        -o /out/minio .; \
    /out/minio --version | grep -F 'commit-id=7aac2a2c5b7c882e68c1ce017d8256be2feea27f'; \
    cd /src/mc; \
    PATH=/usr/local/go/bin:/usr/bin:/bin \
      GOTOOLCHAIN=local \
      CGO_ENABLED=0 \
      GOOS=linux \
      GOARCH=amd64 \
      go build \
        -mod=readonly \
        -buildvcs=false \
        -trimpath \
        -ldflags '-s -w -X github.com/minio/mc/cmd.Version=2025-11-06T16:25:29Z -X github.com/minio/mc/cmd.ReleaseTag=DEVELOPMENT.GOGET -X github.com/minio/mc/cmd.CommitID=77f82e18b5401a65958f1619df6ebb994634bd88 -X github.com/minio/mc/cmd.ShortCommitID=77f82e18b540' \
        -o /out/mc .; \
    /out/mc --version | grep -F 'commit-id=77f82e18b5401a65958f1619df6ebb994634bd88'; \
    cp /src/minio/LICENSE /out/MINIO-LICENSE; \
    cp /src/minio/CREDITS /out/MINIO-CREDITS; \
    cp /src/mc/LICENSE /out/MC-LICENSE; \
    cp /src/mc/CREDITS /out/MC-CREDITS


FROM --platform=linux/amd64 alpine:3.22.5@sha256:14358309a308569c32bdc37e2e0e9694be33a9d99e68afb0f5ff33cc1f695dce AS minio

ARG HBCB_MINIO_RECIPE_ID=unmeasured

LABEL org.opencontainers.image.title="MinIO local compatibility fixture" \
      org.opencontainers.image.source="https://github.com/minio/minio/tree/7aac2a2c5b7c882e68c1ce017d8256be2feea27f" \
      org.opencontainers.image.revision="7aac2a2c5b7c882e68c1ce017d8256be2feea27f" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later" \
      org.opencontainers.image.version="final-community-20260212-hbcb.1" \
      org.opencontainers.image.base.name="alpine:3.22.5" \
      org.opencontainers.image.base.digest="sha256:14358309a308569c32bdc37e2e0e9694be33a9d99e68afb0f5ff33cc1f695dce" \
      io.hbcb.mc-revision="77f82e18b5401a65958f1619df6ebb994634bd88" \
      io.hbcb.security-modules="2026-08-12" \
      io.hbcb.recipe-id="${HBCB_MINIO_RECIPE_ID}" \
      io.hbcb.scope="local-development-only"

RUN set -eux; \
    test -s /etc/ssl/certs/ca-certificates.crt; \
    mkdir -p /data /work/home /licenses/minio; \
    chown -R 65532:65532 /data /work; \
    chmod 0700 /data /work/home

COPY --from=minio-build /out/minio /usr/local/bin/minio
COPY --from=minio-build /out/mc /usr/local/bin/mc
COPY --from=minio-build /out/MINIO-LICENSE /licenses/minio/LICENSE
COPY --from=minio-build /out/MINIO-CREDITS /licenses/minio/CREDITS
COPY --from=minio-build /out/MC-LICENSE /licenses/minio/MC-LICENSE
COPY --from=minio-build /out/MC-CREDITS /licenses/minio/MC-CREDITS

RUN set -eux; \
    chmod 0555 /usr/local/bin/minio /usr/local/bin/mc; \
    chmod -R a-w /licenses/minio; \
    /usr/local/bin/minio --version | grep -F 'commit-id=7aac2a2c5b7c882e68c1ce017d8256be2feea27f'; \
    /usr/local/bin/mc --version | grep -F 'commit-id=77f82e18b5401a65958f1619df6ebb994634bd88'

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
