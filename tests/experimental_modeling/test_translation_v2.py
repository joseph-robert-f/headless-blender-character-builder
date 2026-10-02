"""Offline, independent indexed-translation evidence and compatibility tests.

Expected semantics are hand-written in translated_golden.json. No production
canonicalizer, observer, or predicate is used as an expected-result oracle.
The production public entry points below are the subjects under test only.
Synthetic pipeline records do not claim Blender or end-to-end execution.
"""
import copy
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import random
import unittest
from unittest.mock import patch

from experimental_modeling.acceptance import check
from experimental_modeling.contracts import Policy
from experimental_modeling.requirements import RequirementSet
from experimental_modeling.verification import make_report, validate_saved_report

FIXTURES = Path(__file__).with_name("fixtures")
BASELINE = "db205966c49adb140cbffaa5bbb57caa84abd3e1"
V1_FIXTURE_SHA256 = "e91e26f4e3ffa8e35292f1520a30056f2fe88a0e3676bab0f9db7c0b7920b142"
GOLDEN = json.loads((FIXTURES / "translated_golden.json").read_text())


def canonical_sha256(value):
    """Independent serialization for frozen bytes, never a geometric oracle."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def policy_raw(delta=(.25, -.5, .125), tolerance=0., normal_tolerance=0.):
    return {"schema_version": 2, "parts": ["body"], "changed_parts": ["body"],
            "profile": "scene", "constraints": [{"kind": "translated", "part": "body",
            "data": {"delta": list(delta), "tolerance": tolerance,
                     "normal_tolerance_radians": normal_tolerance}}]}


def observations(model="tetrahedron", delta=(.25, -.5, .125)):
    previous = copy.deepcopy(GOLDEN["models"][model]["previous"])
    observed = copy.deepcopy(previous)
    p = observed["parts"]["body"]
    p["world_vertices"] = [[x + d for x, d in zip(v, delta)] for v in p["world_vertices"]]
    p["world_bounds"] = {label: [x + d for x, d in zip(row, delta)]
                         for label, row in p["world_bounds"].items()}
    for i, d in enumerate(delta):
        p["matrix_world"][i][3] += d
    p["transform_hash"] = canonical_sha256(p["matrix_world"])
    return observed, previous


def permute_faces(p, order):
    # Explicit row alignment, not canonicalization or production comparison.
    for key in ("face_indices", "face_material_indices", "face_world_corner_normals"):
        p[key] = [copy.deepcopy(p[key][i]) for i in order]


def rotate_corners(p, face, offset, align=True):
    indices = p["face_indices"][face]
    p["face_indices"][face] = indices[offset:] + indices[:offset]
    if align:
        normals = p["face_world_corner_normals"][face]
        p["face_world_corner_normals"][face] = normals[offset:] + normals[:offset]


def mutate_case(operation, observed, previous):
    p = observed["parts"]["body"]
    if operation == "none":
        pass
    elif operation == "permute_faces":
        permute_faces(p, list(reversed(range(len(p["face_indices"])))))
    elif operation in ("cycle_aligned", "cycle_without_normals"):
        for i in range(len(p["face_indices"])):
            rotate_corners(p, i, 1, align=operation == "cycle_aligned")
    elif operation == "permute_edges":
        p["edge_indices"] = [edge[::-1] for edge in reversed(p["edge_indices"])]
    elif operation == "wrong_delta":
        for vertex in p["world_vertices"]:
            vertex[0] += .25
    elif operation == "deform":
        p["world_vertices"][0][1] += .25
    elif operation == "reverse_face":
        p["face_indices"][0].reverse()
        p["face_world_corner_normals"][0].reverse()
    elif operation == "different_polygon":
        p["face_indices"][1] = [3, 5, 6]
        p["triangle_indices"][2] = [3, 5, 6]
        # An actual topology change must keep its own surface evidence coherent.
        p["edge_indices"] = [[0, 1], [1, 2], [2, 3], [3, 0], [3, 5], [5, 6], [6, 3]]
    elif operation in ("duplicate_drop", "duplicate_bucket"):
        for key in ("face_indices", "face_material_indices", "face_world_corner_normals"):
            if operation == "duplicate_drop":
                p[key][2] = copy.deepcopy(p[key][0])
            else:
                p[key].append(copy.deepcopy(p[key][0]))
    elif operation == "swap_assignments":
        p["face_material_indices"][0], p["face_material_indices"][2] = 1, 0
    elif operation == "palette":
        p["materials"][0]["roughness"] = .75
        p["material_hash"] = canonical_sha256(p["materials"])
    elif operation == "reverse_normal":
        p["face_world_corner_normals"][0][0] = [0., 0., 1.]
    elif operation == "edge_change":
        # A valid loose edge differs between meshes; all polygon boundaries
        # remain present. Omitting a required boundary is malformed evidence.
        p["edge_indices"].append([0, 4])
    elif operation == "edge_duplicate":
        p["edge_indices"].append(copy.deepcopy(p["edge_indices"][0]))
    elif operation == "reindex_vertices":
        # A coordinated 0<->1 relabeling preserves rendered geometry but violates
        # the bounded index contract. Its verdict is specified by hand.
        remap = {0: 1, 1: 0}
        for key in ("world_vertices", "local_vertices", "normals"):
            p[key][0], p[key][1] = p[key][1], p[key][0]
        for key in ("face_indices", "triangle_indices", "edge_indices"):
            p[key] = [[remap.get(i, i) for i in row] for row in p[key]]
    elif operation == "remap_palette":
        p["materials"].reverse()
        for key in ("face_material_indices", "triangle_material_indices"):
            p[key] = [1 - i for i in p[key]]
        p["material_hash"] = canonical_sha256(p["materials"])
    elif operation == "tessellate":
        p["face_indices"] = copy.deepcopy(p["triangle_indices"])
        p["face_material_indices"] = copy.deepcopy(p["triangle_material_indices"])
        p["face_world_corner_normals"] = copy.deepcopy(p["triangle_world_normals"])
        p["edge_indices"].append([0, 2])
    elif operation == "missing_evidence":
        del p["face_world_corner_normals"]
    elif operation == "missing_parent":
        previous = None
    else:
        raise AssertionError("Unknown test mutation: " + operation)
    return observed, previous


def report_for(policy, observed, previous, **result_changes):
    result = {"revision": "synthetic-v2", "parent": "synthetic-baseline",
              "status": "accepted", "parent_result_hash": "a" * 64,
              "provenance_verified": True, "source_files": {},
              "jobs": {stage: {"exit_code": 0} for stage in
                       ("author", "inspect", "roundtrip", "reopen")},
              "policy_hash": "b" * 64, "runtime_hash": "synthetic-no-blender",
              "execution_mode": "synthetic-offline",
              "security_boundary": "not-a-model-execution"}
    result.update(result_changes)
    return make_report(result, policy, observed, previous,
                       RequirementSet.parse({"schema_version": 1, "requirements": []}))


def row(report, id):
    return next(item for item in report["requirements"] if item["id"] == id)


class FrozenV1CompatibilityTests(unittest.TestCase):
    def test_literal_v1_reports_and_hashes_are_unchanged(self):
        path = FIXTURES / "translated_v1_reports.json"
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), V1_FIXTURE_SHA256)
        fixture = json.loads(path.read_text())
        self.assertEqual(fixture["baseline_commit"], BASELINE)
        self.assertTrue(fixture["provenance"]["captured_from_immutable_baseline_export"])
        self.assertEqual({c["name"] for c in fixture["cases"]}, {
            "accepted", "face-order-rejected", "deformed-rejected",
            "material-palette-rejected", "material-assignment-incorrect-pass",
            "normal-incorrect-pass"})
        for case in fixture["cases"]:
            with self.subTest(case=case["name"]):
                self.assertEqual(canonical_sha256(case["report"]), case["report_sha256"])
                current = make_report(case["result"], Policy.parse(case["policy"]),
                                      case["observation"], case["previous"],
                                      RequirementSet.parse(case["requirements"]))
                self.assertEqual(current, case["report"])
                if case["name"].endswith("-rejected"):
                    self.assertEqual(case["result"]["status"], "rejected")
                    self.assertEqual(current["build_status"], "rejected")
                    self.assertGreater(current["summary"]["fail"], 0)
                self.assertEqual(canonical_sha256(current), case["report_sha256"])
                validate_saved_report(case["report"], current)

    def test_known_legacy_incorrect_passes_are_not_semantic_goldens(self):
        fixture = json.loads((FIXTURES / "translated_v1_reports.json").read_text())
        incorrect = [c for c in fixture["cases"] if "incorrect-pass" in c["name"]]
        self.assertEqual(len(incorrect), 2)
        for case in incorrect:
            self.assertEqual(case["classification"], "legacy-compatibility-known-incorrect-pass")
            self.assertFalse(case["independent_surface_semantics"])
            self.assertTrue(case["report"]["machine_verified"])


class HandDerivedSemanticTests(unittest.TestCase):
    def assert_verdict(self, expected, policy, observed, previous):
        if expected == "unknown":
            with self.assertRaises(ValueError):
                check(policy, observed, previous)
        else:
            failures = check(policy, observed, previous)
            self.assertEqual(bool(failures), expected == "fail", failures)
        report = report_for(policy, observed, previous)
        self.assertEqual(report["schema_version"], 2)
        self.assertEqual(row(report, "policy-001")["status"], expected)
        self.assertEqual(row(report, "policy-overall")["status"], expected)
        self.assertEqual(report["machine_verified"], expected == "pass")
        return report

    def test_hand_derived_literal_cases(self):
        self.assertEqual(GOLDEN["baseline_commit"], BASELINE)
        self.assertEqual(len(GOLDEN["cases"]), 27)
        for case in GOLDEN["cases"]:
            with self.subTest(case=case["name"]):
                observed, previous = observations(case["model"], case["delta"])
                observed, previous = mutate_case(case["operation"], observed, previous)
                policy = Policy.parse(policy_raw(case["delta"], case["tolerance"],
                                                 case["normal_tolerance_radians"]))
                self.assert_verdict(case["expected"], policy, observed, previous)

    def test_hand_surface_ledger_matches_declared_observation(self):
        for model in GOLDEN["models"].values():
            p = model["previous"]["parts"]["body"]
            for index, surface in enumerate(model["surface_ledger"]):
                self.assertEqual(p["face_indices"][index], surface["oriented_cycle"])
                self.assertEqual(p["face_material_indices"][index], surface["material_index"])
                self.assertEqual(p["face_world_corner_normals"][index], surface["world_corner_normals"])

    def test_composed_metamorphic_transformations_seeds_zero_through_fifteen(self):
        for model in GOLDEN["models"]:
            for seed in range(16):
                with self.subTest(model=model, seed=seed):
                    rng = random.Random(seed)
                    delta = [rng.randrange(-8, 9) / 8 for _ in range(3)]
                    observed, previous = observations(model, delta)
                    p = observed["parts"]["body"]
                    order = list(range(len(p["face_indices"])))
                    rng.shuffle(order)
                    permute_faces(p, order)
                    for i, face in enumerate(p["face_indices"]):
                        rotate_corners(p, i, rng.randrange(len(face)))
                    rng.shuffle(p["edge_indices"])
                    for edge in p["edge_indices"]:
                        if rng.choice([False, True]):
                            edge.reverse()
                    self.assert_verdict("pass", Policy.parse(policy_raw(delta)), observed, previous)

    def test_protected_part_hash_components_remain_enforced(self):
        for component in ("geometry_hash", "transform_hash", "material_hash"):
            with self.subTest(component=component):
                observed, previous = observations()
                previous["parts"]["protected"] = copy.deepcopy(previous["parts"]["body"])
                observed["parts"]["protected"] = copy.deepcopy(previous["parts"]["protected"])
                protected = observed["parts"]["protected"]
                if component == "geometry_hash":
                    protected["world_vertices"][0][0] += .25
                    protected["local_vertices"][0][0] += .25
                    protected[component] = canonical_sha256(protected["world_vertices"])
                elif component == "transform_hash":
                    protected["matrix_world"][0][3] += .25
                    for vertex in protected["world_vertices"]:
                        vertex[0] += .25
                    protected[component] = canonical_sha256(protected["matrix_world"])
                else:
                    protected["materials"][0]["roughness"] = .75
                    protected[component] = canonical_sha256(protected["materials"])
                raw = policy_raw()
                raw["parts"].append("protected")
                policy = Policy.parse(raw)
                failures = check(policy, observed, previous)
                self.assertIn({"check": "unchanged", "part": "protected", "component": component}, failures)
                report = report_for(policy, observed, previous)
                self.assertFalse(report["machine_verified"])
                self.assertEqual(row(report, "preserved-protected")["status"], "fail")

    def test_palette_values_are_compared_even_if_palette_hash_is_stale(self):
        for roughness in (.75, math.nextafter(.5, 1.)):
            with self.subTest(roughness=roughness):
                observed, previous = observations()
                observed["parts"]["body"]["materials"][0]["roughness"] = roughness
                self.assert_verdict("fail", Policy.parse(policy_raw()), observed, previous)

    def test_removed_or_new_unscoped_parts_cannot_pass(self):
        observed, previous = observations()
        previous["parts"]["removed"] = copy.deepcopy(previous["parts"]["body"])
        self.assertTrue(check(Policy.parse(policy_raw()), observed, previous))
        observed, previous = observations()
        observed["parts"]["added"] = copy.deepcopy(observed["parts"]["body"])
        raw = policy_raw()
        raw["parts"].append("added")
        failures = check(Policy.parse(raw), observed, previous)
        self.assertTrue(failures)
        self.assertEqual(failures[0]["check"], "new_parts_outside_scope")
        self.assertFalse(report_for(Policy.parse(raw), observed, previous)["machine_verified"])


class ExactCoordinateBoundaryTests(unittest.TestCase):
    def verdict_with_residual(self, residual, tolerance):
        observed, previous = observations(delta=(0., 0., 0.))
        observed["parts"]["body"]["world_vertices"][0] = list(residual)
        return check(Policy.parse(policy_raw((0., 0., 0.), tolerance)), observed, previous)

    def test_zero_tolerance_accepts_identity_only(self):
        self.assertFalse(self.verdict_with_residual([0., 0., 0.], 0.))
        self.assertTrue(self.verdict_with_residual([2. ** -40, 0., 0.], 0.))

    def test_dyadic_below_equal_above_boundary(self):
        tolerance = .125
        for x, expected in [(0., False), (math.nextafter(tolerance, 0.), False),
                            (tolerance, False), (math.nextafter(tolerance, math.inf), True)]:
            with self.subTest(x=x):
                self.assertEqual(bool(self.verdict_with_residual([x, 0., 0.], tolerance)), expected)

    def test_exact_multiaxis_dyadic_boundary(self):
        # (3/32)^2 + (4/32)^2 == (5/32)^2 in exact rational arithmetic.
        for x, expected in [(math.nextafter(3 / 32, 0.), False), (3 / 32, False),
                            (math.nextafter(3 / 32, math.inf), True)]:
            with self.subTest(x=x):
                self.assertEqual(bool(self.verdict_with_residual([x, 4 / 32, 0.], 5 / 32)), expected)

    def test_math_dist_rounded_boundary_must_not_be_a_false_pass(self):
        residual, tolerance = [.075, .1, 0.], .125
        self.assertEqual(math.dist(residual, [0., 0., 0.]), tolerance)
        # This arithmetic establishes the fixture boundary independently. The
        # stored binary64 inputs are strictly outside, despite rounded distance.
        exact_squared = sum(Fraction(value) ** 2 for value in residual)
        self.assertGreater(exact_squared, Fraction(tolerance) ** 2)
        self.assertTrue(self.verdict_with_residual(residual, tolerance))

    def test_stored_binary64_translation_is_not_real_decimal_arithmetic(self):
        observed, previous = observations(delta=(0., 0., 0.))
        previous["parts"]["body"]["world_vertices"][0][0] = .1
        for current, old in zip(observed["parts"]["body"]["world_vertices"],
                                previous["parts"]["body"]["world_vertices"]):
            current[0] = old[0] + .2
        observed["parts"]["body"]["world_vertices"][0][0] = .3
        self.assertNotEqual(Fraction(.3) - Fraction(.1), Fraction(.2))
        self.assertTrue(check(Policy.parse(policy_raw((.2, 0., 0.), 0.)), observed, previous))


class Binary64NormalBoundaryTests(unittest.TestCase):
    def test_binary64_atan2_below_equal_above(self):
        # Analytical base normal is -Z. Cross magnitude is abs(y); dot is -z.
        # This checks the binary64 atan2 policy, not exact-real angular geometry.
        y, z = math.sin(.005), -math.cos(.005)
        self.assertEqual(math.hypot(0., y, z), 1.)
        boundary = math.atan2(abs(y), -z)
        for tolerance, expected_failure in [
                (math.nextafter(boundary, 0.), True), (boundary, False),
                (math.nextafter(boundary, math.inf), False)]:
            with self.subTest(tolerance=tolerance):
                observed, previous = observations()
                observed["parts"]["body"]["face_world_corner_normals"][0][0] = [0., y, z]
                failures = check(Policy.parse(policy_raw(normal_tolerance=tolerance)), observed, previous)
                self.assertEqual(bool(failures), expected_failure)

    def test_zero_normal_tolerance_and_direction_preservation(self):
        observed, previous = observations()
        self.assertFalse(check(Policy.parse(policy_raw()), observed, previous))
        observed["parts"]["body"]["face_world_corner_normals"][0][0] = [0., math.sin(1e-8), -math.cos(1e-8)]
        self.assertTrue(check(Policy.parse(policy_raw()), observed, previous))


class FailClosedEvidenceTests(unittest.TestCase):
    def assert_unknown(self, observed, previous):
        policy = Policy.parse(policy_raw())
        with self.assertRaises(ValueError):
            check(policy, observed, previous)
        report = report_for(policy, observed, previous)
        self.assertFalse(report["machine_verified"])
        self.assertEqual(row(report, "policy-001")["status"], "unknown")

    def test_required_evidence_missing_on_either_side_is_unknown(self):
        for side in ("candidate", "parent"):
            for field in ("world_vertices", "face_indices", "edge_indices", "materials",
                          "face_material_indices", "face_world_corner_normals"):
                with self.subTest(side=side, field=field):
                    observed, previous = observations()
                    target = observed if side == "candidate" else previous
                    del target["parts"]["body"][field]
                    self.assert_unknown(observed, previous)

    def test_malformed_shapes_and_boolean_indices_are_unknown(self):
        edits = [
            ("face_indices", [[True, 2, 1]]),
            ("face_indices", [[0., 2, 1]]),
            ("face_indices", [[0, 0, 1]]),
            ("face_indices", [[0, 1]]),
            ("face_indices", [[0, 1, 99]]),
            ("face_indices", [[-1, 2, 1]]),
            ("face_indices", None),
            ("edge_indices", [[0, True]]),
            ("edge_indices", [[0, 0]]),
            ("edge_indices", [[0, 1, 2]]),
            ("edge_indices", [[0, 99]]),
            ("edge_indices", None),
            ("face_material_indices", [True, 0, 1, 1]),
            ("face_material_indices", [2, 0, 1, 1]),
            ("face_material_indices", [0]),
            ("face_world_corner_normals", []),
            ("world_vertices", []),
            ("world_vertices", [[0., 0.]]),
            ("world_vertices", None),
            ("materials", []),
            ("materials", [{"roughness": .5}]),
        ]
        for side in ("candidate", "parent"):
            for field, value in edits:
                with self.subTest(side=side, field=field, value=value):
                    observed, previous = observations()
                    p = (observed if side == "candidate" else previous)["parts"]["body"]
                    if field == "face_indices" and isinstance(value, list):
                        # Retain aligned face/material/normal row counts so an
                        # invalid face index is the reason evidence is rejected.
                        p[field][0] = copy.deepcopy(value[0])
                        if len(value[0]) != len(p["face_world_corner_normals"][0]):
                            p["face_world_corner_normals"][0] = [[0., 0., -1.]] * len(value[0])
                    else:
                        p[field] = copy.deepcopy(value)
                    self.assert_unknown(observed, previous)

    def test_nonfinite_or_boolean_numeric_evidence_is_unknown(self):
        for side in ("candidate", "parent"):
            for invalid in (float("nan"), float("inf"), -float("inf"), True):
                for field in ("vertex", "normal", "material"):
                    with self.subTest(side=side, invalid=invalid, field=field):
                        observed, previous = observations()
                        p = (observed if side == "candidate" else previous)["parts"]["body"]
                        if field == "vertex":
                            p["world_vertices"][0][0] = invalid
                        elif field == "normal":
                            p["face_world_corner_normals"][0][0][0] = invalid
                        else:
                            p["materials"][0]["roughness"] = invalid
                        self.assert_unknown(observed, previous)

    def test_missing_polygon_boundary_edges_are_unknown_even_when_both_sides_match(self):
        for side in ("candidate", "parent", "both"):
            for replacement in ("empty", "missing-one"):
                with self.subTest(side=side, replacement=replacement):
                    observed, previous = observations()
                    targets = ([observed, previous] if side == "both" else
                               [observed if side == "candidate" else previous])
                    for target in targets:
                        p = target["parts"]["body"]
                        p["edge_indices"] = [] if replacement == "empty" else p["edge_indices"][:-1]
                    self.assert_unknown(observed, previous)

    def test_zero_and_nonunit_normals_are_unknown(self):
        for normal in ([0., 0., 0.], [0., 0., -2.], [0., 0.], None):
            with self.subTest(normal=normal):
                observed, previous = observations()
                observed["parts"]["body"]["face_world_corner_normals"][0][0] = normal
                self.assert_unknown(observed, previous)

    def test_v1_or_invalid_observation_version_cannot_masquerade_as_v2(self):
        for side in ("candidate", "parent"):
            for version in (1, True, 2., None, 3):
                with self.subTest(side=side, version=version):
                    observed, previous = observations()
                    (observed if side == "candidate" else previous)["schema_version"] = version
                    self.assert_unknown(observed, previous)

    def test_missing_parent_and_duplicate_oriented_cycles_are_unknown(self):
        observed, previous = observations()
        self.assert_unknown(observed, None)
        for side in ("candidate", "parent", "both"):
            observed, previous = observations()
            for target in ([observed, previous] if side == "both" else
                           [observed if side == "candidate" else previous]):
                p = target["parts"]["body"]
                for key in ("face_indices", "face_material_indices", "face_world_corner_normals"):
                    p[key].append(copy.deepcopy(p[key][0]))
                rotate_corners(p, len(p["face_indices"]) - 1, 1)
            with self.subTest(side=side):
                self.assert_unknown(observed, previous)

    def test_missing_inspection_or_parent_binding_blocks_machine_verification(self):
        observed, previous = observations()
        policy = Policy.parse(policy_raw())
        for changes in ({"parent_result_hash": None}, {"provenance_verified": False},
                        {"jobs": {}}, {"status": "needs_review"}):
            with self.subTest(changes=changes):
                self.assertFalse(report_for(policy, observed, previous, **changes)["machine_verified"])
        report = report_for(policy, None, previous)
        self.assertFalse(report["machine_verified"])
        self.assertEqual(row(report, "policy-001")["status"], "unknown")

    def test_invalid_or_absent_protected_hashes_cannot_compare_equal(self):
        missing = object()
        for component in ("geometry_hash", "transform_hash", "material_hash"):
            for invalid in (missing, None, "", 7, [], "a" * 63, "A" * 64):
                for side in ("candidate", "parent", "both"):
                    with self.subTest(component=component, invalid=repr(invalid), side=side):
                        observed, previous = observations()
                        previous["parts"]["protected"] = copy.deepcopy(previous["parts"]["body"])
                        observed["parts"]["protected"] = copy.deepcopy(previous["parts"]["protected"])
                        targets = ([observed, previous] if side == "both" else
                                   [observed if side == "candidate" else previous])
                        for target in targets:
                            if invalid is missing:
                                del target["parts"]["protected"][component]
                            else:
                                target["parts"]["protected"][component] = copy.deepcopy(invalid)
                        raw = policy_raw()
                        raw["parts"].append("protected")
                        policy = Policy.parse(raw)
                        with self.assertRaises(ValueError):
                            check(policy, observed, previous)
                        report = report_for(policy, observed, previous)
                        self.assertFalse(report["machine_verified"])
                        self.assertEqual(row(report, "policy-overall")["status"], "unknown")
                        self.assertEqual(row(report, "preserved-protected")["status"], "unknown")
                        json.dumps(report, allow_nan=False)

    def test_malformed_protected_observation_has_a_readable_unknown_report(self):
        for side in ("candidate", "parent"):
            for shape in (None, {}, {"parts": None}, {"parts": []}):
                with self.subTest(side=side, shape=shape):
                    observed, previous = observations()
                    previous["parts"]["protected"] = copy.deepcopy(previous["parts"]["body"])
                    observed["parts"]["protected"] = copy.deepcopy(previous["parts"]["protected"])
                    raw = policy_raw()
                    raw["parts"].append("protected")
                    if side == "candidate":
                        observed = copy.deepcopy(shape)
                    else:
                        previous = copy.deepcopy(shape)
                    report = report_for(Policy.parse(raw), observed, previous)
                    self.assertFalse(report["machine_verified"])
                    self.assertEqual(row(report, "policy-overall")["status"], "unknown")
                    if previous is not None:
                        self.assertEqual(row(report, "preserved-protected")["status"], "unknown")
                    json.dumps(report, allow_nan=False)
        for bad_part in (None, [], "invalid"):
            observed, previous = observations()
            previous["parts"]["protected"] = copy.deepcopy(previous["parts"]["body"])
            observed["parts"]["protected"] = bad_part
            raw = policy_raw()
            raw["parts"].append("protected")
            report = report_for(Policy.parse(raw), observed, previous)
            self.assertFalse(report["machine_verified"])
            self.assertEqual(row(report, "preserved-protected")["status"], "unknown")
            json.dumps(report, allow_nan=False)

    def test_translation_budget_stops_before_measurement_including_report_rows(self):
        observed, previous = observations()
        p = observed["parts"]["body"]
        p["world_vertices"] = p["world_vertices"] + [[0., 0., 0.]] * (50001 - 4)
        raw = policy_raw()
        raw["constraints"].append(copy.deepcopy(raw["constraints"][0]))
        policy = Policy.parse(raw)
        with patch("experimental_modeling.acceptance.measure", side_effect=AssertionError("budget bypass")) as measure:
            with self.assertRaisesRegex(ValueError, "work|limit|budget"):
                check(policy, observed, previous)
            report = report_for(policy, observed, previous)
            measure.assert_not_called()
        self.assertFalse(report["machine_verified"])
        self.assertEqual(row(report, "policy-001")["status"], "unknown")
        self.assertEqual(row(report, "policy-002")["status"], "unknown")

    def test_total_surface_budget_stops_before_surface_preparation(self):
        observed, previous = observations()
        for target in (observed, previous):
            p = target["parts"]["body"]
            p["world_vertices"] += [[0., 0., 0.]] * (100000 - 4)
            p["edge_indices"] += [[0, 1]] * (30000 - 6)
        policy = Policy.parse(policy_raw())
        with patch("experimental_modeling.acceptance.surface", side_effect=AssertionError("budget bypass")) as surface:
            with self.assertRaisesRegex(ValueError, "work|limit|budget"):
                check(policy, observed, previous)
            report = report_for(policy, observed, previous)
            surface.assert_not_called()
        self.assertFalse(report["machine_verified"])
        self.assertEqual(row(report, "policy-001")["status"], "unknown")

    def test_saved_v2_report_rejects_status_or_binding_tampering(self):
        observed, previous = observations()
        report = report_for(Policy.parse(policy_raw()), observed, previous)
        validate_saved_report(copy.deepcopy(report), report)
        for mutate in (lambda r: r.update(machine_verified=False),
                       lambda r: r.update(schema_version=1),
                       lambda r: r["bindings"].update(policy_hash="0" * 64),
                       lambda r: row(r, "policy-001").update(status="unknown")):
            altered = copy.deepcopy(report)
            mutate(altered)
            with self.assertRaises(ValueError):
                validate_saved_report(altered, report)


class VersionTwoContractTests(unittest.TestCase):
    def test_v1_and_v2_translated_parameters_are_explicitly_versioned(self):
        raw = policy_raw()
        self.assertEqual(Policy.parse(raw).schema_version, 2)
        legacy = copy.deepcopy(raw)
        legacy["schema_version"] = 1
        with self.assertRaises(ValueError):
            Policy.parse(legacy)
        del legacy["constraints"][0]["data"]["normal_tolerance_radians"]
        self.assertEqual(Policy.parse(legacy).schema_version, 1)
        del raw["constraints"][0]["data"]["normal_tolerance_radians"]
        with self.assertRaises(ValueError):
            Policy.parse(raw)

    def test_v2_constraint_budget_is_bounded(self):
        raw = policy_raw()
        raw["constraints"] *= 33
        with self.assertRaises(ValueError):
            Policy.parse(raw)

    def test_invalid_v2_parameters_are_rejected(self):
        edits = [("delta", [0, 0]), ("delta", [True, 0, 0]),
                 ("delta", [float("nan"), 0, 0]), ("delta", [float("inf"), 0, 0]),
                 ("delta", [1e308, 0, 0]),
                 ("tolerance", True), ("tolerance", -1), ("tolerance", 1.1),
                 ("tolerance", float("nan")), ("tolerance", 10 ** 400),
                 ("delta", [10 ** 400, 0, 0]), ("normal_tolerance_radians", 10 ** 400),
                 ("normal_tolerance_radians", True),
                 ("normal_tolerance_radians", -.001), ("normal_tolerance_radians", .011),
                 ("normal_tolerance_radians", float("inf"))]
        for field, value in edits:
            with self.subTest(field=field, value=value):
                raw = policy_raw()
                raw["constraints"][0]["data"][field] = value
                with self.assertRaises(ValueError):
                    Policy.parse(raw)


if __name__ == "__main__":
    unittest.main()
