"""Bounded cold-reference search for player-facing Sword reads.

This module exposes static reference identity only. It never proves mutable
campaign state, current location, wounds, control, staffing, relationships,
knowledge, stock, deployments, or future outcomes.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_ALLOWED_CATEGORIES = {"any", "location", "person", "house", "history"}
_MAX_CATALOG_RECORDS = 4096
_MAX_RESULTS = 32


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _match_score(query: str, *values: object) -> int | None:
    query_cf = query.casefold()
    texts = [_text(value) for value in values if _text(value)]
    folded = [value.casefold() for value in texts]
    if any(value == query_cf for value in folded):
        return 0
    if any(value.startswith(query_cf) for value in folded):
        return 1
    if any(query_cf in value for value in folded):
        return 2
    return None


def _location_records(store: Any) -> list[dict[str, Any]]:
    source = store.read_json("game/data/world/locations.json")
    records = []
    for item in source.get("locations", []):
        if not isinstance(item, Mapping):
            continue
        ref = item.get("ref")
        name = item.get("name")
        if not isinstance(ref, str) or not isinstance(name, str):
            continue
        records.append(
            {
                "category": "location",
                "ref": ref,
                "name": name,
                "kind": item.get("kind"),
                "state": item.get("state"),
                "functions": list(item.get("functions", []))[:16]
                if isinstance(item.get("functions"), list)
                else [],
                "flavor_only": bool(item.get("flavor_only", False)),
            }
        )
    return records


def _person_records(store: Any) -> list[dict[str, Any]]:
    source = store.read_json("game/data/people/latent-identities.json")
    identities = source.get("identities", {})
    if not isinstance(identities, Mapping):
        return []
    records = []
    for ref, item in identities.items():
        if not isinstance(ref, str) or not isinstance(item, Mapping):
            continue
        name = item.get("name")
        if not isinstance(name, str):
            continue
        record = {"category": "person", "ref": ref, "name": name}
        source_hint = item.get("source_hint")
        if isinstance(source_hint, str) and source_hint:
            record["source_hint"] = source_hint
        records.append(record)
    return records


def _house_records(store: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in (
        "game/data/world/noble-houses.json",
        "game/data/world/merchant-houses.json",
    ):
        source = store.read_json(path)
        houses = source.get("houses", [])
        if not isinstance(houses, list):
            continue
        for item in houses:
            if not isinstance(item, Mapping):
                continue
            ref = item.get("house_ref")
            name = item.get("name")
            if not isinstance(ref, str) or not isinstance(name, str):
                continue
            record = {
                "category": "house",
                "ref": ref,
                "name": name,
                "state": item.get("state"),
            }
            functions = item.get("functions")
            if isinstance(functions, list):
                record["functions"] = list(functions)[:16]
            records.append(record)
    return records


def _history_records(store: Any) -> list[dict[str, Any]]:
    source = store.read_json("game/data/history/canon-background.json")
    records = []
    completed = source.get("completed_background", [])
    if not isinstance(completed, list):
        return records
    for index, item in enumerate(completed):
        if not isinstance(item, Mapping):
            continue
        event = item.get("event")
        if not isinstance(event, str) or not event:
            continue
        records.append(
            {
                "category": "history",
                "ref": "canon_background_%03d" % index,
                "name": event,
                "year_bce": item.get("year_bce"),
            }
        )
    return records


def search_world_reference(
    store: Any,
    query: str,
    *,
    category: str = "any",
    offset: int = 0,
    limit: int = 12,
) -> dict[str, Any]:
    """Search curated cold reference identity with deterministic pagination."""

    if not isinstance(query, str) or not query.strip() or len(query) > 160:
        raise ValueError("query must be bounded non-empty text")
    query = query.strip()
    if category not in _ALLOWED_CATEGORIES:
        raise ValueError("unsupported world-reference category")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0 or offset > 100000:
        raise ValueError("offset is invalid")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > _MAX_RESULTS:
        raise ValueError("limit is invalid")

    records: list[dict[str, Any]] = []
    if category in {"any", "location"}:
        records.extend(_location_records(store))
    if category in {"any", "person"}:
        records.extend(_person_records(store))
    if category in {"any", "house"}:
        records.extend(_house_records(store))
    if category in {"any", "history"}:
        records.extend(_history_records(store))
    if len(records) > _MAX_CATALOG_RECORDS:
        raise ValueError("world-reference catalog exceeds bounded size")

    ranked: list[tuple[int, str, str, dict[str, Any]]] = []
    for record in records:
        score = _match_score(
            query,
            record.get("name"),
            record.get("ref"),
            record.get("state"),
            record.get("source_hint"),
        )
        if score is None:
            continue
        ranked.append(
            (
                score,
                _text(record.get("name")).casefold(),
                _text(record.get("ref")),
                record,
            )
        )
    ranked.sort(key=lambda item: item[:3])
    total = len(ranked)
    page = [item[3] for item in ranked[offset : offset + limit]]
    next_offset = offset + len(page)
    return {
        "query": query,
        "category": category,
        "results": page,
        "result_count": total,
        "results_truncated": next_offset < total,
        "next_offset": next_offset if next_offset < total else None,
        "reference_warning": (
            "Cold reference identity only. Results do not prove current mutable state, "
            "player knowledge, location, control, staffing, wounds, stock, relationships, "
            "deployments, or future outcomes."
        ),
    }


__all__ = ["search_world_reference"]
