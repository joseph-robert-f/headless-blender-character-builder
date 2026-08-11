# syntax=docker/dockerfile:1.25@sha256:0adf442eae370b6087e08edc7c50b552d80ddf261576f4ebd6421006b2461f12

ARG HBCB_BUILDER_IMAGE=headless-blender-character-builder:dev

# Install the service wheel set with Blender's CPython 3.11 so the worker can
# remain a strict child of the already-gated G4 builder image.  Nothing in this
# stage writes to /opt/builder/source or its baked provenance.
FROM --platform=linux/amd64 ${HBCB_BUILDER_IMAGE} AS service-dependencies

USER 0:0
COPY docker/service-requirements.lock /opt/hbcb/service-requirements.lock
RUN set -eux; \
    /opt/blender/4.5/python/bin/python3.11 -m pip install \
      --disable-pip-version-check \
      --no-cache-dir \
      --only-binary=:all: \
      --require-hashes \
      --requirement /opt/hbcb/service-requirements.lock \
      --target /opt/hbcb/site-packages; \
    find /opt/hbcb/site-packages -type d -name __pycache__ -prune -exec rm -rf '{}' +; \
    chmod -R a+rX,a-w /opt/hbcb/site-packages /opt/hbcb/service-requirements.lock


# The supervisor adds orchestration only.  The inherited builder executable,
# Blender tree, generator, exporters, QA, manifests, and provenance stay byte
# for byte unchanged; tests compare them with the G4 parent before acceptance.
# Keep this target before the control-plane stages so classic Docker builders
# do not install the API operating-system layer while building the worker.
FROM --platform=linux/amd64 ${HBCB_BUILDER_IMAGE} AS worker

LABEL org.opencontainers.image.title="Headless Blender Character Builder supervisor" \
      org.opencontainers.image.source="https://github.com/joseph-robert-f/headless-blender-character-builder" \
      org.opencontainers.image.licenses="GPL-3.0-or-later" \
      org.opencontainers.image.version="0.1.0" \
      io.hbcb.builder.contract="complete-v1"

USER 0:0
COPY --from=service-dependencies /opt/hbcb/site-packages /opt/hbcb/site-packages
COPY service/src /opt/hbcb/service/src
COPY THIRD_PARTY_NOTICES.md /usr/share/licenses/headless-blender-character-builder/THIRD_PARTY_NOTICES.md
COPY release/license-policy.json /opt/hbcb/provenance/license-policy.json
COPY release/service-dependency-licenses.json /opt/hbcb/provenance/service-dependency-licenses.json
RUN set -eux; \
    chmod -R a+rX,a-w \
      /opt/hbcb/site-packages \
      /opt/hbcb/service \
      /opt/hbcb/provenance \
      /usr/share/licenses/headless-blender-character-builder; \
    test -x /usr/local/bin/builder; \
    test -f /opt/builder/provenance/source-tree.sha256

ENV PYTHONPATH="/opt/hbcb/site-packages:/opt/hbcb/service/src:/opt/builder/source" \
    PYTHONDONTWRITEBYTECODE="1" \
    HOME="/work" \
    TMPDIR="/work"

USER 65532:65532
ENTRYPOINT ["/opt/blender/4.5/python/bin/python3.11", "-m", "hbcb_service.worker_main"]


# The HTTP/control-plane image deliberately contains no Blender executable.
# Debian resolution is frozen to the same immutable snapshot as the G4 image.
FROM --platform=linux/amd64 debian:bookworm-20260713-slim@sha256:63a496b5d3b99214b39f5ed70eb71a61e590a77979c79cbee4faf991f8c0783e AS service-base

ARG DEBIAN_SNAPSHOT=20260714T000000Z

LABEL org.opencontainers.image.title="Headless Blender Character Builder service" \
      org.opencontainers.image.source="https://github.com/joseph-robert-f/headless-blender-character-builder" \
      org.opencontainers.image.licenses="GPL-3.0-or-later" \
      org.opencontainers.image.version="0.1.0"

RUN set -eux; \
    sed -i \
      -e "s|http://deb.debian.org/debian-security|http://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT}|g" \
      -e "s|http://deb.debian.org/debian|http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT}|g" \
      /etc/apt/sources.list.d/debian.sources; \
    printf '%s\n' 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99snapshot; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install --yes --no-install-recommends \
      ca-certificates \
      libstdc++6 \
      python3; \
    rm -rf /var/lib/apt/lists/*; \
    mkdir -p /opt/hbcb/source /work; \
    chown -R 65532:65532 /work; \
    chmod 0555 /opt/hbcb/source; \
    chmod 0700 /work

COPY --from=service-dependencies /opt/hbcb/site-packages /opt/hbcb/site-packages
COPY LICENSE /usr/share/licenses/headless-blender-character-builder/LICENSE
COPY THIRD_PARTY_NOTICES.md /usr/share/licenses/headless-blender-character-builder/THIRD_PARTY_NOTICES.md
COPY release/license-policy.json /opt/hbcb/provenance/license-policy.json
COPY release/service-dependency-licenses.json /opt/hbcb/provenance/service-dependency-licenses.json
COPY shared /opt/hbcb/source/shared
COPY service/src /opt/hbcb/source/service/src

RUN set -eux; \
    chmod -R a+rX,a-w \
      /opt/hbcb/site-packages \
      /opt/hbcb/provenance \
      /opt/hbcb/source \
      /usr/share/licenses/headless-blender-character-builder; \
    test ! -e /opt/blender; \
    test ! -e /usr/local/bin/builder

ENV PATH="/usr/bin:/bin" \
    PYTHONPATH="/opt/hbcb/site-packages:/opt/hbcb/source/service/src:/opt/hbcb/source" \
    PYTHONDONTWRITEBYTECODE="1" \
    HOME="/work" \
    TMPDIR="/work"

WORKDIR /opt/hbcb/source
USER 65532:65532
STOPSIGNAL SIGTERM


FROM service-base AS api
ENTRYPOINT ["/usr/bin/python3", "-m", "hbcb_service.api_main"]


FROM service-dependencies AS service-test-dependencies
USER 0:0
COPY docker/service-test-requirements.lock /opt/hbcb/service-test-requirements.lock
RUN set -eux; \
    /opt/blender/4.5/python/bin/python3.11 -m pip install \
      --disable-pip-version-check \
      --no-cache-dir \
      --no-deps \
      --only-binary=:all: \
      --require-hashes \
      --requirement /opt/hbcb/service-test-requirements.lock \
      --target /opt/hbcb/test-site-packages; \
    find /opt/hbcb/test-site-packages -type d -name __pycache__ -prune -exec rm -rf '{}' +; \
    chmod -R a+rX,a-w \
      /opt/hbcb/test-site-packages \
      /opt/hbcb/service-test-requirements.lock


FROM service-base AS service-test
USER 0:0
COPY --from=service-test-dependencies /opt/hbcb/test-site-packages /opt/hbcb/site-packages
COPY .env.example /opt/hbcb/source/.env.example
COPY examples /opt/hbcb/source/examples
COPY scripts /opt/hbcb/source/scripts
COPY tests /opt/hbcb/source/tests
RUN set -eux; \
    chmod -R a+rX,a-w \
      /opt/hbcb/site-packages \
      /opt/hbcb/source/.env.example \
      /opt/hbcb/source/examples \
      /opt/hbcb/source/scripts \
      /opt/hbcb/source/tests; \
    test -x /opt/hbcb/source/scripts/init-env
USER 65532:65532
ENTRYPOINT ["/usr/bin/python3"]
