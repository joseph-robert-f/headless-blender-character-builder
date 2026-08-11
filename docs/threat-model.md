<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# v0.1 threat model

## Purpose and scope

This document defines the security assumptions and release boundary for
Headless Blender Character Builder v0.1. It covers the keyless one-shot
builder, the local asynchronous service, and the single-operator VPS reference
deployment. It does not claim to secure a public multi-tenant hosted product.

The core design treats every caller-supplied request as untrusted and every
project-controlled generator and image as trusted release code. The supported
input is a strict, bounded `BuildRequest v1` containing a declarative
`CharacterSpec v1`. Customer- or model-authored Python, Blender commands,
add-ons, drivers, node graphs, uploaded `.blend` files, host paths, remote
URLs, reference-image ingestion, and container controls are outside v0.1.

## Assets to protect

- host, container runtime, worker, and Blender process integrity;
- API and internal service credentials;
- database job/attempt state and queue integrity;
- private artifacts, exact object versions, and signed download URLs;
- source, dependency, image, generator, schema, and manifest provenance;
- service availability and operator cloud/compute budget; and
- user-supplied names and build specifications.

The v0.1 schema does not accept reference images or arbitrary file uploads.
Those would introduce additional privacy, parser, malware, and intellectual-
property risks and require a new threat-model review.

## Actors

- **Local evaluator:** runs the bundled keyless request in one container.
- **Authenticated caller:** can submit and read builds through the API token.
- **Self-hosting operator:** controls the host, release, credentials, network,
  storage, backups, and public edge.
- **Contributor or dependency publisher:** can propose code or publish an
  upstream artifact that may enter a future release.
- **Attacker:** may send malformed requests, replay requests, guess build IDs,
  exhaust resources, exploit a dependency, obtain a leaked URL/token, or try
  to make trusted code execute untrusted instructions.

The self-hosting operator and reviewed release code are trusted. A compromised
host administrator, kernel, container runtime, release signer, or upstream
artifact is outside what application-level isolation can fully contain.

## Data flow and trust boundaries

```text
untrusted caller
    |
    | bearer auth + bounded JSON
    v
API/control plane -----> PostgreSQL (authoritative state)
    |                         |
    | build ID/outbox         +----> Redis (wake-up coordination)
    v
worker supervisor -----> exact-version object storage
    |
    | canonical trusted request; scrubbed environment
    v
fresh Blender child ----> private attempt staging ----> immutable publication
                                                   |
                                                   v
                                      version-pinned signed URL
```

Primary boundaries are:

1. caller to authenticated API;
2. API/worker to role-separated database, queue, and object storage;
3. worker supervisor to one fresh Blender child;
4. private attempt staging to successful immutable artifact publication;
5. artifact metadata to an authorized version-pinned download;
6. source/dependency publication to the pinned release images; and
7. containers to the operator-controlled host and network.

The one-shot path removes the network services: it mounts one read-only request
and one caller-owned output parent into a network-disabled disposable worker.

## Security invariants

The following are release invariants, not optional recommendations:

- Only strict declarative schema input reaches the trusted generator.
- One attempt starts one fresh Blender process from factory state.
- Blender automatic embedded-script execution is disabled.
- A Blender child receives no API, database, Redis, object-storage, Docker,
  OpenAI, or other provider credential.
- The keyless demo reads no `.env` and requires no secret.
- Caller-controlled values never become shell commands, Blender flags, host
  paths, object keys, environment-variable names, or remote fetch targets.
- Incomplete, failed, cancelled, or `needs_review` attempts cannot publish a
  success manifest.
- Successful artifacts are hash verified, tied to exact object versions, and
  published only after fresh reload/re-import evidence passes.
- Normal API and worker identities cannot administer database or storage
  permissions; the worker cannot delete artifacts.
- The worker has no Docker socket, host home, device mount, or general public
  ingress.

## Threats and controls

