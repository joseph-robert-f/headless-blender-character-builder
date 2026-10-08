<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# v0.1 threat model

## Separate unsigned REVIEW PREVIEW boundary

The experimental [standalone review preview](review-preview.md) packages the
existing review backend, static assets, and Python.
It opens existing projects and gives offline package verification and provenance.
It always creates a read-only backend, on each OS and independent of UI controls.
Acceptance and request POSTs fail, even with valid CSRF credentials.

The preview does not call the build controller or import project source.
It does not write project leases or state, register an installer,
download runtimes, connect providers, or open a remote listener.
The existing loopback, Host, Origin, CSRF, artifact-hash, and safe-path controls apply.
Concurrent readers are permitted. Concurrent project changes are not supported.

At startup, the package validates a complete file and link manifest in fixed limits.
Internal PyInstaller macOS links must resolve in the extracted folder.

The Windows native launcher and frozen Python payload execute before the Python inventory check.
That check is not pre-execution authentication.
The Windows launcher selects an absolute colocated payload path without a shell or environment-selected executable.
It rejects network and device paths, links, and reparse points in the launch path.
Arguments retain their UTF-16 command-line representation. The launcher bounds the expanded command line.

Only duplicated standard handles pass to the payload. Missing standard streams use `NUL`.
An atomic Windows job assignment binds the child to a kill-on-close job before it can execute.
The launcher waits for the child and returns its exit code. Forced launcher exit stops its descendants.

These controls assume no concurrent path replacement by the local OS owner.

Before payload startup, explicit System32 loads test the two documented Visual C++ runtime DLLs.
A missing or unloadable runtime produces an actionable terminal diagnostic and exit code `78`.
This is a prerequisite check, not runtime installation or a compatibility-version guarantee.
The launcher has no network, elevation, account, license-acceptance, or security-setting operation.
Its build records explicit OS-only link inputs and rejects unexpected PE imports.

The frozen payload and all packaged native files remain in the component and import inventories.
Project symlinks, junctions, and reparse points are not permitted.

Tests use the actual native executable without Python or Node on PATH.
They cover new extraction, backend write denial, tamper, shutdown, crash/reopen,
and unchanged project data.
The test harness uses hosted runners with Python.
These results are not evidence of installation on a clean consumer computer.

Unsigned archive hashes detect accidental corruption.
They do not show publisher authenticity or prevent attacks from a replaced verifier or compromised host.
CI artifacts are temporary developer evidence, not public releases.
Do not bypass security warnings.

Microsoft runtime redistribution must have an identified basis.
Documents identify each prerequisite for an existing runtime.
Apple system libraries stay external.
Each package includes complete project source, upstream notices,
native component hashes, and runtime and build provenance.
An unknown native component prevents package creation.
Native build and smoke tests do not show cross-platform generation,
installer trust, or full product support.

## Purpose and scope

This document defines the security assumptions and release scope for
Headless Blender Character Builder v0.1.
Its security analysis includes the one-shot builder, local asynchronous service,
and future single-operator VPS design.

v0.1 supports only one trusted local user with the one-shot Docker builder.
The Compose service is experimental and loopback-only.
Internet-facing services, hostile inputs, multi-tenant services, and VPS operation are outside v0.1 support.

The core design validates each caller request as untrusted data.
It trusts project-controlled generators and images as release code.
The same input validation applies when the trusted local user writes the request.
This does not support hostile requests or public service operation in v0.1.

The input must be a strict `BuildRequest v1` with a declarative `CharacterSpec v1`.
Both have limits.
The v0.1 input excludes customer- or model-authored Python, Blender commands,
add-ons, drivers, node graphs, uploaded `.blend` files, and host paths.
It also excludes remote URLs, reference images, and container controls.

## Assets to protect

