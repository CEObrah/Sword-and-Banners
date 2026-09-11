"""Identity-checked routing for exact materialized fortification owners.

``state/fortifications/index.json`` is a bounded routing/cache owner.  It may
help locate a fortification or carry static profile hints, but it may never
substitute another exact fortification, erase one because a cache entry is
missing, or authorize duplicate materialization over an existing exact owner.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Iterator

_FORTIFICATION_INDEX = "state/fortifications/index.json"
_OWNER_INDEX = "state/index/owner-index.json"


def _read_optional(source: Any, path: str) -> Any | None:
    if callable(source):
        try:
            return source(path)
        except (FileNotFoundError, KeyError, ValueError):
            return None
    for name in ("read_optional", "read"):
        fn = getattr(source, name, None)
        if callable(fn):
            try:
                return fn(path)
            except (FileNotFoundError, KeyError, ValueError):
                continue
    raise TypeError("fortification routing requires bounded read access")


def _validated_fortification(row: Any, fortification_ref: str) -> dict[str, Any] | None:
    if not isinstance(row, Mapping) or str(row.get("schema") or "") != "sword-fortification":
        return None
    if str(row.get("fortification_ref") or "") != fortification_ref:
        return None
    owner_id = row.get("owner_id")
    if owner_id not in (None, "", fortification_ref):
        return None
    return dict(row)


def exact_fortification_record(source: Any, fortification_ref: str) -> tuple[str, dict[str, Any]] | None:
    """Resolve one materialized fortification by exact identity."""
    if not isinstance(fortification_ref, str) or not fortification_ref:
        return None
    candidates: list[str] = []

    owner_index = _read_optional(source, _OWNER_INDEX)
    owners = owner_index.get("owners", {}) if isinstance(owner_index, Mapping) else {}
    owner_path = owners.get(fortification_ref) if isinstance(owners, Mapping) else None
    if isinstance(owner_path, str) and owner_path:
        candidates.append(owner_path.split("#", 1)[0])

    routing = _read_optional(source, _FORTIFICATION_INDEX)
    routes = routing.get("fortifications", {}) if isinstance(routing, Mapping) else {}
    routed = routes.get(fortification_ref) if isinstance(routes, Mapping) else None
    if isinstance(routed, str) and routed:
        candidates.append(routed.split("#", 1)[0])

    candidates.append(f"state/fortifications/{fortification_ref}.json")
    seen: set[str] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        row = _validated_fortification(_read_optional(source, path), fortification_ref)
        if row is not None:
            return path, row
    return None


def iter_exact_fortification_records(source: Any) -> Iterator[tuple[str, str, dict[str, Any]]]:
    """Enumerate materialized fortifications without trusting the route cache."""
    refs: set[str] = set()
    owner_index = _read_optional(source, _OWNER_INDEX)
    owners = owner_index.get("owners", {}) if isinstance(owner_index, Mapping) else {}
    if isinstance(owners, Mapping):
        for ref, path in owners.items():
            if not isinstance(ref, str) or not isinstance(path, str):
                continue
            base = path.split("#", 1)[0]
            if base.startswith("state/fortifications/") and base != _FORTIFICATION_INDEX:
                refs.add(ref)

    routing = _read_optional(source, _FORTIFICATION_INDEX)
    routes = routing.get("fortifications", {}) if isinstance(routing, Mapping) else {}
    if isinstance(routes, Mapping):
        refs.update(str(ref) for ref in routes if isinstance(ref, str) and ref)

    for ref in sorted(refs):
        resolved = exact_fortification_record(source, ref)
        if resolved is None:
            continue
        path, row = resolved
        yield ref, path, row


__all__ = ["exact_fortification_record", "iter_exact_fortification_records"]
