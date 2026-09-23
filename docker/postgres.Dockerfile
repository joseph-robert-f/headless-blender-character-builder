# syntax=docker/dockerfile:1.25@sha256:0adf442eae370b6087e08edc7c50b552d80ddf261576f4ebd6421006b2461f12

# Keep the reviewed official PostgreSQL filesystem and entrypoint, but remove
# gosu before copying the filesystem into a clean image configuration.  The
# scratch final stage is intentional: it prevents the inherited GOSU_VERSION
# environment entry from advertising a binary that is no longer present.
FROM --platform=linux/amd64 postgres:16.15-alpine3.24@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea AS postgres-sanitized

RUN set -eux; \
    rm -f /usr/local/bin/gosu; \
    test ! -e /usr/local/bin/gosu; \
    test ! -L /usr/local/bin/gosu; \
    test "$(sha256sum /usr/local/bin/docker-entrypoint.sh | awk '{print $1}')" = \
      9c440299ae04a0a79d55b8bf03307036d890a40979d2fb698073c9050d4b20a5


FROM scratch AS postgres

LABEL org.opencontainers.image.title="PostgreSQL local service runtime (gosu-free)" \
      org.opencontainers.image.source="https://github.com/docker-library/postgres/tree/9d15534160ade17f2b6c455a39ee967c49b1937d/16/alpine3.24" \
      org.opencontainers.image.licenses="PostgreSQL" \
      org.opencontainers.image.version="16.15-alpine3.24-hbcb.1" \
      org.opencontainers.image.revision="9d15534160ade17f2b6c455a39ee967c49b1937d" \
      org.opencontainers.image.base.name="postgres:16.15-alpine3.24" \
      org.opencontainers.image.base.digest="sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea" \
      io.hbcb.postgres.recipe-id="postgres-16.15-alpine3.24-gosu-free-v1" \
      io.hbcb.scope="local-service-and-digest-locked-vps"

COPY --from=postgres-sanitized / /

RUN set -eux; \
    test ! -e /usr/local/bin/gosu; \
    test ! -L /usr/local/bin/gosu; \
    test "$(sha256sum /usr/local/bin/docker-entrypoint.sh | awk '{print $1}')" = \
      9c440299ae04a0a79d55b8bf03307036d890a40979d2fb698073c9050d4b20a5

ENV PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
    LANG="en_US.utf8" \
    PG_MAJOR="16" \
    PG_VERSION="16.15" \
    PG_SHA256="c1575341fa7bd40f5274ea465b34390f4dc64cdd0770af327005caaeb9f6b7ed" \
    PGDATA="/var/lib/postgresql/data"

# Real-tab legacy ENV form copied verbatim from upstream
# docker-library/postgres@9d15534160ade17f2b6c455a39ee967c49b1937d
# 16/alpine3.24/Dockerfile so the derived image env matches the
# reviewed base contract byte-for-byte (double-quoted ENV values do
# not interpret \t escapes).
ENV DOCKER_PG_LLVM_DEPS \
		llvm21-dev \
		clang21

WORKDIR /
VOLUME ["/var/lib/postgresql/data"]
EXPOSE 5432
USER 70:70
STOPSIGNAL SIGINT
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["postgres"]