| Threat | v0.1 controls | Residual risk / follow-up |
|---|---|---|
| Arbitrary code or Blender-operation injection | Closed schemas reject extra fields, code, flags, paths, URLs, add-ons, and unsupported generators. The runner exposes only reviewed request/output arguments. | A defect in trusted generator code still executes with worker privileges. Code review and release tests remain necessary. |
| Embedded scripts or hostile `.blend` files | No uploaded `.blend` input; Blender uses factory startup and `--disable-autoexec`. | `--disable-autoexec` is defense in depth, not a general Python sandbox. Future file import needs a separate high-isolation design. |
| Command, path, archive, or SSRF injection | Subprocess arguments are fixed; output paths and attempt/object keys are server-controlled; v0.1 accepts no URLs, archives, symlinks, or remote asset fetches. | New import or callback features require explicit allowlists and threat-model changes. |
| Secret theft or exfiltration | Demo is keyless; optional provider keys are out of v0.1; `.env` is ignored; runtime roles are distinct; Blender gets a scrubbed environment; logs are structured and secret-free. | Host administrators and compromised control-plane code can access role credentials. Use a secret manager and rotate on suspicion. |
| Network exfiltration | One-shot build uses `--network none`; Blender uses `--offline-mode`; VPS worker lacks the public edge network and reaches storage only through a private controlled path. | Blender offline mode cannot constrain malicious third-party code. Network policy/container isolation is the real boundary. |
| Resource exhaustion and cost abuse | Request, object, polygon, artifact, CPU, memory, PID, scratch-space, concurrency, lease, and wall-clock bounds; asynchronous API; one VPS worker. | v0.1 has no public hosted abuse-control plane, billing, or multi-tenant quotas. Do not expose it as an open public service. |
| Authentication bypass, IDOR, or leaked URLs | Auth precedes request handling; opaque build IDs; artifact authorization; short-lived, exact-version signed URLs; no secrets in URLs. | A bearer token or signed URL grants its documented access until revoked/expired. TLS and careful client handling remain mandatory. |
| Replay and duplicate execution | HMAC-bound idempotency, durable unique state, fenced leases, transactional outbox, and stale-claim recovery. | Legitimate retries can still consume bounded resources; monitor queue depth and failures. |
| Retry/cancellation race | Attempt fencing, cancellation-wins publication locking, nested-process termination, private attempt keys, and success-last publication. | Host loss at a boundary can leave private/orphaned versions for maintenance cleanup. |
| Cross-attempt or cross-tenant artifact disclosure | Canonical attempt-scoped keys, exact object versions, authorization, private buckets, version-pinned URLs, and separate API/worker/maintenance storage roles. | v0.1 is one deployment namespace and not a fully designed multi-tenant service. |
| Artifact corruption or false success | Private staging, atomic/local or immutable/object publication, SHA-256 and byte-size evidence, fresh Blender reload, GLB/STL re-import, and success-only manifest. | Hashes prove recorded bytes, not artistic quality, legal clearance, or manufacturing fitness. |
| Dependency or image compromise | Digest-pinned base/service images, checksum-pinned Blender and downloads, hash-locked wheels, immutable Debian snapshot, generated SPDX SBOM, preserved notices, clean-source release gates, and a scheduled checksum-pinned vulnerability scan. | Upstream compromise before pinning, scanner/database errors, and vulnerabilities absent from current advisory data remain possible. Maintain supported-version and patch review. |
| Container escape or host compromise | Non-root containers, read-only roots, dropped capabilities, no-new-privileges, fixed mounts, resource limits, and no Docker socket. | Containers share the host kernel. A kernel/runtime/native-code exploit can cross the boundary; use a dedicated patched host and stronger isolation for future hostile-file processing. |
| Database/queue/storage privilege escalation | Generated distinct API, worker, migrator, and maintenance identities; explicit grants; negative permission probes; private/internal networks. | Operator misconfiguration or provider-side IAM mistakes remain possible and must be checked during deployment. |
| Sensitive logging or retention | Structured redacted logs, private storage, explicit retention/maintenance path, version-aware deletion, and protected backups. | Operators choose retention, backup access, and log export destinations and must publish their own privacy policy. |
| Unauthorized character, brand, or likeness use | Original `facet-bot` default, declarative original-character scope, and `OUTPUT_POLICY.md` rights requirements. | The software cannot automatically clear IP rights. Operators need policy, review, and takedown processes for a hosted service. |
| Unsafe physical print | Objective geometry QA and explicit `needs_review`/failure states. | No slicer-, printer-, material-, strength-, safety-, or physical-print guarantee. See `OUTPUT_POLICY.md`. |

## Supply-chain and CI rules

- Release builds must use tracked source and pinned inputs, generate an SBOM,
  and retain upstream notices.
- Third-party GitHub Actions should be pinned to immutable commits and receive
  the minimum token permissions.
- Untrusted pull requests must not execute on a privileged/self-hosted runner
  or receive repository, registry, cloud, signing, or deployment credentials.
- Workflows using `pull_request_target` must not execute untrusted checkout
  content.
- Dependency updates require the same tests and security/licensing review as
  direct edits. Repository code reports candidates and findings but has no
  permission or path to create dependency pull requests. Operators who want no
  Dependabot PRs must also disable repository-level Dependabot security updates;
  removing its configuration disables only configured version updates.
- The networked dependency workflow runs only on the default branch schedule or
  explicit maintainer dispatch. It sends public package names, versions,
  ecosystems, file hashes, and public image metadata to the OSV/deps.dev APIs,
  PyPI, Docker registries, and GitHub-hosted official manifests; OSV-Scanner
  does not transmit source code. Docker builds also access only the pinned
  public sources already declared by the Dockerfiles. No repository, provider,
  registry, or deployment credential is supplied to the scan.
- Scanner binaries and GitHub Actions are immutable/checksum pinned; detailed
  reports have per-file and aggregate byte limits, are retained for seven days,
  and rendered summaries exclude remote vulnerability descriptions.
  Registry/advisory outages fail the scan as incomplete rather than clean.
- Release publication, image signing, remote creation, DNS/TLS changes, and
  live deployment are explicit operator actions, not local-test side effects.

## Out-of-scope features requiring a new review

- arbitrary Python, Blender expressions, add-ons, drivers, nodes, or flags;
- uploaded `.blend`, archive, mesh, texture, font, or reference-image parsing;
- remote URL ingestion, callbacks, webhooks, or general worker egress;
- prompt planning, OpenAI credentials, or remote MCP tools;
- GPU/device passthrough, multiple workers, multi-host scheduling, or public
  multi-tenancy;
- browser UI, accounts, billing, subscriptions, or public anonymous access;
- slicer automation or claims of physical-print success.

## Vulnerability handling and review cadence

Follow `SECURITY.md` for reporting. Private GitHub reporting is conditional on
repository publication and the maintainer enabling it. Do not post exploit
details publicly.

Review this threat model whenever a trust boundary changes and at each release.
A pull request that changes input shape, process execution, network access,
credentials, persistence, file parsing, IAM, artifact publication, or CI trust
must update the relevant threats and tests in the same change.
