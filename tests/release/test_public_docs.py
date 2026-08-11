from __future__ import annotations

import re
import stat
import subprocess
import unittest
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[2]
LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")


def markdown_anchors(path: Path) -> set[str]:
    anchors: set[str] = set()
    counts: dict[str, int] = {}
    fenced = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if fenced:
            continue
        match = HEADING.match(line)
        if match is None:
            continue
        title = re.sub(r"<[^>]+>", "", match.group(1))
        title = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", title)
        title = title.replace("`", "").replace("*", "")
        base = re.sub(r"[^\w\- ]", "", title.lower())
        base = re.sub(r"\s+", "-", base.strip())
        suffix = counts.get(base, 0)
        counts[base] = suffix + 1
        anchors.add(base if suffix == 0 else f"{base}-{suffix}")
    return anchors


class PublicDocumentationTests(unittest.TestCase):
    def test_public_shell_examples_are_syntax_valid(self) -> None:
        documents = (
            "README.md",
            "CONTRIBUTING.md",
            "docs/installation.md",
            "docs/configuration.md",
            "docs/troubleshooting.md",
            "docs/character-spec.md",
            "docs/api.md",
            "examples/README.md",
        )
        snippets: list[str] = []
        for relative in documents:
            inside = False
            for line in (ROOT / relative).read_text(encoding="utf-8").splitlines():
                if line == "```sh":
                    inside = True
                    continue
                if inside and line == "```":
                    inside = False
                    snippets.append("")
                    continue
                if inside:
                    snippets.append(line)
            self.assertFalse(inside, f"unterminated shell block: {relative}")
        checked = subprocess.run(
            ("sh", "-n"),
            input="\n".join(snippets) + "\n",
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(checked.returncode, 0, checked.stdout)

    def test_beginner_surfaces_are_present_and_connected(self) -> None:
        required = (
            "docs/installation.md",
            "docs/configuration.md",
            "docs/troubleshooting.md",
            "docs/character-spec.md",
            "docs/api.md",
            "examples/README.md",
            "scripts/doctor",
        )
        for relative in required:
            self.assertTrue((ROOT / relative).is_file(), relative)
        doctor_mode = stat.S_IMODE((ROOT / "scripts" / "doctor").stat().st_mode)
        self.assertEqual(doctor_mode & 0o111, 0o111)
        self.assertEqual(doctor_mode & 0o022, 0)

        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        index = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
        for link in (
            "docs/installation.md",
            "docs/configuration.md",
            "docs/troubleshooting.md",
            "docs/character-spec.md",
            "docs/api.md",
            "examples/README.md",
        ):
            self.assertIn(link, readme, link)
        for link in (
            "installation.md",
            "configuration.md",
            "troubleshooting.md",
            "character-spec.md",
            "api.md",
            "../examples/README.md",
        ):
            self.assertIn(link, index, link)
        self.assertIn("./scripts/doctor", readme)
        self.assertIn("make build", readme)
        self.assertIn("make verify", readme)
        self.assertIn("OUTPUT_NAME=", readme)
        self.assertIn("No project package is published on PyPI", readme)

        installation = (ROOT / "docs" / "installation.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("no project-published PyPI package", installation)

        progress = (ROOT / "docs" / "progress.md").read_text(encoding="utf-8")
        self.assertIn("authenticates the historical G9 index only", progress)
        self.assertIn("HBCB_RELEASE_RUN_ID", progress)

    def test_network_and_deployment_claims_are_mode_specific(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        architecture = (ROOT / "docs" / "architecture.md").read_text(
            encoding="utf-8"
        )
        threat_model = (ROOT / "docs" / "threat-model.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("networking disabled", readme.lower())
        for text in (architecture, threat_model):
            self.assertIn("--network none", text)
        self.assertIn("shares", readme.lower())
        self.assertRegex(readme.lower(), r"network\s+namespace")
        self.assertIn("shares", architecture.lower())
        self.assertRegex(architecture.lower(), r"network\s+namespace")
        self.assertIn("internal-only", threat_model.lower())

        deployment = (ROOT / "docs" / "deployment.md").read_text(encoding="utf-8")
        self.assertIn("## Availability", deployment)
        self.assertIn("does **not** publish", deployment.lower())
        self.assertIn("not yet a copy-paste", deployment.lower())
        self.assertIn("placeholder", deployment.lower())
        self.assertNotIn("supported production reference", deployment.lower())

    def test_examples_and_contract_guide_do_not_overclaim_qa(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        examples = (ROOT / "examples" / "README.md").read_text(encoding="utf-8")
        self.assertIn("facet-bot.json", examples)
        self.assertIn("**Passes**", examples)
        self.assertIn("moss-hopper.json", examples)
        self.assertIn("**`needs_review`**", examples)
        self.assertIn("schema-valid", examples.lower().replace(" ", "-"))
        self.assertIn("not pre-verified", examples.lower())
        self.assertRegex(readme, r"OUTPUT_NAME=facet-bot(?:\s|$)")
        self.assertRegex(examples, r"OUTPUT_NAME=facet-bot-example(?:\s|$)")
        self.assertNotRegex(examples, r"OUTPUT_NAME=facet-bot(?:\s|$)")

        troubleshooting = (ROOT / "docs" / "troubleshooting.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("README quickstart uses `build/facet-bot`", troubleshooting)
        self.assertIn("`make demo` alias uses\n`build/demo`", troubleshooting)

        guide = (ROOT / "docs" / "character-spec.md").read_text(encoding="utf-8")
        for value in (
            "0.7–1.6",
            "0.7–1.4",
            "0.7–1.3",
            "antenna-pair",
            "swept-tail",
            "height_mm - base.height_mm >= 18",
            "BUILDER_VALIDATE: PASS",
        ):
            self.assertIn(value, guide, value)
        self.assertNotIn("unittest discover -s tests", guide)

    def test_api_and_environment_recovery_are_copyable_and_secret_aware(self) -> None:
        api = (ROOT / "docs" / "api.md").read_text(encoding="utf-8")
        for value in (
            "curl --fail-with-body",
            "/v1/builds",
            "/artifacts",
            "/cancel",
            "auth.header",
            'HBCB_POLL_ATTEMPT" -lt 300',
            "HBCB_POLL_DEADLINE",
            "--max-time 15",
            "stop before downloading artifacts",
            "unset HBCB_API_BASE",
        ):
            self.assertIn(value, api, value)
        self.assertNotIn('Bearer $HBCB_API_TOKEN', api)
        self.assertNotIn("while :", api)
        self.assertNotRegex(api, r"failed\|canceled\|needs_review\)\s+exit")

        troubleshooting = (ROOT / "docs" / "troubleshooting.md").read_text(
            encoding="utf-8"
        )
        configuration = (ROOT / "docs" / "configuration.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("restore the original", troubleshooting.lower())
        self.assertIn("irreversible", troubleshooting.lower())
        self.assertRegex(
            troubleshooting.lower(), r"provides no one-command\s+reset"
        )
        self.assertIn("active Docker context", troubleshooting)
        self.assertNotIn("access the network", troubleshooting)
        self.assertIn("matched set", configuration.lower())
        self.assertNotIn("rename it before generating", troubleshooting.lower())

    def test_vps_install_secrets_and_component_notices_are_consistent(self) -> None:
        deployment = (ROOT / "docs" / "deployment.md").read_text(encoding="utf-8")
        for value in (
            "Docker Compose 2.24.4 or newer",
            "/absolute/path/to/verified-source",
            "sudo cp -a",
            "no such published source package exists yet",
        ):
            self.assertIn(value, deployment, value)

        secrets = (ROOT / "deploy" / "vps" / "SECRETS.md").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("<random>", secrets)
        self.assertIn("same placeholder name must be replaced by the same value", secrets)
        self.assertIn("different placeholder names must receive independent values", secrets)
        for placeholder in (
            "<DB_ADMIN_PASSWORD_64_HEX>",
            "<DB_MIGRATOR_PASSWORD_64_HEX>",
            "<DB_API_PASSWORD_64_HEX>",
            "<DB_WORKER_PASSWORD_64_HEX>",
            "<DB_MAINTENANCE_PASSWORD_64_HEX>",
        ):
            self.assertGreaterEqual(secrets.count(placeholder), 3, placeholder)
        self.assertGreaterEqual(secrets.count("<REDIS_PASSWORD_64_HEX>"), 3)
        self.assertEqual(secrets.count("<REDIS_URL_FROM_TABLE>"), 4)
        self.assertNotRegex(
            secrets, r"[a-z][a-z0-9+.-]*://[^/@:\s]+:[^/@\s]+@"
        )

        notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        self.assertIn("local and VPS-reference state service", notices)
        self.assertIn("local and VPS-reference queue/coordination service", notices)
        self.assertIn("local compatibility fixture only", notices)

    def test_relative_markdown_heading_anchors_resolve(self) -> None:
        failures: list[str] = []
        cache: dict[Path, set[str]] = {}
        for document in sorted(ROOT.rglob("*.md")):
            if any(part in {".git", "build"} for part in document.parts):
                continue
            text = document.read_text(encoding="utf-8")
            for raw_target in LINK.findall(text):
                target = raw_target.strip().strip("<>")
                if "#" not in target or re.match(
                    r"^[a-z][a-z0-9+.-]*:", target, re.I
                ):
                    continue
                file_part, fragment = target.split("#", 1)
                if not fragment:
                    continue
                target_path = (
                    document
                    if not file_part
                    else (document.parent / unquote(file_part)).resolve()
                )
                if not target_path.is_file() or target_path.suffix.lower() != ".md":
                    failures.append(f"{document.relative_to(ROOT)} -> {raw_target}")
                    continue
                anchors = cache.setdefault(target_path, markdown_anchors(target_path))
                if unquote(fragment).lower() not in anchors:
                    failures.append(f"{document.relative_to(ROOT)} -> {raw_target}")
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
