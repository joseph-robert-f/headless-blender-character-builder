# PR #16 Fix Specification

Implementation spec for an autonomous fix agent. Every finding below was
verified against the PR head by reading the code at the cited locations —
do not re-litigate whether the defects exist; go straight to implementing
the fixes, re-confirming each cited location before editing it (line
numbers may drift as you land earlier tasks).

## Context

- **Repository:** `joseph-robert-f/headless-blender-character-builder`
- **PR under review:** #16, branch `codex/p1-release-hardening`, head `810af14`, base `main` (`207daf1`), +15,977/−595 across 84 files.
- **Working branch for fixes:** `claude/pr-16-review-vbsw8q` (already based on the PR head). Develop, commit, and push there. Never push to any other branch.
- **PR scope:** release hardening — a derived gosu-free Alpine PostgreSQL image, a new postgres fixture gate, release publication preflight/finalization, dependency audit/scan policy enforcement.

## Repository conventions the agent MUST follow

1. **Standalone scripts.** Everything in `scripts/` is an extensionless, self-contained, stdlib-only Python (or POSIX sh) executable. They deliberately do not import each other or any project package. Do not introduce cross-script imports.
2. **Fail-closed bounded errors.** Scripts convert every anticipated failure into a typed error with a short machine code and a secret-free detail string (`PreflightFailure(code, detail)`, `GateError(...)`, `SourceFailure(...)`), caught by an explicit exception allowlist in `main()`. Never let a new code path raise a raw traceback; never echo user-controlled or secret data in messages.
3. **Tests.** Python `unittest`, discovered per directory (`python3 -m unittest discover -s tests/release -p 'test_*.py'`). Test modules in `tests/release/` load extensionless scripts via `importlib.util.spec_from_file_location` (see the `SPEC = ...` prologue of `tests/release/test_postgres_security_gate.py:24`). Shell scripts are tested behaviorally with fake `DOCKER` / `HBCB_COMPOSE_BIN` executables written into a temp dir (see `tests/release/test_service_compose.py`).
4. **Style.** Long explicit boolean-chain validation, `type(x) is int` for bool-rejecting int checks, strict decoding (`decode("ascii"/"utf-8", "strict")`), bounded sizes on every read. Match the surrounding code; keep comment density low.
5. **Commit discipline.** One commit per task below, message prefixed with the task ID (e.g. `F3: fail closed on null Config in image inspect`). Push with `git push -u origin claude/pr-16-review-vbsw8q` (retry up to 4 times with 2s/4s/8s/16s backoff on network failure only).

## Task index and required order

| ID | Priority | File(s) | One-line summary |
|----|----------|---------|-------------------|
| F4 | P0 | `scripts/dependency-audit` | Missing postgres `target` crashes the audit with `TypeError` |
| F3 | P0 | `scripts/release-publication-preflight` | Null `Config` in `docker image inspect` raises uncaught `AttributeError` |
| F2 | P0 | `tests/security/postgres_fixture_gate.py` | `pg_isready` races the entrypoint's initdb temp server; PID-1 proof flakes |
| F5 | P1 | `docker/postgres.Dockerfile` | `ENV` bakes literal `\t` characters instead of the base image's real tabs |
| F1 | P0 | `scripts/service-compose`, docs | Pre-existing `postgres-data` volumes are silently unusable after the image swap |
| F6 | P1 | `scripts/release-publication-preflight` | Nested `_FinalizationSignalGuard`s are inert; termination checkpoints are dead code |
| F9 | P2 | `scripts/release-publication-preflight` | Every bundle artifact is read and hashed 2–3 times per run |
| F7 | P2 | `tests/security/*.py` | Postgres gate duplicates ~250 lines of the MinIO gate's machinery |
| F8 | P2 | `tests/release/` (new test) | Publication-policy validation chain is copy-pasted in three scripts |

