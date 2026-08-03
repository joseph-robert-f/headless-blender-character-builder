"""Canonical encoding and hashing.

The manifest's reproducibility claims rest entirely on these functions, so the
edge cases around number spelling are tested explicitly rather than assumed.
"""

import json
import os
import tempfile
import unittest

from hbcb import canonical


class NormalisationTests(unittest.TestCase):
    def test_key_order_does_not_change_the_hash(self):
        first = {"b": 1, "a": {"d": 4, "c": 3}}
        second = {"a": {"c": 3, "d": 4}, "b": 1}
        self.assertEqual(canonical.sha256_of_obj(first), canonical.sha256_of_obj(second))

    def test_integral_floats_collapse_to_integers(self):
        self.assertEqual(canonical.canonical_json({"h": 95.0}), '{"h":95}')
        self.assertEqual(canonical.sha256_of_obj({"h": 95.0}), canonical.sha256_of_obj({"h": 95}))

    def test_negative_zero_matches_zero(self):
        self.assertEqual(canonical.sha256_of_obj(-0.0), canonical.sha256_of_obj(0.0))

    def test_booleans_are_not_treated_as_integers(self):
        self.assertEqual(canonical.canonical_json({"x": True}), '{"x":true}')
        self.assertNotEqual(canonical.sha256_of_obj(True), canonical.sha256_of_obj(1))

    def test_float_noise_below_the_rounding_threshold_is_absorbed(self):
        self.assertEqual(canonical.sha256_of_obj(1.2000000000001), canonical.sha256_of_obj(1.2))

    def test_genuinely_different_numbers_still_differ(self):
        self.assertNotEqual(canonical.sha256_of_obj(1.2), canonical.sha256_of_obj(1.3))

    def test_non_finite_numbers_are_refused(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    canonical.canonical_json({"x": value})

    def test_nested_structures_are_normalised(self):
        self.assertEqual(canonical.canonical_json({"a": [1.0, {"b": 2.0}]}), '{"a":[1,{"b":2}]}')

    def test_output_is_parseable_json(self):
        payload = {"a": [1, 2.5, "x"], "b": {"c": True, "d": None}}
        self.assertEqual(json.loads(canonical.canonical_json(payload)), payload)

    def test_unicode_is_preserved_not_escaped(self):
        self.assertEqual(canonical.canonical_json({"n": "café"}), '{"n":"café"}')


class FileHashTests(unittest.TestCase):
    def test_file_hash_matches_known_value(self):
        with tempfile.NamedTemporaryFile("wb", delete=False) as handle:
            handle.write(b"abc")
            path = handle.name
        try:
            self.assertEqual(
                canonical.sha256_of_file(path),
                "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            )
        finally:
            os.unlink(path)

    def test_chunking_does_not_change_the_hash(self):
        payload = os.urandom(300000)
        with tempfile.NamedTemporaryFile("wb", delete=False) as handle:
            handle.write(payload)
            path = handle.name
        try:
            self.assertEqual(
                canonical.sha256_of_file(path, chunk_size=7),
                canonical.sha256_of_file(path, chunk_size=1 << 20),
            )
        finally:
            os.unlink(path)


class WriteJsonTests(unittest.TestCase):
    def test_written_file_round_trips_and_ends_with_a_newline(self):
        payload = {"z": 1, "a": {"nested": [1, 2, 3]}}
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "out.json")
            canonical.write_json(path, payload)
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            self.assertTrue(text.endswith("\n"))
            self.assertEqual(json.loads(text), payload)


if __name__ == "__main__":
    unittest.main()
