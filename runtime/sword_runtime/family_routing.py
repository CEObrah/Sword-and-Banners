"""Identity-checked reads for authority:false family routing indexes.

Family indexes nominate exact sparse records.  They never own a proposal, union,
household, parentage, kinship or succession, so a stale route must neither
substitute another record nor manufacture person membership.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

_SPECS: dict[str, tuple[str, str, str]] = {
    "proposals": ("family-proposal", "proposal_id", "state/family/proposals/{ref}.json"),
    "unions": ("family-union", "union_id", "state/family/unions/{ref}.json"),
    "households": ("family-household", "household_id", "state/family/households/{ref}.json"),
    "parentage": ("family-parentage", "parentage_id", "state/family/parentage/{ref}.json"),
    "kinships": ("family-kinship", "kinship_id", "state/family/kinships/{ref}.json"),
    "successions": ("family-succession", "succession_id", "state/family/successions/{ref}.json"),
}


def exact_family_record(
    read_optional: Callable[[str], Any],
    index: Mapping[str, Any],
    bucket: str,
    record_ref: str,
) -> tuple[str, Mapping[str, Any]] | None:
    """Resolve one exact family record without granting authority to its index route."""
    if bucket not in _SPECS or not isinstance(record_ref, str) or not record_ref:
        return None
    schema, id_field, template = _SPECS[bucket]
    routes = index.get(bucket, {}) if isinstance(index.get(bucket), Mapping) else {}
    routed = routes.get(record_ref) if isinstance(routes, Mapping) else None
    canonical = template.format(ref=record_ref)
    candidates = [routed, canonical] if isinstance(routed, str) else [canonical]
    seen: set[str] = set()
    for path in candidates:
        if not isinstance(path, str) or not path or path in seen:
            continue
        seen.add(path)
        row = read_optional(path)
        if not isinstance(row, Mapping):
            continue
        if str(row.get("schema", "")) != schema:
            continue
        if str(row.get(id_field, "")) != record_ref:
            continue
        return path, row
    return None


def exact_family_records_for_person(
    read_optional: Callable[[str], Any],
    index: Mapping[str, Any],
    bucket: str,
    person_ref: str,
) -> list[tuple[str, str, Mapping[str, Any]]]:
    """Recover exact family records involving one person from bounded routes.

    ``person_index`` is only a convenience cache.  Missing per-person rows must
    not erase an exact proposal, union, household or parentage record.  The
    bucket registry remains a bounded route set, and every candidate is
    identity/schema checked through :func:`exact_family_record` before use.
    """
    if bucket not in _SPECS or not isinstance(person_ref, str) or not person_ref:
        return []
    refs: set[str] = set()
    person_index = index.get("person_index", {}) if isinstance(index.get("person_index"), Mapping) else {}
    person_routes = person_index.get(person_ref, {}) if isinstance(person_index.get(person_ref), Mapping) else {}
    routed = person_routes.get(bucket, [])
    if isinstance(routed, list):
        refs.update(str(ref) for ref in routed if isinstance(ref, str) and ref)
    bucket_routes = index.get(bucket, {}) if isinstance(index.get(bucket), Mapping) else {}
    refs.update(str(ref) for ref in bucket_routes if isinstance(ref, str) and ref)

    out: list[tuple[str, str, Mapping[str, Any]]] = []
    for ref in sorted(refs):
        resolved = exact_family_record(read_optional, index, bucket, ref)
        if resolved is None:
            continue
        path, row = resolved
        involved = False
        if bucket == "proposals":
            involved = person_ref in {str(row.get("proposer_id", "")), str(row.get("target_id", ""))}
        elif bucket == "unions":
            involved = person_ref in {str(x) for x in row.get("participants", []) if isinstance(x, str)}
        elif bucket == "households":
            involved = person_ref in {
                str(x) for key in ("member_refs", "dependent_refs")
                for x in (row.get(key, []) if isinstance(row.get(key), list) else [])
                if isinstance(x, str)
            }
        elif bucket == "parentage":
            involved = str(row.get("child_id", "")) == person_ref or any(
                isinstance(link, Mapping) and str(link.get("parent_id") or link.get("guardian_id") or "") == person_ref
                for key in ("parent_links", "guardian_links")
                for link in (row.get(key, []) if isinstance(row.get(key), list) else [])
            )
        elif bucket == "kinships":
            involved = person_ref in {str(x) for x in row.get("participants", []) if isinstance(x, str)}
        elif bucket == "successions":
            values = []
            for key in ("subject_ref", "decedent_ref", "successor_ref", "heir_ref"):
                if isinstance(row.get(key), str):
                    values.append(str(row.get(key)))
            for key in ("candidate_refs", "heir_refs", "participant_refs"):
                if isinstance(row.get(key), list):
                    values.extend(str(x) for x in row.get(key, []) if isinstance(x, str))
            involved = person_ref in values
        if involved:
            out.append((ref, path, row))
    return out


__all__ = ["exact_family_record", "exact_family_records_for_person"]
