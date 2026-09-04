"""Identity-checked routing for exact information claims.

``state/information/subject-index.json`` is explicitly ``authority:false``. It
may accelerate or alias subject lookup, but exact ``sword-information`` owners
registered in ``state/information/index.json`` determine which subjects a claim
can actually support.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


def exact_information_claim(
    read_optional: Callable[[str], Any],
    information_index: Mapping[str, Any],
    information_ref: str,
) -> tuple[str, Mapping[str, Any]] | None:
    claims = information_index.get("claims", {}) if isinstance(information_index, Mapping) else {}
    path = claims.get(information_ref) if isinstance(claims, Mapping) else None
    if not isinstance(path, str) or not path:
        return None
    claim = read_optional(path)
    if not isinstance(claim, Mapping):
        return None
    if str(claim.get("schema", "")) != "sword-information":
        return None
    if str(claim.get("information_ref", claim.get("owner_id", ""))) != information_ref:
        return None
    return path, claim


def exact_claim_subject_refs(claim: Mapping[str, Any]) -> set[str]:
    refs: set[str] = set()
    for key in ("subject_ref", "supersession_group_ref"):
        value = claim.get(key)
        if isinstance(value, str) and value:
            refs.add(value)
    for key in ("evidence_refs", "subject_alias_refs"):
        values = claim.get(key)
        if isinstance(values, list):
            refs.update(str(value) for value in values if isinstance(value, str) and value)
    return refs


def information_claim_refs_for_subject(
    read_optional: Callable[[str], Any],
    information_index: Mapping[str, Any],
    subject_index: Mapping[str, Any] | None,
    subject_ref: str,
) -> list[str]:
    """Resolve a subject from exact claim metadata, using the cache only as a hint."""
    if not isinstance(subject_ref, str) or not subject_ref:
        return []
    claims = information_index.get("claims", {}) if isinstance(information_index, Mapping) else {}
    if not isinstance(claims, Mapping):
        return []
    hinted: set[str] = set()
    subjects = subject_index.get("subjects", {}) if isinstance(subject_index, Mapping) else {}
    raw_hints = subjects.get(subject_ref, []) if isinstance(subjects, Mapping) else []
    if isinstance(raw_hints, list):
        hinted.update(str(ref) for ref in raw_hints if isinstance(ref, str))
    # The exact claim registry is bounded campaign state, not a filesystem scan.
    candidates = hinted | {str(ref) for ref in claims if isinstance(ref, str)}
    resolved: list[str] = []
    for information_ref in sorted(candidates):
        exact = exact_information_claim(read_optional, information_index, information_ref)
        if exact is None:
            continue
        _path, claim = exact
        if subject_ref not in exact_claim_subject_refs(claim):
            continue
        resolved.append(information_ref)
    return resolved


def information_supersession_groups(
    read_optional: Callable[[str], Any],
    information_index: Mapping[str, Any],
) -> dict[str, str]:
    groups: dict[str, str] = {}
    claims = information_index.get("claims", {}) if isinstance(information_index, Mapping) else {}
    if not isinstance(claims, Mapping):
        return groups
    for information_ref in sorted(str(ref) for ref in claims if isinstance(ref, str)):
        exact = exact_information_claim(read_optional, information_index, information_ref)
        if exact is None:
            continue
        _path, claim = exact
        group = claim.get("supersession_group_ref") or claim.get("subject_ref")
        if isinstance(group, str) and group:
            groups[information_ref] = group
    return groups


__all__ = [
    "exact_information_claim",
    "exact_claim_subject_refs",
    "information_claim_refs_for_subject",
    "information_supersession_groups",
]