- host, container runtime, worker, and Blender process integrity.
- API and internal service credentials.
- database job/attempt state and queue integrity.
- private artifacts, specified object versions, and signed download URLs.
- source, dependency, image, generator, schema, and manifest provenance.
- service availability and operator cloud/compute budget. And
- user-supplied names and build specifications.

The v0.1 schema does not accept reference images or arbitrary file uploads.
These inputs would add privacy, parser, malware, and intellectual-property risks.
A new threat-model review is necessary before such a change.

## Actors

- **Local evaluator:** runs the bundled keyless request in one container.
- **Authenticated caller:** can submit and read builds through the API token.
- **Self-hosting operator:** controls the host, release, credentials, network,
  storage, backups, and public edge.
- **Contributor or dependency publisher:** can propose code or publish an
  upstream artifact that may enter a future release.
- **Attacker:** can send malformed requests, replay requests, guess build IDs,
  use all available resources, exploit a dependency, or get a leaked URL/token.
  An attacker can try to make trusted code execute untrusted instructions.

The design trusts the self-hosting operator and reviewed release code.
Application isolation cannot prevent all effects of a compromised host administrator,
kernel, container runtime, release signer, or upstream artifact.

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

1. caller to authenticated API.
2. API/worker to role-differentd database, queue, and object storage.
3. worker supervisor to one new Blender child.
4. private attempt staging to successful immutable artifact publication.
5. artifact metadata to an authorized version-pinned download.
6. source/dependency publication to the pinned release images. And
7. containers to the operator-controlled host and network.

The one-shot mode uses no network services.
It mounts one read-only request and one caller-owned output parent in a temporary worker with no network access.

## Security invariants

These release conditions are mandatory:

- The trusted generator accepts only strict declarative schema input.
- Each attempt starts one new Blender process from factory state.
- Blender automatic embedded-script execution is disabled.
- A Blender child receives no API, database, Redis, object-storage, Docker,
  OpenAI, or other provider credential.
- In one-shot mode, the complete worker uses `--network none`.
- In service mode, the child uses the worker container's internal-only network namespace.
  The launcher removes credentials from the child environment and closes nonstandard inherited descriptors.
  The Linux supervisor is non-dumpable.
  The container has no Linux capabilities, including `CAP_SYS_PTRACE`.
  These controls prevent child process inspection of the supervisor.
  They do not create a different network namespace.
- The demo reads no `.env` and uses no secret.
- Caller values cannot become shell commands, Blender flags, host paths,
  object keys, environment-variable names, or remote download targets.
- Incomplete, failed, canceled, or `needs_review` attempts cannot publish a success manifest.
- Before publication, artifacts must pass hash validation and new reload/re-import tests.
  The service records their specified object versions.
- The 2 GiB publication limit includes all nine files,
  the canonical manifest, and its last newline.
  Local validation and service publication enforce the same total.
  The standalone client does a check of the total before download.
- The two state adapters reject non-boolean retry flags before an attempt or build change.
- Usual API and worker identities cannot administer database or storage permissions.
  The worker cannot delete artifacts.
- The worker has no Docker socket, host home, device mount, or general public ingress.

## Threats and controls

