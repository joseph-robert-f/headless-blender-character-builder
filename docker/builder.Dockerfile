# Deterministic builder image.
#
# Blender arrives as the `bpy` PyPI wheel rather than as a downloaded tarball.
# Both give the identical Blender release and run the identical runner; the
# wheel additionally gets its integrity checked by pip against a pinned version,
# with no hand-maintained checksum file to go stale. If you would rather ship
# the Blender application itself, see docs/deployment.md.
#
# The image contains no secrets, runs as a non-root user, and needs no network
# at build time beyond installing Blender.

FROM python:3.11-slim-bookworm

# Pinned so the image, and therefore the geometry, is reproducible.
ARG BPY_VERSION=4.5.12

# Recorded in every manifest this image produces, so an artifact can be traced
# back to the source it came from. Pass with:
#   docker build --build-arg PROJECT_REVISION=$(git rev-parse HEAD) ...
ARG PROJECT_REVISION=unknown

# Blender's shared libraries need these even in headless mode; Cycles renders on
# the CPU so no GPU driver is required.
RUN apt-get update && apt-get install --no-install-recommends -y \
        libx11-6 \
        libxi6 \
        libxxf86vm1 \
        libxfixes3 \
        libxrender1 \
        libgl1 \
        libsm6 \
        libxkbcommon0 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "bpy==${BPY_VERSION}"

WORKDIR /opt/builder
COPY hbcb/ /opt/builder/hbcb/
COPY blender/ /opt/builder/blender/
COPY schemas/ /opt/builder/schemas/
COPY examples/ /opt/builder/examples/
COPY tests/ /opt/builder/tests/
COPY hbcb-cli pyproject.toml README.md LICENSE /opt/builder/

RUN echo "${PROJECT_REVISION}" > /opt/builder/revision

# Unprivileged by default. The output directory is a mount, so the caller
# controls where anything is written.
RUN useradd --create-home --uid 10001 builder \
    && mkdir -p /output \
    && chown builder:builder /output
USER builder

ENV PYTHONPATH=/opt/builder \
    PYTHONDONTWRITEBYTECODE=1 \
    HBCB_IMAGE_REFERENCE=headless-blender-character-builder

VOLUME ["/output"]

ENTRYPOINT ["python", "/opt/builder/hbcb-cli"]
CMD ["build", "--preset", "facet-bot", "-o", "/output"]
