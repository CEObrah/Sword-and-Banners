"""Bounded causal-event head with deterministic archive segments and route shards.

The event/message/movement registry remains the hot operational owner.  Triggered
causal events older than the head window move into exact authoritative archive
segments.  A deterministic hash-prefix route shard maps an exact event ref to its
segment, so old report/work references can be rehydrated without a global scan.
"""
from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping
from typing import Any

EVENT_OWNER_REF = "events_messages_and_movement"
EVENT_OWNER_PATH = "state/event/events-messages-and-movement.json"
EVENT_HEAD_LIMIT = 512
EVENT_SEGMENT_SIZE = 256
EVENT_ARCHIVE_DIR = "state/event/archive"
EVENT_ROUTE_DIR = "state/event/index"
EVENT_ROUTE_PREFIX_HEX = 4
EVENT_RECENT_ARCHIVE_METADATA_LIMIT = 64


def _read(reader: Any, path: str) -> Any:
    if hasattr(reader, "read"):
        return reader.read(path)
    return reader.read_json(path)


def _read_optional(reader: Any, path: str) -> Any:
    if hasattr(reader, "read_optional"):
        return reader.read_optional(path)
    try:
        return _read(reader, path)
    except (FileNotFoundError, KeyError, OSError):
        return None


def _owner_path(planner: Any) -> str:
    if hasattr(planner, "owner_path"):
        return planner.owner_path(EVENT_OWNER_REF)
    return EVENT_OWNER_PATH


def read_causal_event_owner(planner: Any) -> tuple[str, dict[str, Any]]:
    path = _owner_path(planner)
    owner = copy.deepcopy(planner.read(path))
    if owner.get("schema") != "event-registry" or owner.get("owner_id") != EVENT_OWNER_REF:
        raise ValueError("causal event routing lost its exact event owner")
    if not isinstance(owner.setdefault("causal_events", {}), dict):
        raise ValueError("causal event owner causal_events is invalid")
    archives = owner.setdefault("archives", [])
    if not isinstance(archives, list):
        raise ValueError("causal event archive routing is invalid")
    return path, owner


def _event_sort_key(row: tuple[str, Any]) -> tuple[str, str, str]:
    ref, event = row
    if not isinstance(event, Mapping):
        return ("", "", ref)
    return (str(event.get("triggered_at", "")), str(event.get("due_at", "")), ref)


def _route_prefix(event_ref: str, width: int = EVENT_ROUTE_PREFIX_HEX) -> str:
    return hashlib.sha256(event_ref.encode("utf-8")).hexdigest()[:width]


def _route_path(prefix: str) -> str:
    return f"{EVENT_ROUTE_DIR}/route_{prefix}.json"


def _write_route_shard(planner: Any, prefix: str, routes: Mapping[str, str]) -> None:
    path = _route_path(prefix)
    existing = _read_optional(planner, path)
    if isinstance(existing, Mapping):
        doc = copy.deepcopy(dict(existing))
    else:
        doc = {
            "schema": "sword-causal-event-route-shard",
            "owner_id": f"causal_event_route_{prefix}",
            "authority": False,
            "prefix": prefix,
            "routes": {},
        }
    routed = doc.setdefault("routes", {})
    if not isinstance(routed, dict):
        raise ValueError("causal event route shard is invalid")
    for event_ref, segment_path in sorted(routes.items()):
        routed[event_ref] = segment_path
    doc["route_count"] = len(routed)
    planner.put(path, doc)
    if hasattr(planner, "_register_owner"):
        planner._register_owner(str(doc["owner_id"]), path)


