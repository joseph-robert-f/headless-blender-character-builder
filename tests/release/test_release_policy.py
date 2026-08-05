from __future__ import annotations

import json
import re
import unittest
from typing import Iterator

from tests.release.support import ROOT


WORKFLOWS = (
    ROOT / ".github" / "workflows" / "ci.yml",
    ROOT / ".github" / "workflows" / "release-candidate.yml",
)
FULL_ACTION_SHA = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")


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
        for path in WORKFLOWS:
            with self.subTest(path=path.name):
                document = json.loads(path.read_text(encoding="utf-8"))
                self.assertIsInstance(document, dict)
                self.assertEqual(document.get("permissions"), {"contents": "read"})
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
                self.assertEqual(step.get("with", {}).get("persist-credentials"), False)

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

    def test_dependabot_targets_only_rewritable_dependency_surfaces(self) -> None:
        text = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
        self.assertIn("package-ecosystem: docker-compose", text)
        self.assertIn("dependency-name: postgres", text)
        self.assertIn("dependency-name: redis", text)
        self.assertNotIn("package-ecosystem: github-actions", text)


if __name__ == "__main__":
    unittest.main()
