from __future__ import annotations

import contextlib
import io
import json
import re
import unittest
from typing import Iterator

from tests.release.support import ROOT


WORKFLOW_ROOT = ROOT / ".github" / "workflows"
WORKFLOWS = tuple(sorted((*WORKFLOW_ROOT.glob("*.yml"), *WORKFLOW_ROOT.glob("*.yaml"))))
FULL_ACTION_SHA = re.compile(
    r"^(?!(?:\.{1,2})(?:/|@))(?!.*(?:/\.{1,2})(?:/|@))"
    r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*@[0-9a-f]{40}$"
)
CHECKOUT_ACTION = "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd"  # v6.0.2
UPLOAD_ARTIFACT_ACTION = "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"  # v7.0.1


def values(value: object, key: str) -> Iterator[object]:
    if isinstance(value, dict):
        for name, child in value.items():
            if name == key:
                yield child
            yield from values(child, key)
    elif isinstance(value, list):
        for child in value:
            yield from values(child, key)


class ReleasePolicyTests(unittest.TestCase):
    def test_workflows_are_json_form_yaml_with_minimal_permissions(self) -> None:
        self.assertEqual(
            {path.name for path in WORKFLOWS},
            {"ci.yml", "dependency-audit.yml", "release-candidate.yml"},
        )
        for path in WORKFLOWS:
            with self.subTest(path=path.name):
                document = json.loads(path.read_text(encoding="utf-8"))
                self.assertIsInstance(document, dict)
                self.assertEqual(document.get("permissions"), {"contents": "read"})
                self.assertTrue(
                    all(item == {"contents": "read"} for item in values(document, "permissions")),
                    path.name,
                )
                self.assertNotIn("pull_request_target", document.get("on", {}))
                self.assertTrue(document.get("jobs"))
                if path.name == "ci.yml":
                    service_job = document["jobs"].get("service")
                    self.assertIsInstance(service_job, dict)
                    self.assertNotIn("if", service_job)

    def test_external_actions_are_full_sha_pinned_and_checkout_drops_credentials(self) -> None:
        for path in WORKFLOWS:
            document = json.loads(path.read_text(encoding="utf-8"))
            uses = list(values(document, "uses"))
            self.assertTrue(uses, path.name)
            self.assertTrue(
                all(isinstance(item, str) and FULL_ACTION_SHA.fullmatch(item) for item in uses),
                path.name,
            )
            checkout_steps = [
                step
                for step in values(document, "steps")
                if isinstance(step, list)
                for item in step
                if isinstance(item, dict)
                for step in (item,)
                if str(step.get("uses", "")).startswith("actions/checkout@")
            ]
            self.assertTrue(checkout_steps, path.name)
            for step in checkout_steps:
                self.assertEqual(step.get("uses"), CHECKOUT_ACTION)
                self.assertEqual(step.get("with", {}).get("persist-credentials"), False)

    def test_action_reference_policy_rejects_mutable_or_ambiguous_uses(self) -> None:
        self.assertTrue(FULL_ACTION_SHA.fullmatch(CHECKOUT_ACTION))
        for unsafe in (
            "actions/checkout@main",
            "actions/checkout@v6",
            "actions/checkout@de0fac2",
            "actions/checkout@${{ github.sha }}",
            "docker://example.invalid/image@sha256:" + "a" * 64,
            "owner/repository@" + "A" * 40,
            "owner/repository@" + "a" * 39,
            "owner/repository/../action@" + "a" * 40,
            "owner/repository/path@" + "a" * 40 + " extra",
        ):
            with self.subTest(unsafe=unsafe):
                self.assertIsNone(FULL_ACTION_SHA.fullmatch(unsafe))

    def test_pull_request_dco_job_uses_exact_event_shas_and_full_history(self) -> None:
        document = json.loads((WORKFLOW_ROOT / "ci.yml").read_text(encoding="utf-8"))
        self.assertIn("pull_request", document.get("on", {}))
        self.assertNotIn("pull_request_target", document.get("on", {}))
        job = document.get("jobs", {}).get("dco")
        self.assertIsInstance(job, dict)
        self.assertEqual(job.get("name"), "DCO sign-off")
        self.assertEqual(job.get("if"), "${{ github.event_name == 'pull_request' }}")
        self.assertEqual(job.get("permissions"), {"contents": "read"})
        self.assertEqual(job.get("timeout-minutes"), 5)
        steps = job.get("steps")
        self.assertIsInstance(steps, list)
        self.assertEqual(len(steps), 2)
        checkout, check = steps
        self.assertEqual(checkout.get("uses"), CHECKOUT_ACTION)
        self.assertEqual(
            checkout.get("with"), {"fetch-depth": 0, "persist-credentials": False}
        )
        self.assertEqual(
            check.get("env"),
            {
                "HBCB_DCO_BASE_SHA": "${{ github.event.pull_request.base.sha }}",
                "HBCB_DCO_HEAD_SHA": "${{ github.event.pull_request.head.sha }}",
            },
        )
        self.assertEqual(
            check.get("run"),
            './scripts/dco-check "$HBCB_DCO_BASE_SHA" "$HBCB_DCO_HEAD_SHA"',
        )

    def test_release_tools_contain_no_network_or_remote_git_operations(self) -> None:
        scripts = [
            (ROOT / "scripts" / name).read_text(encoding="utf-8")
            for name in (
                "release-audit",
                "service-sbom",
                "release-artifacts",
                "release-publication-preflight",
            )
        ]
        combined = "\n".join(scripts)
        for forbidden in (
            "git push",
            "git fetch",
            "git pull",
            "pull_request_target",
            "requests.get(",
            "urlopen(",
            "shell=True",
        ):
            self.assertNotIn(forbidden, combined)

    def test_dependency_audit_is_scheduled_manual_read_only_and_report_only(self) -> None:
        self.assertFalse((ROOT / ".github" / "dependabot.yml").exists())
        path = ROOT / ".github" / "workflows" / "dependency-audit.yml"
        document = json.loads(path.read_text(encoding="utf-8"))
        triggers = document.get("on")
        self.assertIsInstance(triggers, dict)
        self.assertEqual(set(triggers), {"schedule", "workflow_dispatch"})
        schedule = triggers.get("schedule")
        self.assertIsInstance(schedule, list)
        self.assertEqual(len(schedule), 1)
        self.assertRegex(str(schedule[0].get("cron")), r"^[0-9*,/-]+(?: [0-9*,/-]+){4}$")
        self.assertEqual(document.get("permissions"), {"contents": "read"})

        audit = document.get("jobs", {}).get("audit")
        self.assertIsInstance(audit, dict)
        self.assertEqual(audit.get("timeout-minutes"), 180)
        steps = audit.get("steps")
        self.assertIsInstance(steps, list)
        run_text = "\n".join(
            str(step.get("run", "")) for step in steps if isinstance(step, dict)
        )
        uses = [
            str(step.get("uses", "")) for step in steps if isinstance(step, dict)
        ]
        self.assertIn("./scripts/dependency-scan", run_text)
        self.assertIn("GITHUB_STEP_SUMMARY", run_text)
        self.assertTrue(
            any(item.startswith("actions/upload-artifact@") for item in uses)
        )
        upload = next(
            step
            for step in steps
            if isinstance(step, dict)
            and str(step.get("uses", "")).startswith("actions/upload-artifact@")
        )
        self.assertEqual(upload.get("uses"), UPLOAD_ARTIFACT_ACTION)
        self.assertEqual(upload.get("with", {}).get("if-no-files-found"), "error")
        self.assertEqual(upload.get("with", {}).get("retention-days"), 7)
        combined = json.dumps(document, sort_keys=True)
        for forbidden in (
            "pull_request_target",
            "contents: write",
            "issues: write",
            "pull-requests: write",
            "git push",
            "gh issue",
            "gh pr",
        ):
            self.assertNotIn(forbidden, combined)

    def test_release_candidate_retains_uniquely_named_checksum_evidence(self) -> None:
        path = ROOT / ".github" / "workflows" / "release-candidate.yml"
        document = json.loads(path.read_text(encoding="utf-8"))
        job = document.get("jobs", {}).get("release-check")
        self.assertIsInstance(job, dict)
        steps = job.get("steps")
        self.assertIsInstance(steps, list)
        gate = next(
            step
            for step in steps
            if isinstance(step, dict) and step.get("run") == "make release-check"
        )
        run_id = "github-${{ github.run_id }}-${{ github.run_attempt }}"
        self.assertEqual(gate.get("env", {}).get("HBCB_RELEASE_RUN_ID"), run_id)
        upload = next(
            step
            for step in steps
            if isinstance(step, dict)
            and str(step.get("uses", "")).startswith("actions/upload-artifact@")
        )
        self.assertEqual(upload.get("uses"), UPLOAD_ARTIFACT_ACTION)
        self.assertEqual(upload.get("with", {}).get("if-no-files-found"), "error")
        self.assertEqual(upload.get("with", {}).get("retention-days"), 7)
        self.assertEqual(
            upload.get("with", {}).get("path"),
            "build/release-check/" + run_id,
        )
        self.assertIn("${{ github.run_id }}", upload.get("with", {}).get("name", ""))
        self.assertIn("${{ github.run_attempt }}", upload.get("with", {}).get("name", ""))
        self.assertEqual(upload.get("with", {}).get("compression-level"), 0)

        wrapper = (ROOT / "scripts" / "release-check").read_text(encoding="utf-8")
        for required in (
            "fetch-corresponding-source",
            "HBCB_BLENDER_SOURCE_ARCHIVE",
            "--corresponding-source-dir",
            "oci-identity-and-project-blender-source",
        ):
            self.assertIn(required, wrapper)

    def test_publication_upload_preserves_checksum_sample_paths(self) -> None:
        process = (ROOT / "docs" / "release-process.md").read_text(encoding="utf-8")
        self.assertIn('for asset in "$RELEASE_DIR"/*', process)
        self.assertIn('gh release download "v${RC_VERSION}"', process)
        self.assertIn(
            'headless-blender-character-builder-${RC_VERSION}-sample.tar.gz',
            process,
        )
        self.assertIn('tar -xzf \\', process)
        self.assertNotIn('find "$RELEASE_DIR" -type f', process)

    def test_publication_authenticates_before_any_remote_mutation(self) -> None:
        process = (ROOT / "docs" / "release-process.md").read_text(encoding="utf-8")
        login = '"$HBCB_PUBLISH_DOCKER" login ghcr.io -u "$GH_OWNER" --password-stdin'
        first_image_push = '"$HBCB_PUBLISH_DOCKER" push "ghcr.io/${GH_OWNER}/headless-blender-character-builder:${RC_VERSION}"'
        tag_push = 'git push origin "v${RC_VERSION}"'
        self.assertEqual(process.count(login), 1)
        self.assertIn(first_image_push, process)
        self.assertIn(tag_push, process)
        self.assertIn('export HBCB_PUBLISH_DOCKER=${DOCKER:-docker}', process)
        self.assertIn('command -v "$HBCB_PUBLISH_DOCKER"', process)
        publication_start = process.index("```sh\n(\nset -eu", process.index("Exact registry"))
        self.assertLess(publication_start, process.index("command -v gh", publication_start))
        self.assertLess(process.index(login), process.index(first_image_push))
        self.assertLess(process.index(first_image_push), process.index(tag_push))
        self.assertIn("public_oci_ready: false", process)
        self.assertIn("Public OCI publication remains blocked", process)
        readiness = 'scripts/release-publication-preflight \\'
        self.assertIn(readiness, process)
        self.assertLess(process.index(readiness), process.index(login))
        self.assertLess(process.index(readiness), process.index(first_image_push))
        tag_end = process.index(
            '"ghcr.io/${GH_OWNER}/headless-blender-character-builder-worker:${RC_VERSION}"',
            process.index('"$HBCB_PUBLISH_DOCKER" tag "$WORKER_IMAGE_ID"'),
        )
        immediate_preflight = process.index(
            'publication_preflight --registry-owner "$GH_OWNER"', tag_end
        )
        self.assertLess(immediate_preflight, process.index(first_image_push))
        self.assertIn("published_digest: null", process)
        finalizer = "--finalize-output-dir \"$PUBLISHED_RELEASE_DIR\""
        final_digest_check = (
            'publication_preflight --require-published-digests --registry-owner "$GH_OWNER"'
        )
        self.assertIn(finalizer, process)
        self.assertIn(final_digest_check, process)
        last_image_push = process.index(
            '"$HBCB_PUBLISH_DOCKER" push "ghcr.io/${GH_OWNER}/headless-blender-character-builder-worker:${RC_VERSION}"'
        )
        self.assertLess(last_image_push, process.index(finalizer))
        self.assertLess(process.index(finalizer), process.index(final_digest_check))
        self.assertLess(process.index(final_digest_check), process.index(tag_push))
        self.assertIn("registry-qualified GHCR tag", process)
        self.assertIn("raw manifest whose config digest matches", process)
        self.assertIn("RepoTags", process)
        self.assertIn("RepoDigests", process)
        self.assertIn('gh release delete "v${RC_VERSION}" --yes', process)
        self.assertIn('git push origin --delete "v${RC_VERSION}"', process)
        self.assertIn("exact version ID", process)
        for role, variable in (
            ("builder", "BUILDER_IMAGE_ID"),
            ("api", "API_IMAGE_ID"),
            ("worker", "WORKER_IMAGE_ID"),
        ):
            self.assertIn(
                f"{variable}=$(publication_preflight --print-image-id {role})",
                process,
            )
            self.assertIn(f'"$HBCB_PUBLISH_DOCKER" tag "${variable}"', process)
        self.assertIn("fail-fast but non-atomic operator transaction", process)

    def test_publication_runbook_is_fail_closed_and_resumable(self) -> None:
        process = (ROOT / "docs" / "release-process.md").read_text(
            encoding="utf-8"
        )
        self.assertIn('"$HBCB_PUBLISH_DOCKER" buildx version', process)
        self.assertIn('test "$(gh api user --jq .login)" = "$GH_OWNER"', process)
        self.assertIn("HBCB_CANONICAL_REPOSITORY=joseph-robert-f/", process)
        self.assertIn('git remote get-url --push origin', process)
        self.assertIn("SIGNING_PROBE_TAG_OBJECT", process)
        self.assertIn("SIGNING_PROBE_INTENT=1", process)
        self.assertIn("assert_remote_release_slot()", process)
        self.assertIn("assert_package_private()", process)
        self.assertIn("/user/packages?package_type=container&per_page=100", process)
        self.assertIn('item.get("visibility") != "private"', process)
        for package in (
            "headless-blender-character-builder",
            "headless-blender-character-builder-api",
            "headless-blender-character-builder-worker",
        ):
            check = f"assert_remote_release_slot {package}"
            push = (
                '"$HBCB_PUBLISH_DOCKER" push '
                f'"ghcr.io/${{GH_OWNER}}/{package}:${{RC_VERSION}}"'
            )
            private = f"assert_package_private {package}"
            self.assertLess(process.index(check, process.index("# Push private")), process.index(push))
            self.assertLess(process.index(push), process.index(private, process.index(push)))
        self.assertIn(
            'cmp -- "$RELEASE_DIR/SHA256SUMS" "$RELEASE_REVIEW_DIR/SHA256SUMS"',
            process,
        )
        self.assertIn("downloaded draft asset set differs from the local bundle", process)
        self.assertIn("downloaded review tree contains missing or extra paths", process)
        self.assertIn("fresh disposable VM with an empty Docker daemon", process)
        self.assertIn("HBCB_CLEAN_REGISTRY_VERIFY: PASS", process)
        self.assertIn("verify_private_remote_role()", process)
        self.assertIn("verify_public_remote_role()", process)
        self.assertIn('existing_image_ids=$("$HBCB_VERIFY_DOCKER" image ls', process)
        self.assertNotIn("clean verifier already contains a candidate image", process)
        self.assertIn("HBCB_PUBLIC_VISIBILITY_COMMIT: PASS", process)
        self.assertIn('test -d "$local_asset" && continue', process)
        self.assertIn("local_names=sorted(", process)
        builder_public = (
            "verify_public_remote_role builder "
            "headless-blender-character-builder"
        )
        api_private = (
            "verify_private_remote_role api "
            "headless-blender-character-builder-api"
        )
        api_public = (
            "verify_public_remote_role api "
            "headless-blender-character-builder-api"
        )
        worker_private = (
            "verify_private_remote_role worker "
            "headless-blender-character-builder-worker"
        )
        final_visibility = process.index("# Before changing the API package:")
        self.assertLess(
            process.index(builder_public, final_visibility),
            process.index(api_private, final_visibility),
        )
        worker_visibility = process.index("# Before changing the worker package:")
        self.assertLess(
            process.index(builder_public, worker_visibility),
            process.index(api_public, worker_visibility),
        )
        self.assertLess(
            process.index(api_public, worker_visibility),
            process.index(worker_private, worker_visibility),
        )
        self.assertIn("--draft=false --repo joseph-robert-f/", process)
        self.assertIn("release.lock.env", process)
        self.assertIn("PUBLISHED_RELEASE_DIR=\"${ORIGINAL_RELEASE_DIR}.published\"", process)
        self.assertIn(".failed-<random>", process)
        self.assertIn("--json assets,isDraft,tagName,url", process)
        recovery = process.index("Use this bounded recovery inventory")
        self.assertNotIn("imagetools inspect --raw \"$reference\" |", process[recovery:])
        self.assertIn('> "$manifest"', process[recovery:])
        self.assertIn('recovery_docker_config="$recovery_inventory/docker-config"', process[recovery:])
        self.assertIn('export DOCKER_CONFIG=$recovery_docker_config', process[recovery:])
        self.assertIn('unset CR_PAT', process[recovery:])
        self.assertIn('--config "$release_curl_config"', process[recovery:])
        self.assertNotIn('Authorization: Bearer $(gh auth token)', process[recovery:])
        self.assertIn('chmod 0600 "$release_curl_config"', process[recovery:])
        token_writer = (
            'sys.stdout.write(f"header = \\"Authorization: Bearer '
            '{token}\\"\\n")'
        )
        self.assertIn(token_writer, process[recovery:])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exec("import sys\ntoken='abc'\n" + token_writer, {})
        self.assertEqual(output.getvalue(), 'header = "Authorization: Bearer abc"\n')
        self.assertIn("normal tracked-file index flags", process)


if __name__ == "__main__":
    unittest.main()