def write_causal_event_owner(planner: Any, owner: Mapping[str, Any]) -> None:
    """Persist the hot owner, archiving the oldest triggered events when necessary."""
    doc = copy.deepcopy(dict(owner))
    causal = doc.setdefault("causal_events", {})
    if not isinstance(causal, dict):
        raise ValueError("causal event owner causal_events is invalid")
    archives = doc.setdefault("archives", [])
    if not isinstance(archives, list):
        raise ValueError("causal event archive routing is invalid")
    next_seq = max(1, int(doc.get("next_archive_seq", 1)))
    archived_count = doc.get("archived_event_count")
    if not isinstance(archived_count, int) or isinstance(archived_count, bool) or archived_count < 0:
        archived_count = sum(max(0, int(row.get("event_count", 0))) for row in archives if isinstance(row, Mapping))

    while len(causal) > EVENT_HEAD_LIMIT:
        ordered = sorted(causal.items(), key=_event_sort_key)
        chunk = ordered[:EVENT_SEGMENT_SIZE]
        if not chunk:
            break
        segment_ref = f"causal_event_segment_{next_seq:06d}"
        segment_path = f"{EVENT_ARCHIVE_DIR}/segment_{next_seq:06d}.json"
        segment_events = {ref: copy.deepcopy(event) for ref, event in chunk}
        first = chunk[0][1] if isinstance(chunk[0][1], Mapping) else {}
        last = chunk[-1][1] if isinstance(chunk[-1][1], Mapping) else {}
        segment = {
            "schema": "sword-causal-event-segment",
            "owner_id": segment_ref,
            "authority": True,
            "segment_number": next_seq,
            "event_count": len(segment_events),
            "first_triggered_at": str(first.get("triggered_at", "")),
            "last_triggered_at": str(last.get("triggered_at", "")),
            "causal_events": segment_events,
        }
        planner.put(segment_path, segment)
        if hasattr(planner, "_register_owner"):
            planner._register_owner(segment_ref, segment_path)

        by_prefix: dict[str, dict[str, str]] = {}
        for event_ref, _event in chunk:
            by_prefix.setdefault(_route_prefix(event_ref), {})[event_ref] = segment_path
            causal.pop(event_ref, None)
        for prefix, routes in sorted(by_prefix.items()):
            _write_route_shard(planner, prefix, routes)

        archives.append({
            "segment_ref": segment_ref,
            "path": segment_path,
            "event_count": len(segment_events),
            "first_triggered_at": segment["first_triggered_at"],
            "last_triggered_at": segment["last_triggered_at"],
        })
        if len(archives) > EVENT_RECENT_ARCHIVE_METADATA_LIMIT:
            del archives[:-EVENT_RECENT_ARCHIVE_METADATA_LIMIT]
        kind_counts = doc.setdefault("archived_kind_counts", {})
        if not isinstance(kind_counts, dict):
            raise ValueError("causal event archived kind counts are invalid")
        for _event_ref, archived_event in chunk:
            if isinstance(archived_event, Mapping):
                kind = str(archived_event.get("kind", ""))
                if kind:
                    kind_counts[kind] = int(kind_counts.get(kind, 0)) + 1
        archived_count += len(segment_events)
        doc["archive_segment_count"] = next_seq
        next_seq += 1

    doc["archived_event_count"] = archived_count
    doc["next_archive_seq"] = next_seq
    doc["head_limit"] = EVENT_HEAD_LIMIT
    doc["archive_segment_size"] = EVENT_SEGMENT_SIZE
    planner.put(_owner_path(planner), doc)


def get_causal_event_from_reader(reader: Any, event_ref: str) -> Mapping[str, Any] | None:
    """Resolve one exact causal event from a repository/store style reader."""
    owner = _read_optional(reader, EVENT_OWNER_PATH)
    hot = owner.get("causal_events", {}) if isinstance(owner, Mapping) else {}
    if isinstance(hot, Mapping):
        event = hot.get(event_ref)
        if isinstance(event, Mapping):
            return event
    prefix = _route_prefix(event_ref)
    shard = _read_optional(reader, _route_path(prefix))
    routes = shard.get("routes", {}) if isinstance(shard, Mapping) else {}
    segment_path = routes.get(event_ref) if isinstance(routes, Mapping) else None
    if not isinstance(segment_path, str) or not segment_path:
        return None
    segment = _read(reader, segment_path)
    events = segment.get("causal_events", {}) if isinstance(segment, Mapping) else {}
    event = events.get(event_ref) if isinstance(events, Mapping) else None
    return event if isinstance(event, Mapping) else None


