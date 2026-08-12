from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.release.support import ROOT


class DcoCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repository = Path(self.temporary.name) / "repository"
        (self.repository / "scripts").mkdir(parents=True)
        self.script = self.repository / "scripts" / "dco-check"
        shutil.copyfile(ROOT / "scripts" / "dco-check", self.script)
        self.script.chmod(0o755)
        self._git("init", "-q")
        self._git("config", "user.name", "Release Test")
        self._git("config", "user.email", "release-test@example.invalid")
        self.branch = self._git("symbolic-ref", "--short", "HEAD").decode().strip()
        self.counter = 0
        self.base = self._commit("base without sign-off")

    def _git(
        self,
        *arguments: str,
        payload: bytes | None = None,
        identities: dict[str, str] | None = None,
    ) -> bytes:
        environment = dict(os.environ, LC_ALL="C", GIT_TERMINAL_PROMPT="0")
        if identities:
            environment.update(identities)
        completed = subprocess.run(
            [
                "git",
                "-c",
                "commit.gpgsign=false",
                "-C",
                str(self.repository),
                *arguments,
            ],
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env=environment,
            timeout=10,
        )
        if completed.returncode != 0:
            self.fail(completed.stderr.decode("utf-8", "replace"))
        return completed.stdout

    def _commit(
        self,
        message: str,
        *,
        author: tuple[str, str] = ("Release Test", "release-test@example.invalid"),
        committer: tuple[str, str] = ("Release Test", "release-test@example.invalid"),
    ) -> str:
        self.counter += 1
        (self.repository / "payload.txt").write_text(str(self.counter), encoding="utf-8")
        self._git("add", "payload.txt")
        identities = {
            "GIT_AUTHOR_NAME": author[0],
            "GIT_AUTHOR_EMAIL": author[1],
            "GIT_COMMITTER_NAME": committer[0],
            "GIT_COMMITTER_EMAIL": committer[1],
        }
        self._git("commit", "-q", "-F", "-", payload=message.encode(), identities=identities)
        return self._git("rev-parse", "HEAD").decode("ascii").strip()

    def _run(self, base: str, head: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.script), base, head],
            cwd=self.repository,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=10,
            env=dict(os.environ, LC_ALL="C", GIT_TERMINAL_PROMPT="0"),
        )

    def test_repository_script_is_executable_and_help_is_bounded(self) -> None:
        source = ROOT / "scripts" / "dco-check"
        self.assertEqual(stat.S_IMODE(source.stat().st_mode), 0o755)
        completed = subprocess.run(
            [str(source)],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stdout, "")
        self.assertEqual(completed.stderr, "usage: scripts/dco-check BASE_SHA HEAD_SHA\n")

    def test_exact_author_or_committer_identity_passes(self) -> None:
        author_head = self._commit(
            "author sign-off\n\nSigned-off-by: Release Test <release-test@example.invalid>\n"
        )
        author_result = self._run(self.base, author_head)
        self.assertEqual(author_result.returncode, 0, author_result.stderr)
        self.assertEqual(author_result.stdout, "DCO_CHECK: PASS (1 commits)\n")

        committer_head = self._commit(
            "committer sign-off\n\nSigned-off-by: Committer Person <committer@example.invalid>\n",
            author=("Author Person", "author@example.invalid"),
            committer=("Committer Person", "committer@example.invalid"),
        )
        committer_result = self._run(author_head, committer_head)
        self.assertEqual(committer_result.returncode, 0, committer_result.stderr)
        self.assertEqual(committer_result.stdout, "DCO_CHECK: PASS (1 commits)\n")

    def test_every_unique_commit_is_checked_and_failure_does_not_echo_content(self) -> None:
        signed = self._commit(
            "valid\n\nSigned-off-by: Release Test <release-test@example.invalid>\n"
        )
        unsigned = self._commit("PRIVATE-COMMIT-BODY-WITHOUT-SIGNOFF")
        completed = self._run(self.base, unsigned)
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(completed.stdout, "")
        self.assertIn("DCO_CHECK: FAIL[missing_signoff]", completed.stderr)
        self.assertIn("commit=" + unsigned[:12], completed.stderr)
        self.assertNotIn(signed, completed.stderr)
        self.assertNotIn("PRIVATE-COMMIT", completed.stderr)
        self.assertNotIn("release-test@example.invalid", completed.stderr)

    def test_body_line_and_mismatched_identity_do_not_satisfy_policy(self) -> None:
        body_only = self._commit(
            "body-only\n\nSigned-off-by: Release Test <release-test@example.invalid>\n\n"
            "This paragraph is not a trailer.\n"
        )
        body_result = self._run(self.base, body_only)
        self.assertEqual(body_result.returncode, 1)
        self.assertIn("FAIL[missing_signoff]", body_result.stderr)

        mismatch = self._commit(
            "mismatch\n\nSigned-off-by: Private Person <private@example.invalid>\n"
        )
        mismatch_result = self._run(body_only, mismatch)
        self.assertEqual(mismatch_result.returncode, 1)
        self.assertIn("FAIL[identity_mismatch]", mismatch_result.stderr)
        self.assertNotIn("Private Person", mismatch_result.stderr)
        self.assertNotIn("private@example.invalid", mismatch_result.stderr)

    def test_diverged_base_checks_only_commits_unique_to_head(self) -> None:
        self._git("checkout", "-qb", "feature")
        head = self._commit(
            "feature\n\nSigned-off-by: Release Test <release-test@example.invalid>\n"
        )
        self._git("checkout", "-q", self.branch)
        advanced_base = self._commit("new base commit need not be part of the pull request")
        completed = self._run(advanced_base, head)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "DCO_CHECK: PASS (1 commits)\n")

    def test_revisions_are_exact_and_missing_objects_fail_without_git_output(self) -> None:
        for revision, code in (
            ("-" + "a" * 39, "invalid_revision"),
            ("A" * 40, "invalid_revision"),
            ("0" * 40, "missing_commit"),
        ):
            with self.subTest(code=code):
                completed = self._run(self.base, revision)
                self.assertEqual(completed.returncode, 1)
                self.assertIn(f"DCO_CHECK: FAIL[{code}]", completed.stderr)
                self.assertNotIn(revision, completed.stderr)
                self.assertNotIn("fatal:", completed.stderr.lower())


if __name__ == "__main__":
    unittest.main()