| Threat | v0.1 controls | Residual risk / follow-up |
|---|---|---|
| Arbitrary code or Blender-operation injection | Closed schemas reject fields not in the schema, code, flags, paths, URLs, add-ons, and unsupported generators. The runner exposes only reviewed request/output arguments. | A defect in trusted generator code executes with worker privileges. Code review and release tests are necessary. |
| Embedded scripts or hostile `.blend` files | Uploaded `.blend` input is not permitted. Blender uses factory startup and `--disable-autoexec`. | `--disable-autoexec` is defense in depth, not a general Python sandbox. Future file import must have a different high-isolation design. |
| Command, path, archive, or SSRF injection | Subprocess arguments are fixed. The server sets output paths and attempt/object keys. v0.1 accepts no URLs, archives, symlinks, or remote asset downloads. | New import or callback features must have explicit allowlists and threat-model changes. |
| Secret theft or exfiltration | The demo uses no key. Optional provider keys are not part of v0.1. Git ignores `.env`. Runtime roles differ. See the credential controls below. Logs are structured and secret-free. | Host administrators, kernel/runtime compromise, and compromised control-plane code can access role credentials. This closes same-UID process inspection, but it does not make Blender a sandbox for customer-authored code. Use a secret manager. Replace credentials if you suspect theft. |
| Network exfiltration | The one-shot build uses `--network none`. Blender uses `--offline-mode`. The VPS worker has no public edge network. It accesses storage only through a private controlled path. | Blender offline mode cannot constrain malicious third-party code. Network policy and container isolation set the security boundary. |
| Resource exhaustion and cost abuse | Request, object, polygon, artifact, CPU, memory, PID, scratch-space, concurrency, lease, and wall-clock bounds. Asynchronous API. One VPS worker. | v0.1 has no public hosted abuse-control plane, billing, or multi-tenant quotas. Do not expose it as an open public service. |
| Authentication bypass, IDOR, or leaked URLs | Authentication occurs before request processing. Build IDs are opaque. Artifact access uses authorization. Temporary signed URLs identify fixed versions. URLs contain no secrets. | A bearer token or signed URL grants its documented access until revoked/expired. TLS and careful client handling are mandatory. |
| Replay and duplicate execution | HMAC-bound idempotency, durable unique state, fenced leases, transactional outbox, and stale-claim recovery. | Permitted retries can consume resources up to their limits. Monitor queue depth and failures. |
| Retry/cancellation race | Attempt fencing, cancellation-wins publication locking, nested-process termination, private attempt keys, success-last publication, and a bounded grace-period orphan inventory reconciled under PostgreSQL build locks. | Host loss at a boundary can temporarily leave private versions until the independently applied janitor runs. Ambiguous/delete-marker listings fail closed. |
| Cross-attempt or cross-tenant artifact disclosure | Canonical attempt-scoped keys, specified object versions, authorization, private buckets, version-pinned URLs, and different API/worker/maintenance storage roles. | v0.1 is one deployment namespace and not a fully designed multi-tenant service. |
| Artifact corruption or false success | Private staging, atomic/local or immutable/object publication, SHA-256 and byte-size evidence, new Blender reload, GLB/STL re-import, and success-only manifest. | Hashes prove recorded bytes, not artistic quality, legal clearance, or manufacturing fitness. |
| Dependency or image compromise | Digest-pinned base/service images, checksum-pinned Blender and downloads, hash-locked wheels, immutable Debian snapshot, generated SPDX SBOM, preserved notices, and clean-source release gates. A scheduled vulnerability scan uses a fixed checksum. | Upstream compromise before pinning, scanner/database errors, and vulnerabilities absent from current advisory data can occur. Maintain supported-version and patch review. |
| Container escape or host compromise | Non-root containers, read-only roots, dropped capabilities, no-new-privileges, fixed mounts, resource limits, and no Docker socket. | Containers share the host kernel. A kernel, runtime, or native-code exploit can pass this boundary. Use a dedicated patched host and stronger isolation for future hostile-file processing. |
| Database/queue/storage privilege escalation | Generated distinct API, worker, migrator, and maintenance identities. Explicit grants. Negative permission probes. Private/internal networks. | Do checks during deployment for operator configuration errors and provider-side IAM errors. |
| Sensitive logging or retention | Structured redacted logs, private storage, explicit retention/maintenance path, version-aware deletion, bounded Redis dead-letter retention, and protected backups. | Operators choose retention, backup access, and log export destinations and must publish their own privacy policy. |
| Unauthorized character, brand, or likeness use | Original `facet-bot` default, declarative original-character scope, and `OUTPUT_POLICY.md` rights requirements. | The software cannot automatically clear IP rights. Operators must have policy, review, and takedown processes for a hosted service. |
| Unsafe physical print | Objective geometry QA and explicit `needs_review`/failure states. | No slicer-, printer-, material-, strength-, safety-, or physical-print guarantee. See `OUTPUT_POLICY.md`. |