def get_causal_event(planner: Any, event_ref: str) -> Mapping[str, Any] | None:
    """Resolve one exact causal event from the hot owner or deterministic archive route."""
    return get_causal_event_from_reader(planner, event_ref)



def iter_causal_events_newest(reader: Any, *, kinds: set[str] | frozenset[str] | None = None):
    """Yield triggered causal events newest-first across hot and archived storage.

    Segment paths are deterministic, so ordinary discovery does not depend on an
    ever-growing archive catalog.  Exact lookup still uses hash-route shards.
    """
    owner = _read_optional(reader, EVENT_OWNER_PATH)
    if not isinstance(owner, Mapping):
        return
    hot = owner.get("causal_events", {})
    rows = []
    if isinstance(hot, Mapping):
        rows = [(str(ref), event) for ref, event in hot.items() if isinstance(event, Mapping)]
    rows.sort(key=_event_sort_key, reverse=True)
    for ref, event in rows:
        if kinds is None or str(event.get("kind", "")) in kinds:
            yield ref, event

    segment_count = max(0, int(owner.get("archive_segment_count", owner.get("next_archive_seq", 1)) - 1))
    if segment_count <= 0:
        recent = owner.get("archives", [])
        if isinstance(recent, list):
            seqs = []
            for meta in recent:
                if not isinstance(meta, Mapping):
                    continue
                segment_ref = str(meta.get("segment_ref", ""))
                try:
                    seqs.append(int(segment_ref.rsplit("_", 1)[-1]))
                except (TypeError, ValueError):
                    continue
            segment_count = max(seqs, default=0)
    for seq in range(segment_count, 0, -1):
        segment_path = f"{EVENT_ARCHIVE_DIR}/segment_{seq:06d}.json"
        segment = _read_optional(reader, segment_path)
        if not isinstance(segment, Mapping):
            continue
        events = segment.get("causal_events", {})
        if not isinstance(events, Mapping):
            continue
        archived_rows = [(str(ref), event) for ref, event in events.items() if isinstance(event, Mapping)]
        archived_rows.sort(key=_event_sort_key, reverse=True)
        for ref, event in archived_rows:
            if kinds is None or str(event.get("kind", "")) in kinds:
                yield ref, event


def causal_event_kind_count_from_reader(reader: Any, kinds: set[str] | frozenset[str]) -> int:
    """Return total hot+archived count for selected kinds without archive scans."""
    owner = _read_optional(reader, EVENT_OWNER_PATH)
    if not isinstance(owner, Mapping):
        return 0
    hot = owner.get("causal_events", {})
    total = 0
    if isinstance(hot, Mapping):
        total += sum(1 for event in hot.values() if isinstance(event, Mapping) and str(event.get("kind", "")) in kinds)
    archived = owner.get("archived_kind_counts", {})
    if isinstance(archived, Mapping):
        total += sum(max(0, int(archived.get(kind, 0))) for kind in kinds)
    elif archived is not None:
        raise ValueError("causal event archive kind counts are invalid")
    return total

def causal_event_total_count(planner: Any) -> int:
    _path, owner = read_causal_event_owner(planner)
    hot = owner.get("causal_events", {})
    return max(0, int(owner.get("archived_event_count", 0))) + (len(hot) if isinstance(hot, Mapping) else 0)


__all__ = [
    "EVENT_OWNER_REF",
    "EVENT_OWNER_PATH",
    "EVENT_HEAD_LIMIT",
    "EVENT_SEGMENT_SIZE",
    "read_causal_event_owner",
    "write_causal_event_owner",
    "get_causal_event",
    "get_causal_event_from_reader",
    "causal_event_total_count",
    "iter_causal_events_newest",
    "causal_event_kind_count_from_reader",
]
