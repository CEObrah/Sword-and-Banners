"""Bounded routing projection for autonomous faction-alignment candidates."""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

INDEX_PATH = "state/index/faction-alignment-candidates.json"


def _blank() -> dict[str, Any]:
    return {
        "schema": "generic-object", "authority": False,
        "by_state": {}, "member_state": {},
    }


def _state_of(doc: Mapping[str, Any]) -> str | None:
    raw = doc.get("state")
    if not isinstance(raw, str) or not raw:
        career = doc.get("career_state") if isinstance(doc.get("career_state"), Mapping) else {}
        raw = career.get("state") if isinstance(career, Mapping) else None
    if not isinstance(raw, str) or not raw:
        allegiance = doc.get("allegiance")
        if isinstance(allegiance, str): raw = allegiance
        elif isinstance(allegiance, Mapping): raw = allegiance.get("state_ref", allegiance.get("state"))
    if not isinstance(raw, str) or not raw:
        return None
    state = raw.lower().replace("state_", "").strip()
    return state if state in {"qin","zhao","chu","wei","han","yan","qi"} else None


def sync_alignment_candidate(planner: Any, *, member_ref: str, member_kind: str, doc: Mapping[str, Any]) -> None:
    ref = str(member_ref or "")
    if member_kind not in {"person", "house"} or not ref:
        return
    index = copy.deepcopy(planner.read_optional(INDEX_PATH) or _blank())
    by_state = index.setdefault("by_state", {})
    member_state = index.setdefault("member_state", {})
    prior = member_state.get(ref)
    bucket_key = "person_refs" if member_kind == "person" else "house_refs"
    if isinstance(prior, str):
        bucket = by_state.get(prior, {})
        if isinstance(bucket, dict):
            bucket[bucket_key] = [x for x in bucket.get(bucket_key, []) if str(x) != ref]
    life_status = str(doc.get("life_status", doc.get("status", "active"))).lower()
    state = None if member_kind == "person" and life_status in {"dead", "deceased", "killed"} else _state_of(doc)
    if state:
        member_state[ref] = state
        bucket = by_state.setdefault(state, {"person_refs": [], "house_refs": []})
        rows = [str(x) for x in bucket.get(bucket_key, []) if isinstance(x, str)]
        if ref not in rows: rows.append(ref)
        bucket[bucket_key] = sorted(set(rows))
    else:
        member_state.pop(ref, None)
    planner.put(INDEX_PATH, index)


def remove_alignment_candidate(planner: Any, member_ref: str) -> None:
    ref = str(member_ref or "")
    index = copy.deepcopy(planner.read_optional(INDEX_PATH) or _blank())
    state = index.setdefault("member_state", {}).pop(ref, None)
    if isinstance(state, str):
        bucket = index.setdefault("by_state", {}).get(state, {})
        if isinstance(bucket, dict):
            for key in ("person_refs", "house_refs"):
                bucket[key] = [x for x in bucket.get(key, []) if str(x) != ref]
    planner.put(INDEX_PATH, index)


def state_candidates(planner: Any, state: str) -> dict[str, list[str]]:
    index = planner.read_optional(INDEX_PATH) or _blank()
    bucket = index.get("by_state", {}).get(str(state), {}) if isinstance(index, Mapping) else {}
    return {
        "person_refs": sorted({str(x) for x in bucket.get("person_refs", []) if isinstance(x, str)}),
        "house_refs": sorted({str(x) for x in bucket.get("house_refs", []) if isinstance(x, str)}),
    }


__all__ = ["INDEX_PATH", "sync_alignment_candidate", "remove_alignment_candidate", "state_candidates"]
