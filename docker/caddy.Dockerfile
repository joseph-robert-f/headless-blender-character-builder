# syntax=docker/dockerfile:1.25@sha256:0adf442eae370b6087e08edc7c50b552d80ddf261576f4ebd6421006b2461f12
# check=skip=FromPlatformFlagConstDisallowed

# Rebuild the official v2.11.4 release artifact with fixed Go modules. The
# artifact contains Caddy's upstream main.go, go.mod and go.sum. Its vendored
# tree is deliberately not used: it contains the vulnerable release modules.
# This image is linux/amd64 only until another toolchain/archive is reviewed.
FROM --platform=linux/amd64 debian:bookworm-20260918-slim@sha256:3783cc01769c7b2b1b83a5c5ad96c815348e28ed7da68e2e3687004faa906251 AS caddy-build

ARG DEBIAN_SNAPSHOT=20260920T000000Z

RUN set -eux; \
    sed -i \
      -e "s|http://deb.debian.org/debian-security|http://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT}|g" \
      -e "s|http://deb.debian.org/debian|http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT}|g" \
      /etc/apt/sources.list.d/debian.sources; \
    printf '%s\n' 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99snapshot; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install --yes --no-install-recommends ca-certificates; \
    rm -rf /var/lib/apt/lists/*

ADD --checksum=sha256:d0f743b33e8d8945e6b1f432edd15785c70507121d6e2a723b21285eddf8b57b \
    https://go.dev/dl/go1.26.8.linux-amd64.tar.gz /tmp/go1.26.8.linux-amd64.tar.gz
ADD --checksum=sha256:33777097f666d60d78bfb74df06978c933f32aa5a0d4ce0b0c5d028489984187 \
    https://github.com/caddyserver/caddy/releases/download/v2.11.4/caddy_2.11.4_buildable-artifact.tar.gz \
    /tmp/caddy_2.11.4_buildable-artifact.tar.gz

ENV PATH="/usr/local/go/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
    GOTOOLCHAIN="local" \
    GOPROXY="https://proxy.golang.org" \
    GOSUMDB="sum.golang.org"

RUN set -eux; \
    tar -xzf /tmp/go1.26.8.linux-amd64.tar.gz -C /usr/local; \
    mkdir -p /src/caddy /out; \
    tar -xzf /tmp/caddy_2.11.4_buildable-artifact.tar.gz \
      -C /src/caddy --exclude='vendor'; \
    test -f /src/caddy/main.go; \
    test -f /src/caddy/go.mod; \
    test -f /src/caddy/go.sum; \
    test ! -e /src/caddy/vendor; \
    test "$(go version)" = 'go version go1.26.8 linux/amd64'; \
    cd /src/caddy; \
    go get \
      github.com/go-chi/chi/v5@v5.3.0 \
      github.com/google/cel-go@v0.30.0 \
      github.com/klauspost/compress@v1.19.1 \
      go.opentelemetry.io/otel@v1.45.0 \
      go.opentelemetry.io/otel/exporters/otlp/otlplog/otlploggrpc@v0.21.0 \
      go.opentelemetry.io/otel/exporters/otlp/otlplog/otlploghttp@v0.21.0 \
      go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetricgrpc@v1.45.0 \
      go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetrichttp@v1.45.0 \
      go.opentelemetry.io/otel/exporters/otlp/otlptrace@v1.45.0 \
      go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc@v1.45.0 \
      go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp@v1.45.0 \
      go.opentelemetry.io/otel/exporters/prometheus@v0.67.0 \
      go.opentelemetry.io/otel/exporters/stdout/stdoutlog@v0.21.0 \
      go.opentelemetry.io/otel/exporters/stdout/stdoutmetric@v1.45.0 \
      go.opentelemetry.io/otel/exporters/stdout/stdouttrace@v1.45.0 \
      go.opentelemetry.io/otel/sdk@v1.45.0 \
      golang.org/x/crypto@v0.56.0 \
      golang.org/x/net@v0.58.0 \
      golang.org/x/text@v0.41.0 \
      google.golang.org/grpc@v1.83.2; \
    go mod tidy; \
    go mod verify; \
    go mod vendor; \
    cel_matcher=vendor/github.com/caddyserver/caddy/v2/modules/caddyhttp/celmatcher.go; \
    test -f "$cel_matcher"; \
    test "$(grep -Fc '[]interpreter.Interpretable{reqAttr}' "$cel_matcher")" -eq 2; \
    sed -i 's/\[\]interpreter\.Interpretable{reqAttr}/[]interpreter.InterpretableV2{reqAttr}/g' "$cel_matcher"; \
    test "$(grep -Fc '[]interpreter.InterpretableV2{reqAttr}' "$cel_matcher")" -eq 2; \
    ! grep -Fq '[]interpreter.Interpretable{reqAttr}' "$cel_matcher"; \
    check_module() { test "$(go list -m -f '{{.Version}}' "$1")" = "$2"; }; \
    check_module github.com/caddyserver/caddy/v2 v2.11.4; \
    check_module github.com/go-chi/chi/v5 v5.3.0; \
    check_module github.com/google/cel-go v0.30.0; \
    check_module github.com/klauspost/compress v1.19.1; \
    check_module go.opentelemetry.io/otel v1.45.0; \
    check_module go.opentelemetry.io/otel/exporters/otlp/otlplog/otlploggrpc v0.21.0; \
    check_module go.opentelemetry.io/otel/exporters/otlp/otlplog/otlploghttp v0.21.0; \
    check_module go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetricgrpc v1.45.0; \
    check_module go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetrichttp v1.45.0; \
    check_module go.opentelemetry.io/otel/exporters/otlp/otlptrace v1.45.0; \
    check_module go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc v1.45.0; \
    check_module go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp v1.45.0; \
    check_module go.opentelemetry.io/otel/exporters/prometheus v0.67.0; \
    check_module go.opentelemetry.io/otel/exporters/stdout/stdoutlog v0.21.0; \
    check_module go.opentelemetry.io/otel/exporters/stdout/stdoutmetric v1.45.0; \
    check_module go.opentelemetry.io/otel/exporters/stdout/stdouttrace v1.45.0; \
    check_module go.opentelemetry.io/otel/sdk v1.45.0; \
    check_module golang.org/x/crypto v0.56.0; \
    check_module golang.org/x/net v0.58.0; \
    check_module golang.org/x/text v0.41.0; \
    check_module google.golang.org/grpc v1.83.2; \
    CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
      go build -mod=vendor -buildvcs=false -trimpath \
        -ldflags='-s -w -buildid=' -o /out/caddy .; \
    /out/caddy version | grep -F 'v2.11.4'; \
    go version -m /out/caddy | grep -F 'go1.26.8'; \
    cp go.mod /out/go.mod; \
    cp go.sum /out/go.sum; \
    cp LICENSE /out/LICENSE


# Keep the complete official runtime filesystem and image configuration:
# Caddyfile, welcome page, XDG paths, workdir, exposed TCP/UDP ports, default
# root user and CMD. The upstream image declares no ENTRYPOINT or VOLUME.
FROM --platform=linux/amd64 caddy:2.11.4-alpine@sha256:6aeddd44c3078b0f9a35206472a11420648a79c184603ef95957d0a20044cb2b AS caddy

LABEL org.opencontainers.image.title="Caddy v2.11.4 (HBCB patched build)" \
      org.opencontainers.image.source="https://github.com/caddyserver/caddy/releases/tag/v2.11.4" \
      org.opencontainers.image.revision="sha256:33777097f666d60d78bfb74df06978c933f32aa5a0d4ce0b0c5d028489984187" \
      org.opencontainers.image.version="v2.11.4-hbcb.1" \
      org.opencontainers.image.base.name="caddy:2.11.4-alpine" \
      org.opencontainers.image.base.digest="sha256:6aeddd44c3078b0f9a35206472a11420648a79c184603ef95957d0a20044cb2b" \
      io.hbcb.caddy.source-archive.sha256="33777097f666d60d78bfb74df06978c933f32aa5a0d4ce0b0c5d028489984187" \
      io.hbcb.caddy.patch="cel-newcall-interpretable-v2" \
      io.hbcb.caddy.go-version="1.26.8" \
      io.hbcb.scope="local-development-only"

COPY --from=caddy-build /out/caddy /usr/bin/caddy
COPY --from=caddy-build /out/go.mod /usr/share/licenses/caddy/go.mod
COPY --from=caddy-build /out/go.sum /usr/share/licenses/caddy/go.sum
COPY --from=caddy-build /out/LICENSE /usr/share/licenses/caddy/LICENSE

# COPY replaces the binary inode, so restore the official port-binding
# capability after the copy. No USER, EXPOSE, VOLUME, ENTRYPOINT or CMD is
# overridden in this derived image.
RUN set -eux; \
    chmod 0755 /usr/bin/caddy; \
    setcap cap_net_bind_service=+ep /usr/bin/caddy; \
    getcap /usr/bin/caddy | grep -F 'cap_net_bind_service=ep'; \
    caddy version | grep -F 'v2.11.4'
