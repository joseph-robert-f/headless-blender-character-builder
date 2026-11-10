# syntax=docker/dockerfile:1.25@sha256:0adf442eae370b6087e08edc7c50b552d80ddf261576f4ebd6421006b2461f12
# check=skip=FromPlatformFlagConstDisallowed

# Rebuild the official v2.11.9 release artifact with its reviewed Go modules.
# The artifact contains the generated main module, go.mod and go.sum.
# Its go.mod requires Go 1.27.3. Verify and vendor its module graph again
# before compiling with that pinned toolchain and GOTOOLCHAIN=local.
# This image is linux/amd64 only until another toolchain/archive is reviewed.
FROM --platform=linux/amd64 debian:bookworm-20261027-slim@sha256:99c0b25c46d0214d5a2091092e7908907dcaecd6a962cde0ac700acee222b6f3 AS caddy-build

ARG DEBIAN_SNAPSHOT=20261029T000000Z

RUN set -eux; \
    sed -i \
      -e "s|http://deb.debian.org/debian-security|http://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT}|g" \
      -e "s|http://deb.debian.org/debian|http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT}|g" \
      /etc/apt/sources.list.d/debian.sources; \
    printf '%s\n' 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99snapshot; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install --yes --no-install-recommends ca-certificates; \
    rm -rf /var/lib/apt/lists/*

ADD --checksum=sha256:65efbc80fdc1fa2cd2631cad5b481777a68e8725f34e89f50fc6ac714e379b40 \
    https://go.dev/dl/go1.27.3.linux-amd64.tar.gz /tmp/go1.27.3.linux-amd64.tar.gz
ADD --checksum=sha256:07fe00aefec10b60d33e26bddf73d522fdd6d7d48dd0bf125fbce3238ec867e7 \
    https://github.com/caddyserver/caddy/releases/download/v2.11.9/caddy_2.11.9_buildable-artifact.tar.gz \
    /tmp/caddy_2.11.9_buildable-artifact.tar.gz

ENV PATH="/usr/local/go/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
    GOTOOLCHAIN="local" \
    GOPROXY="https://proxy.golang.org" \
    GOSUMDB="sum.golang.org"

RUN set -eux; \
    tar -xzf /tmp/go1.27.3.linux-amd64.tar.gz -C /usr/local; \
    mkdir -p /src/caddy /out; \
    tar -xzf /tmp/caddy_2.11.9_buildable-artifact.tar.gz \
      -C /src/caddy --exclude='vendor'; \
    test -f /src/caddy/main.go; \
    test -f /src/caddy/go.mod; \
    test -f /src/caddy/go.sum; \
    test ! -e /src/caddy/vendor; \
    test "$(go version)" = 'go version go1.27.3 linux/amd64'; \
    cd /src/caddy; \
    go mod tidy; \
    go mod verify; \
    go mod vendor; \
    cel_matcher=vendor/github.com/caddyserver/caddy/v2/modules/caddyhttp/celmatcher.go; \
    test -f "$cel_matcher"; \
    grep -Fq '"cel.dev/cel-go/interpreter"' "$cel_matcher"; \
    test "$(grep -Fc 'github.com/google/cel-go' "$cel_matcher")" -eq 0; \
    test "$(grep -Fc '[]interpreter.InterpretableV2{reqAttr}' "$cel_matcher")" -eq 2; \
    test "$(grep -Fc '[]interpreter.Interpretable{reqAttr}' "$cel_matcher")" -eq 0; \
    check_module() { test "$(go list -m -f '{{.Version}}' "$1")" = "$2"; }; \
    check_module github.com/caddyserver/caddy/v2 v2.11.9; \
    check_module github.com/go-chi/chi/v5 v5.4.0; \
    check_module cel.dev/cel-go v0.32.0; \
    check_module github.com/klauspost/compress v1.20.1; \
    check_module go.opentelemetry.io/otel v1.46.0; \
    check_module go.opentelemetry.io/otel/exporters/otlp/otlplog/otlploggrpc v0.22.0; \
    check_module go.opentelemetry.io/otel/exporters/otlp/otlplog/otlploghttp v0.22.0; \
    check_module go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetricgrpc v1.46.0; \
    check_module go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetrichttp v1.46.0; \
    check_module go.opentelemetry.io/otel/exporters/otlp/otlptrace v1.46.0; \
    check_module go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc v1.46.0; \
    check_module go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp v1.46.0; \
    check_module go.opentelemetry.io/otel/exporters/prometheus v0.68.0; \
    check_module go.opentelemetry.io/otel/exporters/stdout/stdoutlog v0.22.0; \
    check_module go.opentelemetry.io/otel/exporters/stdout/stdoutmetric v1.46.0; \
    check_module go.opentelemetry.io/otel/exporters/stdout/stdouttrace v1.46.0; \
    check_module go.opentelemetry.io/otel/sdk v1.46.0; \
    check_module golang.org/x/crypto v0.57.0; \
    check_module golang.org/x/net v0.60.0; \
    check_module golang.org/x/text v0.42.0; \
    check_module google.golang.org/grpc v1.83.2; \
    CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
      go build -mod=vendor -buildvcs=false -trimpath \
        -ldflags='-s -w -buildid=' -o /out/caddy .; \
    /out/caddy version | grep -F 'v2.11.9'; \
    go version -m /out/caddy | grep -F 'go1.27.3'; \
    sha256sum /out/caddy | sed 's|  /out/caddy$|  /usr/bin/caddy|' > /out/caddy.sha256; \
    cp go.mod /out/go.mod; \
    cp go.sum /out/go.sum; \
    cp LICENSE /out/LICENSE; \
    cp /usr/local/go/LICENSE /out/GO-LICENSE


# Keep the complete official runtime filesystem and image configuration:
# Caddyfile, welcome page, XDG paths, workdir, exposed TCP/UDP ports, default
# root user and CMD. The upstream image declares no ENTRYPOINT or VOLUME.
FROM --platform=linux/amd64 caddy:2.11.9-alpine@sha256:0bbb055bda6793c999bde78b1b5ce3e89f829fb031af2cf50056ea1246559fee AS caddy

LABEL org.opencontainers.image.title="Caddy v2.11.9 (HBCB source build)" \
      org.opencontainers.image.source="https://github.com/caddyserver/caddy/releases/tag/v2.11.9" \
      org.opencontainers.image.revision="sha256:07fe00aefec10b60d33e26bddf73d522fdd6d7d48dd0bf125fbce3238ec867e7" \
      org.opencontainers.image.version="v2.11.9-hbcb.1" \
      org.opencontainers.image.base.name="caddy:2.11.9-alpine" \
      org.opencontainers.image.base.digest="sha256:0bbb055bda6793c999bde78b1b5ce3e89f829fb031af2cf50056ea1246559fee" \
      io.hbcb.caddy.source-archive.sha256="07fe00aefec10b60d33e26bddf73d522fdd6d7d48dd0bf125fbce3238ec867e7" \
      io.hbcb.caddy.cel-compatibility="upstream-interpretable-v2" \
      io.hbcb.caddy.go-version="1.27.3" \
      io.hbcb.scope="local-development-only"

COPY --from=caddy-build /out/caddy /usr/bin/caddy
COPY --from=caddy-build /out/caddy.sha256 /usr/share/licenses/caddy/caddy.sha256
COPY --from=caddy-build /out/go.mod /usr/share/licenses/caddy/go.mod
COPY --from=caddy-build /out/go.sum /usr/share/licenses/caddy/go.sum
COPY --from=caddy-build /out/LICENSE /usr/share/licenses/caddy/LICENSE
COPY --from=caddy-build /out/GO-LICENSE /usr/share/licenses/caddy/GO-LICENSE

# COPY replaces the binary inode. Retain the project's existing effective
# cap_net_bind_service=ep control; the new official base uses permitted-only
# =p. No USER, EXPOSE, VOLUME, ENTRYPOINT or CMD is overridden here.
RUN set -eux; \
    chmod 0755 /usr/bin/caddy; \
    setcap cap_net_bind_service=+ep /usr/bin/caddy; \
    getcap /usr/bin/caddy | grep -F 'cap_net_bind_service=ep'; \
    sha256sum -c /usr/share/licenses/caddy/caddy.sha256; \
    caddy version | grep -F 'v2.11.9'