Do them in the table's order. F3, F6, and F9 all edit
`scripts/release-publication-preflight` — they must land sequentially (F3
first, then F6, then F9). F2 and F7 both edit
`tests/security/postgres_fixture_gate.py` — F2 first. All other tasks are
independent.

After each task: run that task's acceptance commands. After all tasks: run
the full verification matrix at the end.

---

## F4 — `dependency-audit` crashes on a missing/non-string postgres `target` (P0, correctness)

### Verified problem

`scripts/dependency-audit`, `audit_compose`, local-build branch
(~lines 992–1022). When the `release/dependency-policy.json` postgres entry
has a missing or non-string `"target"`:

```python
if (
    not isinstance(base_reference, str)
    or not isinstance(dockerfile, str)
    or not isinstance(target, str)
    or target != "postgres"
):
    failures.append("Local-build Compose image recipe is incomplete")
    base_reference = "invalid"
    dockerfile = "invalid"          # <-- target is NOT reset
...
if recipe.splitlines().count("FROM scratch AS " + target) != 1:   # line ~1021
```

`base_reference` and `dockerfile` are reset to `"invalid"` but `target` is
not, so `"FROM scratch AS " + None` raises
`TypeError: can only concatenate str`, an unhandled traceback instead of the
intended audit failure. (A non-`"postgres"` *string* target is fine — only
non-string values crash.)

### Fix

In the reset block, also reset target, mirroring the existing pattern
exactly:

```python
    failures.append("Local-build Compose image recipe is incomplete")
    base_reference = "invalid"
    dockerfile = "invalid"
    target = "invalid"
```

No other change. Downstream uses (`"FROM scratch AS invalid"`, the
`required_build` format at ~line 1039) then produce ordinary "stale"
failures, consistent with how `base_reference = "invalid"` already behaves.

### Tests

Add to `tests/release/test_dependency_audit.py` (follow its existing
fixture style): a policy document whose postgres entry lacks `"target"`
(and a second case with `"target": 7`). Assert the audit **returns**
failures including `"Local-build Compose image recipe is incomplete"` and
does not raise.

### Acceptance criteria

- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.release.test_dependency_audit -v` passes, including the new cases.
- No behavior change for valid policies.

---

## F3 — `_live_image` dies with `AttributeError` on a present-but-null `Config` (P0, correctness)

### Verified problem

`scripts/release-publication-preflight:1892`:

```python
labels = value.get("Config", {}).get("Labels") if isinstance(value, dict) else None
```

The guard checks `value` is a dict but not `Config`. `docker image inspect`
output of `[{"Config": null, ...}]` (corrupted store, unexpected CLI
output) makes `value.get("Config", {})` return `None`, and
`None.get("Labels")` raises `AttributeError` — which is not in `main()`'s
`except (OSError, UnicodeError, PreflightFailure)` allowlist
(line ~2138), so the fail-closed, secret-silent CLI dies with a raw
traceback instead of `PUBLICATION_PREFLIGHT: FAIL[live_image_invalid]`.

### Fix

Replace the single line with a two-step guard in the same style:

```python
    config = value.get("Config") if isinstance(value, dict) else None
    labels = config.get("Labels") if isinstance(config, dict) else None
