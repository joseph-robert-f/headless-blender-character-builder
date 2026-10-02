"""Select the check contract from the controller-owned policy."""
from dataclasses import replace
import re

from .acceptance_v1 import check as check_v1
from .translation_v2 import measure, surface, MAX_FACES, MAX_VALENCE


def check(policy, observation, previous, *, measurements=None):
    if policy.schema_version == 1:
        return check_v1(policy, observation, previous)
    if policy.schema_version != 2:
        raise ValueError("Unsupported policy version.")
    try:
        return _check_v2(policy, observation, previous, measurements=measurements)
    except (KeyError, TypeError, IndexError, AttributeError, OverflowError) as exc:
        raise ValueError("Observation data is incomplete or invalid: " + str(exc)) from exc


def _check_v2(policy, observation, previous, *, measurements=None):
    if not isinstance(observation, dict) or not isinstance(observation.get("parts"), dict):
        raise ValueError("Observation data is incomplete.")
    if previous is not None and not isinstance(previous, dict):
        raise ValueError("Baseline data is incomplete.")
    if previous is not None and (type(previous.get("schema_version")) is not int or previous["schema_version"] != 2):
        raise ValueError("An accepted version-2 baseline is required.")
    if type(observation.get("schema_version")) is not int or observation["schema_version"] != 2:
        raise ValueError("Version-2 observation is required.")
    parts = observation["parts"]
    if set(parts) != set(policy.parts):
        return [{"check":"semantic_parts", "expected":list(policy.parts), "actual":list(parts)}]
    if previous is not None:
        if not isinstance(previous.get("parts"), dict):
            raise ValueError("Baseline part data is incomplete.")
        removed = set(previous["parts"]) - set(parts)
        if removed:
            return [{"check":"removed_parts_unsupported", "parts":sorted(removed)}]
        unscoped = (set(parts) - set(previous["parts"])) - set(policy.changed_parts)
        if unscoped:
            return [{"check":"new_parts_outside_scope", "parts":sorted(unscoped)}]
    total_surface_work = 0
    for observed in (observation, previous):
        if observed is None:
            continue
        observed_parts = observed.get("parts")
        if not isinstance(observed_parts, dict):
            raise ValueError("Observation part data is incomplete.")
        for name in policy.parts:
            if observed is previous and name not in observed_parts:
                continue
            part = observed_parts.get(name)
            if not isinstance(part, dict):
                raise ValueError("Observation part data is incomplete.")
            for key in ("world_vertices", "edge_indices", "face_indices"):
                if not isinstance(part.get(key), list):
                    raise ValueError("Observation geometry data is incomplete.")
            total_surface_work += len(part["world_vertices"]) + len(part["edge_indices"])
            if len(part["face_indices"]) > MAX_FACES:
                raise ValueError("Face count exceeds the check limit.")
            for face in part["face_indices"]:
                if not isinstance(face, list) or len(face) > MAX_VALENCE:
                    raise ValueError("Face data is incomplete.")
                total_surface_work += len(face)
                if total_surface_work > 250000:
                    raise ValueError("Surface work exceeds the check limit.")
            if total_surface_work > 250000:
                raise ValueError("Surface work exceeds the check limit.")
    # Bound repeated measurement work before any exact-coordinate arithmetic.
    work = 0
    parts = observation.get("parts", {})
    for constraint in policy.constraints:
        if constraint.kind == "translated":
            work += len(parts.get(constraint.part, {}).get("world_vertices", []))
    if work > 100000:
        raise ValueError("Translation work exceeds the check limit.")
    # Validate evidence even for initial builds without a translation constraint.
    prepared, prior = {}, {}
    for name in policy.parts:
        prepared[name] = surface(observation, name)
        if previous is not None and name in previous["parts"]:
            prior[name] = surface(previous, name)
    if previous is not None:
        for name in policy.parts:
            if name in policy.changed_parts:
                continue
            for observed in (observation, previous):
                part = observed["parts"][name]
                for key in ("geometry_hash", "transform_hash", "material_hash"):
                    value = part.get(key)
                    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                        raise ValueError("A protected part has no valid hash evidence.")
    legacy_constraints = tuple(c for c in policy.constraints if c.kind != "translated")
    failures = check_v1(replace(policy, constraints=legacy_constraints), observation, previous)
    for index, constraint in enumerate(policy.constraints):
        if constraint.kind == "translated":
            passed, measured = measure(constraint.data, observation, previous, constraint.part,
                                       prepared=(prepared[constraint.part], prior.get(constraint.part)))
            if measurements is not None:
                measurements[index] = measured
            if not passed:
                failures.append({"check":"translated", "part":constraint.part,
                                 "measured":measured, "expected":constraint.data})
    return failures
