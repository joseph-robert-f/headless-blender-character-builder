# Troubleshooting

## One-shot demo

A complete run ends with these markers:

```text
BUILDER_BUILD: PASS
BUILDER_VERIFY: PASS
```

The verified artifact tree is under `build/demo/`. If a build fails before the
success manifest is published, the builder removes its private staging data and
does not present a partial result as successful.

Common local issues:

- **Docker is unavailable:** start Docker Engine/Desktop and confirm
  `docker info` succeeds for the current user.
- **The first build cannot download dependencies:** the image build needs
  outbound access to pinned Blender and Debian sources. Generation and
  verification themselves run without network access.
- **`build/demo` already exists:** the builder refuses to overwrite output.
  Preserve it under a new name, for example
  `mv build/demo build/demo.previous`, before rebuilding.
- **Apple Silicon is slow:** the release image is `linux/amd64`; Docker Desktop
  runs it through emulation on Apple Silicon. Confirm `linux/amd64` emulation is
  available and allow more time than on native `amd64` Linux.
- **Native mode refuses the output:** native and Docker demos share
  `build/demo/`. Native mode additionally requires Python 3.11+ and exact
  Blender 4.5.12 LTS.

## Asynchronous service

A complete service smoke ends with:

```text
SERVICE_SMOKE: PASS evidence=.../build/service-smoke/run.XXXXXX
```

Before starting it:

- confirm `docker compose version` reports Compose v2 and `python3 --version`
  reports Python 3.11 or newer;
- confirm loopback ports `8080` and `9000` are free;
- run `make init-env` once. It intentionally refuses to overwrite an existing
  `.env`; reuse the existing mode-`0600` file or deliberately rename it before
  generating a replacement;
- after changing trusted builder or generator source, run `make image` before
  `make service-up`. The service reuses an existing local `:dev` builder tag;
- run `make service-down` after testing. It stops the stack while preserving
  the named development volumes.

Never paste `.env`, tokens, signed artifact URLs, private references, or
unredacted service logs into a public issue.

## Release checks

`make release-static` is the fast publication-policy check. The complete
`make release-check` additionally builds images, runs real Blender and service
gates, exercises recovery, and packages local evidence; it needs Compose v2,
Python 3.11+, more time/disk than the one-shot demo, and a clean intended Git
index.

Release evidence is never overwritten. If an earlier run ID already exists,
choose a new one explicitly:

```sh
HBCB_RELEASE_RUN_ID=g9-local2 make release-check
```

For a reproducible report, include the commit, platform, Docker/Compose/Python
versions, exact command, exit code, and sanitized terminal error. Follow
[SECURITY.md](../SECURITY.md) for anything sensitive.