```

The existing boolean chain below already rejects `labels` that is not a
dict, so no further change is needed — a null `Config` now yields the
existing `PreflightFailure("live_image_invalid", ...)`.

### Tests

Find the existing `_live_image` / `verify_live_images` coverage with
`grep -n "_live_image\|verify_live_images" tests/release/*.py` and add a
case in the same file: a payload of
`[{"Architecture": "amd64", "Os": "linux", "Id": "<valid sha256:...>", "Config": null}]`
must raise `PreflightFailure` with code `live_image_invalid`, not
`AttributeError`.

### Acceptance criteria

- New test passes; the module's existing tests pass.
- No other code path in `_live_image` altered.

---

## F2 — fixture-gate readiness poll races the entrypoint's temporary initdb server (P0, correctness/flake)

### Verified problem

`tests/security/postgres_fixture_gate.py:824-846` polls readiness with
`docker exec <id> pg_isready --quiet --username hbcb_gate --dbname hbcb_gate`,
then (lines 848–865) runs a one-shot proof script asserting, among other
things, `test "$(cat /proc/1/comm)" = postgres`.

On a fresh volume, the official `docker-entrypoint.sh` runs initdb and
starts a **temporary** bootstrap server (unix-socket only,
`listen_addresses=''`) while the entrypoint shell is still PID 1.
`pg_isready` with no host defaults to the local unix socket, so it can
return 0 during that window; the proof then reads `/proc/1/comm`, sees the
shell, and the gate fails (`GateError`) on a perfectly healthy image —
recorded as `postgres-runtime-security` incomplete, which makes
`dependency-scan` exit 2 and spuriously fails the release gate.

### Fix

Fold the PID-1 condition into the poll itself so the loop only exits once
the entrypoint has `exec`'d into postgres AND the server accepts
connections. Replace the poll command tuple (lines ~826–840) with a single
shell invocation:

```python
                ready = _run(
                    (
                        docker,
                        "exec",
                        container_id,
                        "/bin/sh",
                        "-eu",
                        "-c",
                        'test "$(cat /proc/1/comm)" = postgres && '
                        "exec pg_isready --quiet --username hbcb_gate --dbname hbcb_gate",
                    ),
                    timeout=10,
                    check=False,
                )
```

Keep the loop structure, timeout, deadline, and
`termination_guard.raise_if_pending()` exactly as they are. Keep the
proof-script assertions unchanged (they remain the recorded evidence; after
this fix they can no longer race).

### Tests

`tests/release/test_postgres_security_gate.py` drives the gate with a fake
`docker` executable; `test_runtime_gate_is_hardened_proves_uid_and_removes_owned_resources`
(line ~193) will encode the old exec command shape. Update the fake's
expectations to the new `/bin/sh -eu -c` poll command, and if the fake
distinguishes poll iterations, add one iteration where the compound check
fails (simulating the initdb window) before succeeding, to lock in the
loop-not-one-shot behavior.

### Acceptance criteria

- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.release.test_postgres_security_gate -v` passes.
- If Docker is available in the environment: `make postgres-security-check` passes. If Docker is unavailable, state that this could not be run.

---

## F5 — Dockerfile bakes literal `\t` into `DOCKER_PG_LLVM_DEPS` (P1, correctness/contract)

### Verified problem

`docker/postgres.Dockerfile:42`:

```dockerfile
    DOCKER_PG_LLVM_DEPS="llvm21-dev \t\tclang21" \
```

The pinned official `postgres:16.14-alpine3.24` base sets this variable
with **real tab bytes** between the package names (upstream uses the legacy
`ENV KEY value` form with tab-indented line continuations; `docker inspect`
renders those tabs as JSON-escaped `\t`, which is what got copied here).
Dockerfile double-quoted `ENV` values do not interpret `\t`, so the derived
image's env deviates byte-for-byte from the reviewed base contract, and the
variable's documented downstream use (`apk add $DOCKER_PG_LLVM_DEPS` in
derived builds) would word-split into a bogus `\t\tclang21` package. This
contradicts the PR's stated goal of preserving the reviewed runtime
contract exactly.

Verified blast radius: `grep -rn DOCKER_PG_LLVM_DEPS` matches only this
Dockerfile line — the fixture gate's `_validate_image` does **not** assert
this variable, and `dependency-audit`'s recipe checks don't cover it. The
fix is local.

### Fix

1. Remove `DOCKER_PG_LLVM_DEPS` from the combined `ENV` block and give it
   its own instruction that reproduces the upstream value with real tabs.
   The most robust form (immune to editors converting tabs) is the
   upstream legacy form copied verbatim from
   `docker-library/postgres@4f9ced003ba58a854656ba150d146243d27ae3ac`
   `16/alpine3.24/Dockerfile` — tab-indented continuation lines:

   ```dockerfile
   ENV DOCKER_PG_LLVM_DEPS \
   		llvm21-dev \
   		clang21
   ```

   (The two continuation lines are indented with real TAB characters,
   exactly as upstream. Fetch the upstream file at that revision to copy
   the instruction byte-for-byte, including the exact llvm/clang version
   tokens — do not trust this spec's rendering of whitespace.)
2. Verify equivalence: build the `postgres` target and compare
   `docker inspect --format '{{json .Config.Env}}'` of the derived image
   against the pinned base — the `DOCKER_PG_LLVM_DEPS=` entry must be
   byte-identical. If Docker is unavailable, verify with
   `grep -P 'DOCKER_PG_LLVM_DEPS'` plus `cat -A docker/postgres.Dockerfile`
   that the file contains real tabs and no literal backslash-t.
3. Recommended hardening (small, do it): add the exact expected entry to
   `required_environment` in
   `tests/security/postgres_fixture_gate.py:_validate_image` (~line 287),
   using a Python string with real `\t` escapes —
   `"DOCKER_PG_LLVM_DEPS=llvm21-dev \t\tclang21"` — so the contract is
   pinned by the gate from now on. Update
   `tests/release/test_postgres_security_gate.py` fixtures that fabricate
   image configs to include the entry.

### Acceptance criteria

- `cat -A docker/postgres.Dockerfile` shows `^I` (tabs), and `\t` no longer appears literally in the ENV value.
- Gate unit tests pass with the new required env entry.
- If Docker is available: rebuilt image's `DOCKER_PG_LLVM_DEPS` env entry is byte-identical to the base image's.

---

## F1 — existing `postgres-data` volumes break on upgrade with no detection or migration path (P0, operability)

### Verified problem

`compose.yaml:18-25` swaps the postgres service from the official Debian
image (`postgres:16.14-bookworm@sha256:64154d...` on `main`; root
entrypoint, data chowned to uid **999**) to the derived Alpine image with
`user: "70:70"`. Any pre-PR stack that preserved its `postgres-data` named
volume (which the project's own docs mandate — `docs/configuration.md:85-95`,
`docs/api.md:496`: `make service-down` deliberately preserves volumes and
forbids pruning) hits: PGDATA owned by 999, container running as 70:70,
postgres exits with a data-directory ownership/permission error, the
`--wait` healthcheck times out, and the operator gets no explanation. Even
if ownership were fixed in place, the glibc→musl swap changes collation
behavior, so in-place reuse is unsafe regardless; a dump/restore is the
only correct path. `docs/dependency-maintenance.md:232` defers migration
design to "PostgreSQL major releases", but this same-version image swap
hits every existing deployment. The PR adds no detection and no guidance.

### Fix

Two parts — detect-and-explain, plus documentation. Never auto-delete or
auto-migrate data.

**Part 1: preflight in `scripts/service-compose` (up path).**
Before invoking `compose ... up` (after `.env` validation, alongside the
existing preflights — see `test_python_and_occupied_port_preflights_run_before_docker`
for where preflights live), add a bounded check:

1. Resolve the project-scoped volume name: `${COMPOSE_PROJECT_NAME}_postgres-data`
   (`COMPOSE_PROJECT_NAME` is already exported by `hbcb_service_identity`
   in `scripts/service-common`).
2. `docker volume inspect` it; if absent, skip (fresh install — nothing to
   check).
3. If present, probe data-directory compatibility **read-only** using the
   project's own postgres image (no new image dependencies), e.g.:

   ```sh
   "$docker_bin" run --rm --network none --read-only \
     --user 0:0 --entrypoint /bin/sh \
     --cap-drop ALL --security-opt no-new-privileges:true \
     --pids-limit 64 --memory 128m \
     -v "${volume}:/probe:ro" \
     "$postgres_image" -c \
     'test -f /probe/PG_VERSION || exit 0; test "$(stat -c %u /probe)" = 70 || exit 3'
   ```

   Exit 0 → empty or compatible, proceed. Exit 3 → fail the `up` with a
   `SERVICE_COMPOSE:` message (match the script's existing `fail` style)
   that names the volume, states that the PostgreSQL runtime now runs as
   UID 70 on Alpine and cannot reuse data initialized by the previous
   Debian image, and points to the migration doc section added in Part 2.
   Any other nonzero exit (image missing, docker error) must **not** block
   `up` on its own — fall through and let compose surface the real error
   (fail-open on probe infrastructure, fail-closed only on a positive
   incompatibility signal). Resolve the image reference the same way
   `compose.yaml` does (`HBCB_POSTGRES_IMAGE` with the same default tag);
   if the image is not present locally yet, skip the probe rather than
   pulling.

**Part 2: documentation.**
Add a migration subsection (in `docs/configuration.md` near the volume
lifecycle discussion at lines 85–95, or `docs/troubleshooting.md` — pick
whichever the existing cross-references favor, and cross-link from the
other) covering:
- why the incompatibility exists (uid 999→70, glibc→musl collations);
- the supported path: with the **old** pinned image
  (`postgres:16.14-bookworm@sha256:64154d0babcb1741988719e703419af0382b19953706149f9872fbd0f438efa8`),
  run `pg_dumpall` against the preserved volume, move the old volume aside
  (rename/keep — never prune automatically), start the new stack to
  initialize a fresh UID-70 volume, restore the dump;
- an explicit statement that discarding the volume instead is an operator
  decision, with the exact commands.
Also update `docs/dependency-maintenance.md`'s PostgreSQL section to note
that a base-OS/UID change triggers this same rehearsal even without a
major-version bump.

### Tests

In `tests/release/test_service_compose.py`, following the existing
fake-`DOCKER`/fake-`HBCB_COMPOSE_BIN` pattern:
- fake docker reports the volume present and the probe exits 3 → `up`
  fails before the compose bin is ever invoked, message mentions the
  volume name and the migration doc;
- probe exits 0 → `up` proceeds to compose;
- volume absent → probe never runs, `up` proceeds;
- probe infrastructure error (e.g. exit 125) → `up` still proceeds.

### Acceptance criteria

- All four new cases plus the existing `test_service_compose` suite pass.
- `make service-up` behavior unchanged for fresh installs.
- Docs build/lint (if `make release-static` covers docs, it must stay green — see `tests/release/test_public_docs.py`).

---

## F6 — nested `_FinalizationSignalGuard`s are inert, deferring signals across the whole finalization (P1, correctness)

### Verified problem

`scripts/release-publication-preflight:205-234`: `__enter__` installs the
`_record` handler only when the current handler is `SIG_DFL` (or the
default SIGINT handler). `main()` wraps the entire finalization in an
outer guard (line ~2088, `with _FinalizationSignalGuard() as transaction:`),
so the **inner** guards in `finalize_published_bundle` (line ~1395) and
`verify_and_commit_published_bundle` (line ~1584) see the outer `_record`
handler, install nothing, and their `self.received` can never be set.
Every `termination.raise_if_pending()` checkpoint inside those functions —
per copied file, per checksum line — is dead code in the real CLI flow.
SIGTERM/Ctrl-C during a multi-gigabyte bundle copy is silently deferred
through the full copy, SHA256SUMS regeneration, complete re-verification,
and Git recheck. The unit tests miss this because they call the inner
functions directly, without the outer guard.

The sibling `_TerminationGuard` in
`tests/security/postgres_fixture_gate.py:70-118` already solves exactly
this with a module-global active guard + delegation. Port that pattern.

### Fix

In `scripts/release-publication-preflight`:

1. Add a module global next to the class:
   `_ACTIVE_FINALIZATION_GUARD: Optional["_FinalizationSignalGuard"] = None`.
2. Extend `_FinalizationSignalGuard` following the `_TerminationGuard`
   shape, adapted to this class's existing semantics:
   - `__init__`: add `self.delegate: Optional["_FinalizationSignalGuard"] = None`.
   - `__enter__`: if `_ACTIVE_FINALIZATION_GUARD` is not None, set
     `self.delegate = _ACTIVE_FINALIZATION_GUARD` and return `self`
     without touching handlers. Otherwise set the global to `self` and
     keep the existing install loop unchanged.
   - `raise_if_pending`: read
     `self.delegate.received if self.delegate is not None else self.received`.
   - `__exit__`: if `self.delegate is not None`: only
     `raise_if_pending()` when `kind is None` (preserve this class's
     existing "don't mask an in-flight exception" rule — note this
     differs from `_TerminationGuard.__exit__`, which raises
     unconditionally; keep THIS class's rule), then return. Otherwise
     restore handlers as today, clear the global
     (`if _ACTIVE_FINALIZATION_GUARD is self: ... = None`), and keep the
     existing `if kind is None: raise_if_pending()`.
3. No changes at the call sites — the inner guards now delegate to the
   outer one, making every existing checkpoint live.

### Tests

In the file that currently tests finalization interruption (find with
`grep -rn "_FinalizationSignalGuard\|_FinalizationInterrupted" tests/release/`),
add:
- nested-guard delivery: enter an outer guard, enter an inner guard,
  `os.kill(os.getpid(), signal.SIGTERM)`, then assert the **inner**
  guard's `raise_if_pending()` raises `_FinalizationInterrupted` with
  `signum == signal.SIGTERM`;
- handler restoration: after both guards exit, `signal.getsignal(SIGTERM)`
  is back to its pre-test value;
- the exception-in-flight rule still holds: an exception raised inside a
  delegating inner guard propagates unchanged (no
  `_FinalizationInterrupted` masking it).
Existing direct-call tests must pass unmodified.

### Acceptance criteria

- New and existing preflight tests pass.
- `python3 scripts/release-publication-preflight --help` (or its no-arg failure path) still behaves; no import-time side effects added.

---

## F9 — preflight reads and hashes every bundle artifact 2–3 times (P2, efficiency)

### Verified problem

Three verified redundancies in `scripts/release-publication-preflight`:

1. `_verify_sample_bundle` (lines ~937–941) reads
   `sample/manifest.json` twice back-to-back: `_read_regular(...)` for the
   digest, then `_json_file(...)` (which itself calls `_read_regular`) for
   the parsed value.
2. `verify_bundle` (line ~1235 vs ~1251): `verify_checksums` reads and
   SHA-256-hashes **every** file in the bundle against `SHA256SUMS`; then
   `_verify_release_artifact_inventory` re-reads and re-hashes all of them
   again against `release-metadata.json`, and both functions perform an
   identical `rglob` directory sweep.
3. `verify_bundle` line ~1258 re-reads `corresponding-source.json` via
   `_read_regular` immediately after `_json_file` read it at line ~1238.

Net effect: 2–3 full read+hash passes over a bundle that can be hundreds
of megabytes, and the finalize path runs `verify_bundle` again on the
copied output. Single-read verification is strictly better here, including
for TOCTOU posture: each artifact is read once under `_read_regular`'s
identity checks and every downstream judgment uses those exact bytes.

### Fix

Keep every failure code and message reachable and unchanged. Mechanics:

1. Split `_json_file` into `_json_payload(payload: bytes) -> Mapping` (the
   parse + canonical-form check, raising the same `invalid_json` failures)
   and a thin `_json_file(path)` wrapper that reads then delegates. Where
   a caller needs bytes AND value (`sample/manifest.json`,
   `corresponding-source.json`), read once with `_read_regular` and call
   `_json_payload` — removing redundancies (1) and (3).
2. Change `verify_checksums` to return
   `Dict[str, tuple[int, str]]` mapping each checksummed path to
   `(byte_count, sha256)` (it already computes both; `len(content)` gives
   the size). `verify_bundle` passes that map into
   `_verify_release_artifact_inventory`, which then validates each
   inventory record **against the map** (name present, bytes equal, digest
   equal — same `identity_mismatch` failures) instead of re-reading files.
   Keep its structural validation of the inventory list itself. Drop its
   duplicate `rglob` sweep only if the surviving checks still guarantee
   what it guaranteed before: `verify_checksums`'s sweep already enforces
   "file set on disk == SHA256SUMS entries + SHA256SUMS"; the inventory
   check must still enforce its own set relationship between inventory
   names and checksummed names (re-derive it from the two maps, preserving
   the existing failure codes for mismatches). If any guarantee cannot be
   reproduced from the maps alone, keep that specific check as a
   file-system check rather than weakening it.
3. Do NOT touch the finalize path's second `verify_bundle` over the copied
   output — re-verifying the copy is intentional.

### Tests

Existing suite is the main guard. Add one focused test: an inventory
record whose digest disagrees with the file (while `SHA256SUMS` agrees
with the file) still fails with `identity_mismatch`, proving the
map-comparison path detects divergence between the two metadata sources.

### Acceptance criteria

- Full `tests/release` suite passes.
- `grep -c "_read_regular" scripts/release-publication-preflight` shows the sample-manifest and corresponding-source double reads are gone.
- No failure code removed or renamed (diff review).

---

## F7 — postgres gate duplicates the MinIO gate's process/ownership machinery (P2, reuse)

### Verified problem

`tests/security/postgres_fixture_gate.py` re-implements, near-verbatim,
machinery from `tests/security/minio_fixture_gate.py`:
`_TerminationSignal` (pg:64 / minio:34), `_TerminationGuard` (pg:70 /
minio:40 — the pg version adds the delegate mechanism), `_safe_tool_selector`
(pg:121 / minio:78), `_run` (pg:136 / minio:93), plus pg-side
process-group helpers and the `_owned_container_ids` /
`_remove_owned_container` ownership pattern (pg:624/698 vs minio:171/203).
The copies have already drifted (grace constants, delegate support), and a
fix to one will not propagate.

### Fix

Extract a shared module `tests/security/fixture_gate_common.py` containing
the superset implementations (adopt the postgres gate's delegate-capable
`_TerminationGuard` and its process-group handling; parametrize anything
that differs — message prefixes/labels, grace constants — via arguments or
module constants passed by each gate). Refactor **both** gates to use it.
Behavior and error-message text asserted by
`tests/release/test_postgres_security_gate.py` and
`tests/release/test_minio_security_gate.py` must not change — parametrize
messages so each gate keeps its current strings.

**Import hazard — handle explicitly.** The gates execute in two modes:
1. as scripts (`make postgres-security-check` →
   `python3 tests/security/postgres_fixture_gate.py`): the script's own
   directory is on `sys.path`, so `import fixture_gate_common` works;
2. loaded by path via `importlib.util.spec_from_file_location` from
   `tests/release/*` (repo root cwd): `tests/security` is NOT on
   `sys.path`, so a bare import fails.

Make each gate load the common module relative to its own file before
first use, e.g. at module top:

```python
_COMMON_DIR = str(Path(__file__).resolve().parent)
if _COMMON_DIR not in sys.path:
    sys.path.insert(0, _COMMON_DIR)
import fixture_gate_common
```

(or load it with `importlib.util.spec_from_file_location` keyed on
`__file__`; either is acceptable — but verify BOTH execution modes pass).
Also confirm `python3 -m unittest discover -s tests/security` still works
(the new module must not look like a test: no `test_*.py` name).

**Explicitly out of scope:** consolidating the four defensive
bounded-reader copies across `scripts/release-publication-preflight`
(`_read_regular`), `scripts/service-client` (`_regular_private_file`),
`scripts/dependency-scan`, and `builder_cli/commands.py`. Those scripts
are deliberately self-contained standalone executables (convention 1);
introducing cross-script imports is an architecture decision for the
maintainer, not this agent. Leave them alone.

### Acceptance criteria

- `python3 -m unittest tests.release.test_postgres_security_gate tests.release.test_minio_security_gate -v` passes unmodified (message strings intact).
- Both gates still run as standalone scripts: `python3 tests/security/postgres_fixture_gate.py --help` (or its bounded failure path) and same for the MinIO gate.
- If Docker is available: `make postgres-security-check` and `make minio-security-check` pass.
- Net line count across the two gates + common module is meaningfully lower than before (sanity check that this was a real extraction).

---

## F8 — publication-policy validation chain triplicated across three standalone scripts (P2, reuse/drift tripwire)

### Verified problem

The ~25-line publication-policy boolean chain (delivery_method /
public_oci_ready / publication_gate / retention / scope, including the two
cross-consistency equalities) is copy-pasted three times:

- `scripts/fetch-corresponding-source:90-116` (`load_policy`)
- `scripts/release-artifacts:~222-246` (`_load_corresponding_source_policy`)
- `scripts/release-publication-preflight:~330-350` (`_source_policy`)

A future schema change edited in only two of the three silently
desynchronizes release gates (e.g. `release-artifacts` accepts a policy
that `release-publication-preflight` rejects), and nothing currently
forces the three to stay equal.

### Fix

Do **not** merge the code — these are deliberately self-contained scripts
(convention 1). Instead add a drift tripwire:
`tests/release/test_publication_policy_consistency.py`, which loads all
three scripts via the existing `spec_from_file_location` pattern and runs
each script's policy loader against one shared table of policy fixtures,
asserting the three agree (all accept, or all reject) on every case.

Fixture table must at least cover:
- the real tracked policy file `release/corresponding-source-policy.json` (all three must accept — adapt per-loader input shape: some take a file path, some take bytes/parsed docs; wrap accordingly);
- each `publication_gate` value × each `public_oci_ready` boolean (consistent and inconsistent combinations);
- each `scope` value × `public_oci_ready` (consistent and inconsistent);
- wrong `delivery_method`, wrong `retention`, extra key in `publication`, missing key, non-bool `public_oci_ready` (e.g. `1`, which `type(...) is not bool` must reject);
- 20+ cases total is expected.

Note the three loaders sit at different altitudes (whole-policy-file vs
publication-section); normalize by feeding each loader a complete policy
document varying only the `publication` section, and treat "raises its
script's failure type" as reject. Blender-section differences are out of
scope — hold that section constant and valid.

### Acceptance criteria

- New test passes on the current tree.
- Mutation check (manual, then revert): flip one accepted `publication_gate` string in ONE script's chain — the consistency test must fail. Revert before committing.

---

## Final verification matrix

Run after all tasks, from the repo root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/release -p 'test_*.py' -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/security -p 'test_*.py' -v
sh -n scripts/service-compose
```

If Docker is available additionally run:

```sh
make postgres-security-check
make minio-security-check
make release-static
```

Report exact pass/fail output for each; do not summarize failures away. If
an environment limitation (no Docker, no network) blocks a check, say so
explicitly in the final report rather than skipping silently.

Then push:

```sh
git push -u origin claude/pr-16-review-vbsw8q
```

## Reporting

Finish with a summary listing, per task ID: commit SHA, what changed,
tests added, and acceptance-criteria status. Flag any place where reality
diverged from this spec (moved lines, renamed helpers) and how you
resolved it.