Credential controls for secret theft and exfiltration:
Blender receives an environment without credentials and no inherited nonstandard supervisor descriptors.
Before credential client initialization, the Linux supervisor disables dumpability and core dumps.
It validates the two controls and stops on failure.
The launcher sets these controls again before each child starts.
With all capabilities dropped, same-UID descendants cannot read the supervisor's `/proc` environment or memory, or use ptrace on it.

## Supply-chain and CI rules

- Release builds must use tracked source and pinned inputs.
  They must generate an SBOM and keep upstream notices.
- Pin third-party GitHub Actions to immutable commits.
  Give them only the necessary token permissions.
- Do not execute untrusted pull requests on privileged or self-hosted runners.
  Do not give them repository, registry, cloud, signing, or deployment credentials.
- Workflows with `pull_request_target` must not execute untrusted checkout content.
- The temporary orphan-cleanup test waits for the two setup containers to exit
  successfully in 300 seconds or less.
  Missing containers, failed setup, or a wait error prevents the live deletion test.
  Cleanup removes only resources with the test's specified project and owner labels.
- Dependency updates must pass the same tests and security and license review as direct changes.
  Repository code reports candidates and findings. It cannot create dependency pull requests.
  To prevent Dependabot PRs, also disable repository-level Dependabot security updates.
  Removal of its configuration stops only configured version updates.
- The networked dependency workflow operates only from the default branch schedule
  or an explicit maintainer dispatch.
  It sends public package names, versions, ecosystems, file hashes,
  and public image metadata to the OSV/deps.dev APIs, PyPI, Docker registries,
  and GitHub-hosted official manifests.
  OSV-Scanner does not transmit source code.
  Docker builds access only the pinned public sources that the Dockerfiles specify.
  The scan receives no repository, provider, registry, or deployment credential.
- Scanner binaries and GitHub Actions use fixed commits or checksums.
  Detailed reports have individual and total byte limits.
  The system keeps reports for seven days.
  Displayed summaries exclude remote vulnerability descriptions.
  A registry or advisory outage makes the scan incomplete. It does not pass.
- Release publication, image signing, remote creation, DNS/TLS changes,
  and live deployment are explicit operator actions.
  Local tests do not do these operations.

## Out-of-scope features requiring a new review

- arbitrary Python, Blender expressions, add-ons, drivers, nodes, or flags.
- uploaded `.blend`, archive, mesh, texture, font, or reference-image parsing.
- remote URL ingestion, callbacks, webhooks, or general worker egress.
- prompt planning, OpenAI credentials, or remote MCP tools.
- GPU/device passthrough, multiple workers, multi-host scheduling, or public
  multi-tenancy.
- browser UI, accounts, billing, subscriptions, or public anonymous access.
- slicer automation or claims of physical-print success.

## Vulnerability handling and review cadence

Use `SECURITY.md` for vulnerability reports.
GitHub private vulnerability reporting is enabled for this repository.
Do not publish exploit details.

Review this threat model at each release and when a trust boundary changes.
Update threats and tests in the same PR as an applicable change.
Applicable changes include input shape, process execution, network access,
credentials, persistence, file parsing, IAM, artifact publication, and CI trust.

## Opt-in source-modeling experiment (outside v0.1)

`experimental_modeling/` is a different research implementation.
The stable builder and service do not import it.
It is not a supported package.
It uses reviewed Blender Python bundles, different trusted geometry observations,
revision policies, and immutable attempt evidence.
It does not change the v1 input contract or enable source execution through the API.

Native `--trusted-reviewed-source` mode is **not sandboxed**.
Do not give it generated code that you have not reviewed.
Resource limits and independent jobs decrease accidental failures.
They cannot prevent malicious native Python or a Blender parser exploit from access to the host or controller.

