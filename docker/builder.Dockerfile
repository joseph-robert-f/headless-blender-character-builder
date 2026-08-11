# The release target is deliberately single-platform until an official,
# checksum-pinned Blender arm64 Linux distribution is validated.
FROM --platform=linux/amd64 debian:bookworm-20260803-slim@sha256:abd67ffcfa541b485a3dff59865ab629aa048a6c613e639d36e7456b0b229241 AS blender-unpack

ARG DEBIAN_SNAPSHOT=20260804T000000Z

# Freeze package resolution to an immutable Debian snapshot. xz-utils is kept
# out of the runtime image by extracting Blender in this throwaway stage.
RUN set -eux; \
    sed -i \
      -e "s|http://deb.debian.org/debian-security|http://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT}|g" \
      -e "s|http://deb.debian.org/debian|http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT}|g" \
      /etc/apt/sources.list.d/debian.sources; \
    printf '%s\n' 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99snapshot; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install --yes --no-install-recommends xz-utils; \
    rm -rf /var/lib/apt/lists/*

ADD --checksum=sha256:95e3a2dfedba3bd32ca54fc355eac6b15a11986954ccb02815a07535d0120a25 \
    https://download.blender.org/release/Blender4.5/blender-4.5.12-linux-x64.tar.xz \
    /tmp/blender-4.5.12-linux-x64.tar.xz
COPY docker/blender-download.sha256 /tmp/blender-download.sha256

RUN set -eux; \
    cd /tmp; \
    sha256sum --check --strict blender-download.sha256; \
    mkdir -p /opt/blender; \
    tar --extract --xz \
      --file blender-4.5.12-linux-x64.tar.xz \
      --directory /opt/blender \
      --strip-components=1; \
    test -x /opt/blender/blender


FROM --platform=linux/amd64 debian:bookworm-20260803-slim@sha256:abd67ffcfa541b485a3dff59865ab629aa048a6c613e639d36e7456b0b229241 AS builder-base

ARG DEBIAN_SNAPSHOT=20260804T000000Z

LABEL org.opencontainers.image.title="Headless Blender Character Builder" \
      org.opencontainers.image.description="Deterministic, headless Blender 4.5 LTS character builder" \
      org.opencontainers.image.source="https://github.com/joseph-robert-f/headless-blender-character-builder" \
      org.opencontainers.image.licenses="GPL-3.0-or-later" \
      org.opencontainers.image.version="0.1.0" \
      org.opencontainers.image.base.name="debian:bookworm-20260803-slim" \
      org.opencontainers.image.base.digest="sha256:abd67ffcfa541b485a3dff59865ab629aa048a6c613e639d36e7456b0b229241" \
      org.blender.version="4.5.12 LTS" \
      org.blender.download.url="https://download.blender.org/release/Blender4.5/blender-4.5.12-linux-x64.tar.xz" \
      org.blender.download.sha256="95e3a2dfedba3bd32ca54fc355eac6b15a11986954ccb02815a07535d0120a25"

# These libraries are the bounded host-facing dependencies needed by the
# official Blender binary and Mesa's CPU renderer. The Blender build itself,
# including its Python runtime, comes only from the verified official archive.
RUN set -eux; \
    sed -i \
      -e "s|http://deb.debian.org/debian-security|http://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT}|g" \
      -e "s|http://deb.debian.org/debian|http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT}|g" \
      /etc/apt/sources.list.d/debian.sources; \
    printf '%s\n' 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99snapshot; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install --yes --no-install-recommends \
      libdbus-1-3 \
      libegl-mesa0 \
      libegl1 \
      libfontconfig1 \
      libfreetype6 \
      libgl1 \
      libgl1-mesa-dri \
      libglx0 \
      libice6 \
      libpulse0 \
      libsm6 \
      libwayland-client0 \
      libwayland-cursor0 \
      libwayland-egl1 \
      libx11-6 \
      libxcursor1 \
      libxext6 \
      libxfixes3 \
      libxi6 \
      libxinerama1 \
      libxkbcommon0 \
      libxrandr2 \
      libxrender1 \
      libxxf86vm1 \
      passwd; \
    rm -rf /var/lib/apt/lists/*; \
    groupadd --gid 65532 builder; \
    useradd \
      --uid 65532 \
      --gid 65532 \
      --home-dir /work/home \
      --no-create-home \
      --shell /usr/sbin/nologin \
      builder

COPY --from=blender-unpack /opt/blender /opt/blender

WORKDIR /opt/builder/source

COPY LICENSE /usr/share/licenses/headless-blender-character-builder/LICENSE
COPY docker/BLENDER_SOURCE_NOTICE.md /usr/share/licenses/blender/SOURCE_NOTICE.md
COPY docker/blender-download.sha256 /opt/builder/provenance/blender-download.sha256
COPY pyproject.toml /opt/builder/source/pyproject.toml
COPY blender /opt/builder/source/blender
COPY shared /opt/builder/source/shared
COPY builder_cli /opt/builder/source/builder_cli
COPY scripts/builder /opt/builder/source/scripts/builder
COPY scripts/builder /usr/local/bin/builder

# Keep the upstream notices next to the container-specific source notice, and
# bake immutable build inputs into the read-only image for audit/SBOM tooling.
RUN set -eux; \
    test -f /opt/blender/license/license.md; \
    test -f /opt/blender/license/licenses.json; \
    test -f /opt/blender/license/spdx/GPL-3.0-or-later.txt; \
    test -f /opt/blender/copyright.txt; \
    cp /opt/blender/license/license.md /usr/share/licenses/blender/license.md; \
    cp /opt/blender/license/licenses.json /usr/share/licenses/blender/licenses.json; \
    cp /opt/blender/license/spdx/GPL-3.0-or-later.txt /usr/share/licenses/blender/GPL-3.0-or-later.txt; \
    cp /opt/blender/copyright.txt /usr/share/licenses/blender/copyright.txt; \
    chmod 0555 /opt/builder/source/scripts/builder /usr/local/bin/builder; \
    printf '%s\n' '4.5.12 LTS' > /opt/builder/provenance/blender-version.txt; \
    printf '%s\n' 'https://download.blender.org/release/Blender4.5/blender-4.5.12-linux-x64.tar.xz' > /opt/builder/provenance/blender-download.url; \
    sha256sum /opt/blender/blender > /opt/builder/provenance/blender-binary.sha256; \
    find blender shared builder_cli -type f -name '*.py' -print0 \
      | sort -z \
      | xargs -0 sha256sum > /opt/builder/provenance/source-files.sha256; \
    sha256sum pyproject.toml scripts/builder \
      >> /opt/builder/provenance/source-files.sha256; \
    /opt/blender/4.5/python/bin/python3.11 -c \
      'from pathlib import Path; from shared.source_revision import source_revision; print(source_revision(Path("/opt/builder/source"), include_launcher=True))' \
      > /opt/builder/provenance/source-tree.sha256; \
    /opt/blender/4.5/python/bin/python3.11 -c 'import hashlib,json,subprocess; source_hash=open("/opt/builder/provenance/source-tree.sha256",encoding="utf-8").read().strip(); rows=sorted(line.split("\t",2) for line in subprocess.check_output(["dpkg-query","-W","-f=${Package}\t${Version}\t${Architecture}\n"],text=True).splitlines()); debian=[{"name":name,"SPDXID":"SPDXRef-Debian-"+hashlib.sha256((name+"@"+version+"@"+arch).encode()).hexdigest()[:16],"versionInfo":version,"downloadLocation":"NOASSERTION","filesAnalyzed":False,"licenseConcluded":"NOASSERTION","licenseDeclared":"NOASSERTION","copyrightText":"NOASSERTION"} for name,version,arch in rows]; project={"name":"headless-blender-character-builder","SPDXID":"SPDXRef-Package-HBCB","versionInfo":"0.1.0","downloadLocation":"https://github.com/joseph-robert-f/headless-blender-character-builder","filesAnalyzed":False,"licenseConcluded":"GPL-3.0-or-later","licenseDeclared":"GPL-3.0-or-later","copyrightText":"NOASSERTION","primaryPackagePurpose":"APPLICATION","checksums":[{"algorithm":"SHA256","checksumValue":source_hash}]}; blender={"name":"Blender","SPDXID":"SPDXRef-Package-Blender","versionInfo":"4.5.12 LTS","packageFileName":"blender-4.5.12-linux-x64.tar.xz","downloadLocation":"https://download.blender.org/release/Blender4.5/blender-4.5.12-linux-x64.tar.xz","filesAnalyzed":False,"licenseConcluded":"GPL-3.0-or-later","licenseDeclared":"GPL-3.0-or-later","copyrightText":"NOASSERTION","primaryPackagePurpose":"APPLICATION","checksums":[{"algorithm":"SHA256","checksumValue":"95e3a2dfedba3bd32ca54fc355eac6b15a11986954ccb02815a07535d0120a25"}]}; base={"name":"debian","SPDXID":"SPDXRef-Package-Debian-Base","versionInfo":"bookworm-20260803-slim","downloadLocation":"https://hub.docker.com/_/debian","filesAnalyzed":False,"licenseConcluded":"NOASSERTION","licenseDeclared":"NOASSERTION","copyrightText":"NOASSERTION","primaryPackagePurpose":"OPERATING-SYSTEM","checksums":[{"algorithm":"SHA256","checksumValue":"abd67ffcfa541b485a3dff59865ab629aa048a6c613e639d36e7456b0b229241"}]}; relationships=[{"spdxElementId":"SPDXRef-DOCUMENT","relationshipType":"DESCRIBES","relatedSpdxElement":"SPDXRef-Package-HBCB"},{"spdxElementId":"SPDXRef-Package-HBCB","relationshipType":"CONTAINS","relatedSpdxElement":"SPDXRef-Package-Blender"},{"spdxElementId":"SPDXRef-Package-HBCB","relationshipType":"CONTAINS","relatedSpdxElement":"SPDXRef-Package-Debian-Base"}]+[{"spdxElementId":"SPDXRef-Package-Debian-Base","relationshipType":"CONTAINS","relatedSpdxElement":package["SPDXID"]} for package in debian]; document={"spdxVersion":"SPDX-2.3","dataLicense":"CC0-1.0","SPDXID":"SPDXRef-DOCUMENT","name":"headless-blender-character-builder-image","documentNamespace":"https://github.com/joseph-robert-f/headless-blender-character-builder/sbom/"+source_hash,"creationInfo":{"created":"2026-07-21T00:00:00Z","creators":["Tool: hbcb-dockerfile-sbom/1"]},"packages":[project,blender,base]+debian,"relationships":relationships}; open("/opt/builder/provenance/sbom.spdx.json","w",encoding="utf-8").write(json.dumps(document,sort_keys=True,separators=(",",":"))+"\n")'; \
    /opt/blender/4.5/python/bin/python3.11 -m json.tool \
      /opt/builder/provenance/sbom.spdx.json > /dev/null; \
    /opt/blender/blender --background --factory-startup --offline-mode --version \
      | grep -Fqx 'Blender 4.5.12 LTS'; \
    test -x /opt/blender/4.5/python/bin/python3.11; \
    if ldd /opt/blender/blender | grep -F 'not found'; then exit 1; fi; \
    mkdir -p /input /output /work; \
    chmod 0555 /input; \
    chmod 0777 /output; \
    chmod 1777 /work; \
    chmod -R a+rX,a-w /opt/blender /opt/builder /usr/share/licenses/blender \
      /usr/share/licenses/headless-blender-character-builder

ENV PATH="/opt/blender/4.5/python/bin:/opt/blender:/usr/local/bin:/usr/bin:/bin" \
    HOME="/work/home" \
    TMPDIR="/work/tmp" \
    PYTHONDONTWRITEBYTECODE="1" \
    LIBGL_ALWAYS_SOFTWARE="1" \
    HBCB_EXECUTION_MODE="container" \
    HBCB_WORKER_IMAGE_REFERENCE="headless-blender-character-builder:dev"

USER 65532:65532
STOPSIGNAL SIGTERM
ENTRYPOINT ["/usr/local/bin/builder"]


# Test-only target. The production `builder` stage above has no third-party
# Python dependency. This target adds only checksum-locked CPython 3.11 wheels
# and the tracked fixtures needed by the G2/G3 integration gates.
FROM builder-base AS test

USER 0:0

COPY docker/test-requirements.lock /opt/builder/test-requirements.lock
COPY . /opt/builder/source

RUN set -eux; \
    /opt/blender/4.5/python/bin/python3.11 -m pip install \
      --disable-pip-version-check \
      --no-cache-dir \
      --only-binary=:all: \
      --require-hashes \
      --requirement /opt/builder/test-requirements.lock; \
    chmod -R a+rX,a-w \
      /opt/builder/source \
      /opt/builder/test-requirements.lock \
      /opt/blender/4.5/python/lib/python3.11/site-packages

ENV TMPDIR="/work"

USER 65532:65532
ENTRYPOINT ["/opt/blender/4.5/python/bin/python3.11"]


# Keep the production image as both the named `builder` target and Docker's
# default final target. This makes the documented plain `docker build` safe:
# test-only dependencies never enter the resulting runtime image.
FROM builder-base AS builder
