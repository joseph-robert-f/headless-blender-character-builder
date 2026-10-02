# Experimental modeling container backend

**Status: implemented.** Live Docker boundary tests and the two complete model benchmarks passed on commit `cb452850a05238ddde155666cad7fe11476b10be`.
Read [CI run 36864042600](https://github.com/joseph-robert-f/headless-blender-character-builder/actions/runs/36864042600).
This historical result applies to that commit only.
The experimental boundary is not a security assurance from an audit done independently.
After changes, make sure that CI passes on the current PR head.

**CAUTION:** Do not execute arbitrary generated Python in native reviewed-source mode.
That mode can change files with the authority of your OS account.
A Docker failure never causes automatic native execution.

The backend uses local Linux Docker with default seccomp and cgroup memory, PID, and CPU controls.
An exact existing `sha256:` image ID is mandatory.
Build the `builder` target from the pinned `docker/builder.Dockerfile`.
Then get its image ID.
The backend rejects tags and remote image pulls.

Use only an image and daemon that you trust.
An immutable ID alone does not show image trust.
The backend rejects unexpected image ENV keys and declared image volumes.
It replaces permitted ENV values with fixed values that contain no sensitive data.
This replacement also applies to container PID 1.

Each author, inspector, GLB roundtrip, and saved-Blend reopening stage uses a new container.
Each container has these controls:

- A read-only root filesystem
- No network, capabilities, or new privileges
- Non-root UID and GID 65532
- Fixed limits for RAM, swap, CPU, process count, file size, log bytes, and wall time.

Source and parameters use read-only mounts with a small scope.
Inspector containers get only the trusted inspector script, candidate input, and an observation reference when necessary.
They do not get generated source, policy, controller, last-good state, Docker socket, host environment, or user credentials.
The existing image contains read-only stable builder code.
This code does not give write access to policy or acceptance authority.

The application can write only to `/output`.
This directory uses a Docker local volume with tmpfs backing and per-run size and inode limits.
It is not a host bind mount.
Standard runtime devices remain available.
IPC shared memory is off.

After Blender exits, the backend pauses the complete container to stop children that remain.
An isolated exporter container mounts the volume read-only and streams a tar archive with fixed limits.
Docker cp cannot reliably copy tmpfs.
The controller parses the archive without tar extraction helpers and copies its content to new host files.
It rejects links, devices, sparse files, duplicate entries, absolute paths, parent-traversal paths, and content above the limits.

A failed stage can keep safe diagnostic files with fixed size limits.
It cannot become accepted.
Only the parent controller evaluates acceptance.

The `finally` block tries to remove the two containers and the temporary volume.
A removal failure stops the operation.
If the daemon becomes unreachable, examine the `modeling-*` containers and volumes.
Before more work, make sure that cleanup removed the resources from the failed operation.

The dedicated PR and manual workflow builds the existing image.
It runs container smoke tests and the complete robot revision benchmark.
Smoke tests examine read-only paths, network access, UID, timeout and child cleanup, output limits, and failed-attempt diagnostics.
The workflow does not publish or deploy artifacts.
For the optional local smoke test, enter these commands:

```sh
export MODELING_SANDBOX_IMAGE="$(docker image inspect --format '{{.Id}}' modeling-sandbox-test)"
python3 -m unittest discover -s tests/experimental_modeling -p test_sandbox.py -v
```

A skipped smoke test is not runtime-verification evidence.
Make sure that the test actually runs before you report runtime verification.
A pass shows only the tested conditions.
It does not prove resistance to unknown Docker, Linux kernel, or Blender vulnerabilities.
Before hostile production use, get an assessment done independently.
Use a hardened disposable Docker host with current security updates.