Untrusted mode stops if the isolated backend is unavailable.
The implemented Docker backend has tests, but these tests are not a security audit.
Print acceptance stops until generic print-profile gates exist.
See [the experimental design and limitations](experimental-source-modeling.md).

### Offline cat STL measurement

The [cat print experiment](experimental-print-optimization-plan.md) adds a bounded binary-STL reader for offline fixture measurements.
The runner uses reviewed local source and an immutable Docker image.
It does not add an uploaded-STL API route or enable the controller's reserved print profile.
The Docker daemon, image, host, and observer code remain trusted components.

The reader requires a regular file with 4 to 500,000 complete facets and an exact byte length of `84 + 50 * facet_count`.
The maximum STL size is 25,000,084 bytes.
It rejects links, truncated or trailing bytes, nonfinite coordinates or normals, nonzero facet attributes, and collapsed facets.
It joins only identical encoded coordinates and retains duplicate facets for topology rejection.
It performs no tolerance repair or component deletion.

Each full STL measurement uses a fresh existing Docker stage with no network, a read-only root, dropped capabilities, and no-new-privileges.
The existing limits remain 120 seconds, 4 GiB memory, 2 CPUs, 128 PIDs, 512 MiB output, 512 files, and 128 KiB logs per stage.
JSON observations remain bounded to 4 MiB.
Parser validation and these resource limits decrease accidental and malformed-input failures.
They do not rule out Blender, Python, container-runtime, or kernel vulnerabilities.

The runner binds complete source, export, and reimport geometry through file SHA-256 values, full facet counts, and exact oriented float32 surface fingerprints.
It checks the actual final STL's protected surface against the fully measured hat-free baseline.
Separate preview jobs verify the same input file and exact complete surface, then bind their receipt to the observation's file hash.
The accepted original scene chain receives separate integrity checks before and after standalone rejected STL assessments.
This experiment does not implement controller print promotion or rejection rollback.
Partial feature coverage and unresolved physical validation keep the evidence ineligible for promotion.

The observers accept only the fixed v1 and [X1C v2](experimental-x1c-print-profile.md) modeling profiles.
Every source, export, reimport, render, and preservation baseline must carry the selected profile identifier and canonical hash.
Unknown or mixed profile bindings cause rejection.
The v1 profile remains the default. A printer setup record cannot change either profile's geometry acceptance limits.

### Local experimental review program

The operator selects one trusted project store for the local review process.
The server binds only to `127.0.0.1`.
It uses Host/Origin equality, CSRF, JSON limits, fixed artifact routes,
CSP, and path/hash validation for its browser interface.
It does not execute source or automatically process prompts.
It gives no remote access and uses no CDN.

Human approval and queued requests are different from immutable machine results.
Neither can change requirements or promote a failed candidate.
The program validates requirement locks and accepted parent hashes independently
of candidate-authored flags.
These checks include missing baselines and deleted locks.

The program trusts the local owner.
It does not give multi-user authentication or prevent attacks from a filesystem
owner who replaces all trust roots.
See [local review details](local-model-review.md).

## Experimental portable project/review scaffold

The [project launcher](local-project-launcher.md) is a different optional source-checkout interface.
A project descriptor can select only fixed version-1 relative folders and a reviewed runtime policy.
It cannot select executables, enable native execution, contain provider credentials,
or decrease acceptance requirements.

The default doctor reads state without program execution.
For explicit probes and builds, the caller selects trusted absolute runtime paths outside the project.
There is no PATH discovery, image pull, runtime installation, or automatic change from isolated to native execution.

The review server uses loopback and Host/Origin/CSRF checks.
POSIX review writes keep the initial store-lock and fsync contract.

