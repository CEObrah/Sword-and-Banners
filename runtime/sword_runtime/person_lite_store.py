"""Compact routed storage for individually relevant person-lite records.

Aggregate personnel have no individual sheet. Person-lite records are grouped
into owner/command-local roster shards. Sharding is a storage optimization only:
a soft target starts a new shard, but there is no hard world or population cap.
Full people continue to use exact character owners.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any
import re

SOFT_SHARD_TARGET = 128


def compact_person_lite_record(person: Mapping[str, Any]) -> dict[str, Any]:
    """Return the native compact person-lite representation.

    Person-lite stores individual facts only. Identity/schema already establish
    representation, military_rank owns durable rank, and current_location owns
    location. Healthy/zero-fatigue state is the implicit default until a real
    injury or fatigue value exists.
    """
    out = deepcopy(dict(person))
    if str(out.get("schema", "")) != "person-lite":
        return out
    person_ref = str(out.get("id") or "")
    if out.get("owner_id") == person_ref:
        out.pop("owner_id", None)
    if not out.get("current_location") and isinstance(out.get("loc"), str):
        out["current_location"] = out["loc"]
    out.pop("loc", None)
    durable = out.get("military_rank") if isinstance(out.get("military_rank"), Mapping) else {}
    if durable and str(out.get("rank", "")) == str(durable.get("grade", "")):
        out.pop("rank", None)
    if out.get("resolution") == "individual_lite":
        out.pop("resolution", None)
    health = out.get("health")
    if isinstance(health, Mapping):
        if set(health).issubset({"status", "fatigue"}) and str(health.get("status", "healthy")).lower() == "healthy" and int(health.get("fatigue", 0) or 0) == 0:
            out.pop("health", None)
    if int(out.get("fatigue", 0) or 0) == 0:
        out.pop("fatigue", None)
    if out.get("relationships") == []:
        out.pop("relationships", None)
    background = out.get("background")
    if isinstance(background, str) and background.startswith("Materialized from one already-conserved"):
        out.pop("background", None)
    dev = out.get("development_state")
    if isinstance(dev, dict):
        if float(dev.get("verified_role_exposure_hours", 0.0) or 0.0) == 0.0:
            dev.pop("verified_role_exposure_hours", None)
        ledger = dev.get("training_time_ledger")
        if isinstance(ledger, dict):
            if ledger.get("active_entries") == []:
                ledger.pop("active_entries", None)
            if ledger.get("active_windows") == []:
                ledger.pop("active_windows", None)
            if not ledger:
                dev.pop("training_time_ledger", None)
    return out


def _slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return text or "general"


def _new_shard_path(scope_ref: str, ordinal: int) -> str:
    return f"state/person/person-lite/{_slug(scope_ref)}-{ordinal:04d}.json"


def _scope_rows(index: Mapping[str, Any], scope_ref: str) -> list[dict[str, Any]]:
    scope_map = index.get("scope_shards", {}) if isinstance(index.get("scope_shards"), Mapping) else {}
    rows = scope_map.get(scope_ref, []) if isinstance(scope_map, Mapping) else []
    return [dict(row) for row in rows if isinstance(row, Mapping) and isinstance(row.get("path"), str)]


def _choose_shard(runtime: Any, index: Mapping[str, Any], scope_ref: str, person_ref: str) -> tuple[str, list[dict[str, Any]]]:
    routes = index.get("record_index", {}) if isinstance(index.get("record_index"), Mapping) else {}
    existing = routes.get(person_ref)
    if isinstance(existing, str) and "#/records/" in existing:
        return existing.split("#/records/", 1)[0], _scope_rows(index, scope_ref)
    rows = _scope_rows(index, scope_ref)
    if rows:
        last = rows[-1]
        path = str(last["path"])
        shard = runtime.read_optional(path)
        count = len(shard.get("records", {})) if isinstance(shard, Mapping) and isinstance(shard.get("records"), Mapping) else int(last.get("record_count", 0))
        if count < SOFT_SHARD_TARGET:
            return path, rows
        ordinal = max(int(row.get("ordinal", i + 1)) for i, row in enumerate(rows)) + 1
        return _new_shard_path(scope_ref, ordinal), rows
    return _new_shard_path(scope_ref, 1), rows


def put_person_lite(runtime: Any, *, person: Mapping[str, Any], scope_ref: str) -> str:
    person_ref = str(person.get("id") or "")
    if not person_ref:
        raise ValueError("person-lite record requires id")
    if not scope_ref:
        raise ValueError("person-lite record requires routing scope")

    index_path = "state/cmd/command-personnel.json"
    raw = runtime.read_optional(index_path)
    index = dict(raw) if isinstance(raw, Mapping) else {"schema": "command-personnel-index", "id": "command_personnel", "record_index": {}, "count": 0}
    path, existing_rows = _choose_shard(runtime, index, scope_ref, person_ref)
    shard_raw = runtime.read_optional(path)
    if isinstance(shard_raw, Mapping):
        shard = dict(shard_raw)
        if shard.get("scope_ref") not in {None, scope_ref}:
            raise ValueError("person-lite shard scope mismatch")
    else:
        match = re.search(r"-(\d{4})\.json$", path)
        ordinal = int(match.group(1)) if match else 1
        shard = {
            "schema": "person-lite-roster-shard",
            "id": f"person_lite_roster.{_slug(scope_ref)}.{ordinal:04d}",
            "scope_ref": scope_ref,
            "shard_ordinal": ordinal,
            "records": {},
            "record_count": 0,
        }
    shard.setdefault("scope_ref", scope_ref)
    records = dict(shard.get("records", {})) if isinstance(shard.get("records"), Mapping) else {}
    records[person_ref] = compact_person_lite_record(person)
    shard["records"] = records
    shard["record_count"] = len(records)
    runtime.put(path, shard)

    fragment = f"{path}#/records/{person_ref}"
    runtime._register_owner(person_ref, fragment)
    routes = dict(index.get("record_index", {})) if isinstance(index.get("record_index"), Mapping) else {}
    routes[person_ref] = fragment
    index["record_index"] = routes
    index["count"] = len(routes)

    scope_map = dict(index.get("scope_shards", {})) if isinstance(index.get("scope_shards"), Mapping) else {}
    rows = [dict(row) for row in existing_rows]
    ordinal = int(shard.get("shard_ordinal", len(rows) + 1))
    updated = False
    for row in rows:
        if row.get("path") == path:
            row.update({"ordinal": ordinal, "record_count": len(records)})
            updated = True
            break
    if not updated:
        rows.append({"path": path, "ordinal": ordinal, "record_count": len(records)})
    rows.sort(key=lambda row: int(row.get("ordinal", 0)))
    scope_map[scope_ref] = rows
    index["scope_shards"] = scope_map
    runtime.put(index_path, index)
    return path
