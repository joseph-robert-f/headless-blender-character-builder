# Experimental modeling container backend

**Status: implemented; live Docker boundary probes and both complete model
benchmarks passed on commit `cb452850a05238ddde155666cad7fe11476b10be` in
[CI run 36864042600](https://github.com/joseph-robert-f/headless-blender-character-builder/actions/runs/36864042600).** This is an experimental boundary, not an audited
security guarantee. Recheck CI on the current PR head after changes. The native reviewed-source mode remains explicitly unsafe
for arbitrary generated Python. No Docker failure falls back to native execution.

The backend requires local Linux Docker, default seccomp, cgroup memory/PID/CPU
support, and an exact existing `sha256:` image ID. Build the existing pinned
`docker/builder.Dockerfile` target `builder`, then resolve its image ID. Tags and
remote image pulls are rejected. The operator must trust the image and daemon;
immutable identity alone does not establish image trust. Unexpected image ENV
keys and declared image volumes are rejected; allowed ENV keys are overridden
with fixed nonsensitive values, including for container PID 1.

Every author, inspector, GLB roundtrip and saved Blend reopen stage gets a fresh
container with a read-only root, no network, no capabilities, no new privileges,
non-root UID/GID 65532, bounded RAM/swap, CPU, process count, file size, log bytes,
and wall time. Source and parameters are narrow read-only mounts. Inspector
containers receive only the trusted inspector script, candidate input, and when
needed the observation reference. They receive neither generated source nor
policy, controller, last-good state, Docker socket, host environment, or user
credentials. The existing image contains read-only stable builder code; this is
not writable policy or acceptance authority.

Only `/output` is application-writable, as a per-run size/inode-bounded tmpfs-backed Docker local volume. It is not a
host bind mount. Standard runtime devices still exist; IPC shared memory is off.
After Blender exits, the entire container is paused to freeze surviving children.
A separate locked-down exporter container mounts that volume read-only and streams
a bounded tar archive. (Docker cp cannot reliably copy tmpfs.) The archive is parsed without tar extraction helpers,
and copied to fresh host files. Links, devices, sparse files, duplicate entries,
absolute/traversal paths and budget excesses fail closed. A failed stage may retain
bounded safe diagnostics, but cannot become accepted. The parent alone evaluates
acceptance. Forced removal of both containers and the temporary volume is attempted in `finally`; failure is fatal.
If the daemon itself becomes unreachable, the operator must verify removal of
`modeling-*` containers and volumes before resuming work.

A standalone PR/manual workflow builds the existing image and runs container
smoke tests (read-only paths, network, UID, timeout/descendant cleanup, bounded
output and failed-attempt diagnostics) plus the complete robot revision benchmark. It does not publish or
deploy anything. Run the opt-in smoke locally with:

```sh
export MODELING_SANDBOX_IMAGE="$(docker image inspect --format '{{.Id}}' modeling-sandbox-test)"
python3 -m unittest discover -s tests/experimental_modeling -p test_sandbox.py -v
```

The opt-in smoke must actually run rather than skip before claiming runtime
verification. Passing it establishes tested conditions only, not resistance to
unknown Docker/Linux kernel or Blender vulnerabilities. Hostile production use
needs independent review and a hardened, patched, disposable Docker host.
