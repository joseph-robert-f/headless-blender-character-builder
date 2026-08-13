from __future__ import annotations

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
            for name in ("release-audit", "service-sbom", "release-artifacts")
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
        login = 'docker login ghcr.io -u "$GH_OWNER" --password-stdin'
        first_image_push = 'docker push "ghcr.io/${GH_OWNER}/headless-blender-character-builder:${RC_VERSION}"'
        tag_push = 'git push origin "v${RC_VERSION}"'
        self.assertEqual(process.count(login), 1)
        self.assertIn(first_image_push, process)
        self.assertIn(tag_push, process)
        publication_start = process.index("```sh\n(\nset -eu", process.index("Exact registry"))
        self.assertLess(publication_start, process.index("command -v gh", publication_start))
        self.assertLess(process.index(login), process.index(first_image_push))
        self.assertLess(process.index(first_image_push), process.index(tag_push))
        self.assertIn("public_oci_ready: false", process)
        self.assertIn("Public OCI publication remains blocked", process)
        readiness = 'inventory.get("public_oci_ready") is not True'
        self.assertIn(readiness, process)
        self.assertLess(process.index(readiness), process.index(first_image_push))
        self.assertIn("fail-fast but non-atomic operator transaction", process)


if __name__ == "__main__":
    unittest.main()
