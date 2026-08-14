"""Drift tripwire: the publication-policy validation chain is copy-pasted
across three standalone scripts (scripts/fetch-corresponding-source,
scripts/release-artifacts, scripts/release-publication-preflight). Nothing
enforces that a future schema edit lands in all three, so this test loads
each script's policy loader and asserts they agree - all accept or all
reject - on one shared table of policy fixtures. A failure here means the
three loaders have desynchronized and a future schema change silently made
one gate stricter or looser than the others.
"""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from typing import Mapping

from tests.release.support import ROOT, load_script


fetch = load_script("fetch_corresponding_source_under_test", "fetch-corresponding-source")
artifacts = load_script("release_artifacts_policy_under_test", "release-artifacts")
preflight = load_script("release_preflight_policy_under_test", "release-publication-preflight")


BLENDER_SECTION = {
    "archive": "blender-4.5.12.tar.xz",
    "bytes": 85105056,
    "license": "GPL-3.0-or-later",
    "official_md5": "5696670e8b7a8d8ffbd33824a140c1c3",
    "sha256": "9cb86825c95e4f0a33bfd41eb574426f2f69aa6c310497e289fdb54cc6482f1b",
    "source_url": "https://download.blender.org/source/blender-4.5.12.tar.xz",
    "version": "4.5.12",
}

BLOCKED_PUBLICATION = {
    "delivery_method": "co-published-release-assets",
    "public_oci_ready": False,
    "publication_gate": "blocked-pending-complete-copyleft-source-review",
    "retention": "retain-with-each-public-image-version-for-its-public-lifetime",
    "scope": "project-and-blender-source-only",
}

REVIEWED_PUBLICATION = {
    "delivery_method": "co-published-release-assets",
    "public_oci_ready": True,
    "publication_gate": "reviewed-complete-source-delivery",
    "retention": "retain-with-each-public-image-version-for-its-public-lifetime",
    "scope": "complete-reviewed-image-source",
}


def document(publication: Mapping[str, object]) -> dict[str, object]:
    return {
        "blender": copy.deepcopy(BLENDER_SECTION),
        "format": "hbcb-corresponding-source-policy/v1",
        "publication": dict(publication),
    }


def canonical_bytes(payload: Mapping[str, object]) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def load_via_fetch(payload: bytes, temporary: Path) -> bool:
    path = temporary / "policy.json"
    path.write_bytes(payload)
    try:
        fetch.load_policy(path)
        return True
    except fetch.SourceFailure:
        return False


def load_via_release_artifacts(payload: bytes) -> bool:
    try:
        artifacts._load_corresponding_source_policy(payload)
        return True
    except artifacts.PackagingFailure:
        return False


def load_via_preflight(payload: bytes) -> bool:
    try:
        preflight._source_policy(payload)
        return True
    except preflight.PreflightFailure:
        return False


class PublicationPolicyConsistencyTests(unittest.TestCase):
    def assert_all_loaders_agree(self, payload: bytes, expected: bool, label: str) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            results = {
                "fetch-corresponding-source": load_via_fetch(payload, Path(temporary)),
                "release-artifacts": load_via_release_artifacts(payload),
                "release-publication-preflight": load_via_preflight(payload),
            }
        self.assertEqual(
            results,
            {name: expected for name in results},
            "%s: loaders disagree: %r" % (label, results),
        )

    def test_real_tracked_policy_file_is_accepted_by_all_three_loaders(self) -> None:
        payload = (ROOT / "release" / "corresponding-source-policy.json").read_bytes()
        self.assert_all_loaders_agree(payload, True, "real tracked policy file")

    def test_gate_scope_oci_ready_combinations_agree(self) -> None:
        gates = (
            "blocked-pending-complete-copyleft-source-review",
            "reviewed-complete-source-delivery",
        )
        scopes = (
            "project-and-blender-source-only",
            "complete-reviewed-image-source",
        )
        for gate in gates:
            for scope in scopes:
                for oci_ready in (False, True):
                    publication = dict(BLOCKED_PUBLICATION)
                    publication["publication_gate"] = gate
                    publication["scope"] = scope
                    publication["public_oci_ready"] = oci_ready
                    consistent = (
                        oci_ready == (gate == "reviewed-complete-source-delivery")
                        and oci_ready == (scope == "complete-reviewed-image-source")
                    )
                    with self.subTest(gate=gate, scope=scope, oci_ready=oci_ready):
                        self.assert_all_loaders_agree(
                            canonical_bytes(document(publication)),
                            consistent,
                            "gate=%s scope=%s oci_ready=%s" % (gate, scope, oci_ready),
                        )

    def test_wrong_delivery_method_is_rejected_by_all_three_loaders(self) -> None:
        publication = dict(BLOCKED_PUBLICATION)
        publication["delivery_method"] = "direct-release-assets"
        self.assert_all_loaders_agree(
            canonical_bytes(document(publication)), False, "wrong delivery_method"
        )

    def test_wrong_retention_is_rejected_by_all_three_loaders(self) -> None:
        publication = dict(BLOCKED_PUBLICATION)
        publication["retention"] = "retain-indefinitely"
        self.assert_all_loaders_agree(
            canonical_bytes(document(publication)), False, "wrong retention"
        )

    def test_extra_publication_key_is_rejected_by_all_three_loaders(self) -> None:
        publication = dict(BLOCKED_PUBLICATION)
        publication["extra_field"] = "unexpected"
        self.assert_all_loaders_agree(
            canonical_bytes(document(publication)), False, "extra publication key"
        )

    def test_each_missing_publication_key_is_rejected_by_all_three_loaders(self) -> None:
        for key in sorted(BLOCKED_PUBLICATION):
            publication = dict(BLOCKED_PUBLICATION)
            del publication[key]
            with self.subTest(missing=key):
                self.assert_all_loaders_agree(
                    canonical_bytes(document(publication)), False, "missing " + key
                )

    def test_non_bool_public_oci_ready_is_rejected_by_all_three_loaders(self) -> None:
        for value in (1, 0, "true", None, 1.0):
            publication = dict(BLOCKED_PUBLICATION)
            publication["public_oci_ready"] = value
            with self.subTest(value=value):
                self.assert_all_loaders_agree(
                    canonical_bytes(document(publication)),
                    False,
                    "non-bool public_oci_ready=%r" % (value,),
                )

    def test_unknown_publication_gate_is_rejected_by_all_three_loaders(self) -> None:
        publication = dict(BLOCKED_PUBLICATION)
        publication["publication_gate"] = "unreviewed-partial-delivery"
        self.assert_all_loaders_agree(
            canonical_bytes(document(publication)), False, "unknown publication_gate"
        )

    def test_unknown_scope_is_rejected_by_all_three_loaders(self) -> None:
        publication = dict(BLOCKED_PUBLICATION)
        publication["scope"] = "everything-including-secrets"
        self.assert_all_loaders_agree(
            canonical_bytes(document(publication)), False, "unknown scope"
        )

    def test_both_valid_publications_are_accepted_by_all_three_loaders(self) -> None:
        for label, publication in (
            ("blocked", BLOCKED_PUBLICATION),
            ("reviewed", REVIEWED_PUBLICATION),
        ):
            with self.subTest(publication=label):
                self.assert_all_loaders_agree(
                    canonical_bytes(document(publication)), True, label + " publication"
                )


if __name__ == "__main__":
    unittest.main()
