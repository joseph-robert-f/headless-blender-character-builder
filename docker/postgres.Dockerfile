# syntax=docker/dockerfile:1.25@sha256:0adf442eae370b6087e08edc7c50b552d80ddf261576f4ebd6421006b2461f12

# Keep the reviewed official PostgreSQL filesystem and entrypoint, but remove
# gosu before copying the filesystem into a clean image configuration.  The
# scratch final stage is intentional: it prevents the inherited GOSU_VERSION
# environment entry from advertising a binary that is no longer present.
FROM --platform=linux/amd64 postgres:16.14-alpine3.24@sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777 AS postgres-sanitized

RUN set -eux; \
    rm -f /usr/local/bin/gosu; \
    test ! -e /usr/local/bin/gosu; \
    test ! -L /usr/local/bin/gosu; \
    test "$(sha256sum /usr/local/bin/docker-entrypoint.sh | awk '{print $1}')" = \
      9c440299ae04a0a79d55b8bf03307036d890a40979d2fb698073c9050d4b20a5


FROM scratch AS postgres

LABEL org.opencontainers.image.title="PostgreSQL local service runtime (gosu-free)" \
      org.opencontainers.image.source="https://github.com/docker-library/postgres/tree/4f9ced003ba58a854656ba150d146243d27ae3ac/16/alpine3.24" \
      org.opencontainers.image.licenses="PostgreSQL" \
      org.opencontainers.image.version="16.14-alpine3.24-hbcb.1" \
      org.opencontainers.image.revision="4f9ced003ba58a854656ba150d146243d27ae3ac" \
      org.opencontainers.image.base.name="postgres:16.14-alpine3.24" \
      org.opencontainers.image.base.digest="sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777" \
      io.hbcb.postgres.recipe-id="postgres-16.14-alpine3.24-gosu-free-v1" \
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
    PG_VERSION="16.14" \
    PG_SHA256="f6d077142737920858ce958ccdb75c6ee137a63b5b0853c70693d401ac7e3471" \
    DOCKER_PG_LLVM_DEPS="llvm21-dev \t\tclang21" \
    PGDATA="/var/lib/postgresql/data"

WORKDIR /
VOLUME ["/var/lib/postgresql/data"]
EXPOSE 5432
USER 70:70
STOPSIGNAL SIGINT
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["postgres"]