The candidate Windows review interface is read-only.
It creates no review metadata. Before a write, it rejects acceptance
and change-request mutation methods, even if a client bypasses disabled UI controls.
It does not enable generated-source execution on Windows.
Persistent Windows review writes must use a different implemented and tested adapter.
This limit does not mean that Windows cannot give persistent writes.

Project and session leases use POSIX flock semantics or a Windows kernel byte-range lock.
Do not remove lock files to force a takeover.
Stored PIDs and URLs do not show process ownership.
Before project or JSON metadata reads, the program examines Windows reparse-point attributes,
such as junctions, on Python 3.11+.

These controls assume a trusted local OS user and local filesystem.
They are not a sandbox. They cannot prevent attacks from another process with equivalent filesystem authority.

Forced process termination releases the lease.
A build error keeps a recovery marker. Examine the marker and explicitly acknowledge it.
The program does not automatically delete artifacts or Docker resources.
Console exit tests cover review only. They do not show isolation of generated subprocess trees.

Actual native-platform CI must validate each stated review support level.
A Windows or Mac review test does not show Blender generation or Docker Desktop isolation.
It also does not show cross-runtime geometry determinism, installer safety,
code signing/notarization, or provider authentication support.

## Explicit external-author request bridge

The [request bridge](model-request-bridge.md) is an optional source-checkout feature outside v0.1.
It adds inert handoff files, explicit proposal inspection, and one isolated execution command.
It does not start an AI model, coding agent, queue worker, or remote listener.
Preparation and inspection make no network call or subprocess.
Execution uses the selected local Docker daemon and existing isolated Blender stages.

A saved prompt is not execution approval.
The execution command selects a full inspection digest and a new revision identity.
That digest binds the exact request, source bytes, normalized parameters, reviewed policy, requirements, and selected runtime.
The full prompt is not truncated into the older short intent field.
The selected reference can be a rejected result, but the execution parent must remain the current accepted result.
A changed baseline stops execution instead of an automatic rebase.

The source author cannot select the runtime, replace project requirements, change accepted history, or declare verification success.
An operator selects and examines the policy independently.
Source, parameter, policy, requirement, and runtime identities are checked again before execution.
The controller records a strict versioned request-binding artifact before result publication.
Current verifiers reject partial or inconsistent new bindings.
Legacy results without this binding keep their existing verification contract.

The handoff and project evidence can contain private information.
Full prompts and source context persist in exported handoffs and model history.
Examine the exported contents before transmission to an external author or service.
The app excludes repository metadata, known agent configuration, and execution logs from handoffs.
It does not scan arbitrary source or assets for secrets.
Those exclusions do not prove that the exported files contain no private data.

Proposal reads reject links, redirected paths, devices, and nonregular files.
Nonblocking file opens prevent a named pipe from holding an input read open.
The program applies fixed limits to file bytes, file counts, directory counts, path depth, and path lengths.
The program copies source to private project staging under the existing build lease.
It checks the copied bytes before the controller takes its own source snapshot.
Generated code receives no write access to policy, request evidence, or project history.

The runtime identity includes Docker executable bytes, its selected path, the image ID, and local socket identity.
These checks detect a changed selection.
They do not establish publisher authenticity or image trust.
The operator must trust the selected Docker installation, daemon, and reviewed image.
The bridge has no native execution option or automatic runtime fallback.
Windows and Mac generation remain unavailable, and packaged previews remain read-only.

Replay verifies an existing revision and its binding before returning the recorded outcome.
It does not execute the same revision again or clear uncertain cleanup state.
Interruption retains the existing conservative recovery marker and immutable attempt evidence.
A new execution requires recovery acknowledgement where applicable and a new revision ID.
The tests are not physical power-loss tests or a general sandbox assurance.

This boundary assumes one trusted local OS owner and local filesystem.
Hashes are not signatures or protection against an owner who replaces every trust root.
The existing Docker and native-parser limitations still apply.
A verified model satisfies its declared checks, not every natural-language, appearance, electrical, or manufacturing requirement.
