"""Bounded semantic-history head with deterministic authoritative archive segments.

The history index remains the routing head. Older exact events move into immutable-
by-convention segment owners and remain rehydratable through the index. This keeps
ordinary reads bounded without treating the hot window as campaign amnesia.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any, Iterable

HISTORY_INDEX_PATH = "state/history/events/index.json"
_HISTORY_HEAD_LIMIT = 512
_HISTORY_SEGMENT_SIZE = 256
_HISTORY_ARCHIVE_DIR = "state/history/events/archive"


def _read(reader: Any, path: str) -> Any:
    if hasattr(reader, "read"):
        return reader.read(path)
    return reader.read_json(path)


def _archive_rows(history: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = history.get("archives", [])
    if not isinstance(rows, list):
        raise ValueError("semantic history archive routing is invalid")
    return [row for row in rows if isinstance(row, Mapping)]


def history_total_count(reader: Any) -> int:
    history = _read(reader, HISTORY_INDEX_PATH)
    if not isinstance(history, Mapping):
        return 0
    events = history.get("events", [])
    head = len(events) if isinstance(events, list) else 0
    archived = history.get("archived_event_count")
    if isinstance(archived, int) and not isinstance(archived, bool) and archived >= 0:
        return archived + head
    return sum(max(0, int(row.get("event_count", 0))) for row in _archive_rows(history)) + head


def recent_history_events(reader: Any, limit: int = 512) -> list[Mapping[str, Any]]:
    """Return newest persisted events in chronological order, crossing segments only as needed."""
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("history read limit is invalid")
    history = _read(reader, HISTORY_INDEX_PATH)
    if not isinstance(history, Mapping):
        return []
    events = history.get("events", [])
    head = [row for row in events if isinstance(row, Mapping)] if isinstance(events, list) else []
    if len(head) >= limit:
        return head[-limit:]
    result = list(head)
    need = limit - len(result)
    archives = _archive_rows(history)
    older: list[Mapping[str, Any]] = []
    for route in reversed(archives):
        path = route.get("path")
        if not isinstance(path, str) or not path:
            continue
        segment = _read(reader, path)
        rows = segment.get("events", []) if isinstance(segment, Mapping) else []
        if not isinstance(rows, list):
            raise ValueError("semantic history archive segment is invalid")
        material = [row for row in rows if isinstance(row, Mapping)]
        if material:
            take = material[-need:]
            older = take + older
            need -= len(take)
        if need <= 0:
            break
    return (older + result)[-limit:]


def iter_history_events(reader: Any) -> Iterable[Mapping[str, Any]]:
    """Yield all exact semantic events oldest to newest through explicit archive routes."""
    history = _read(reader, HISTORY_INDEX_PATH)
    if not isinstance(history, Mapping):
        return
    for route in _archive_rows(history):
        path = route.get("path")
        if not isinstance(path, str) or not path:
            continue
        segment = _read(reader, path)
        rows = segment.get("events", []) if isinstance(segment, Mapping) else []
        if not isinstance(rows, list):
            raise ValueError("semantic history archive segment is invalid")
        for event in rows:
            if isinstance(event, Mapping):
                yield event
    rows = history.get("events", [])
    if isinstance(rows, list):
        for event in rows:
            if isinstance(event, Mapping):
                yield event


def write_history_index(planner: Any, history: Mapping[str, Any]) -> None:
    """Persist history, spilling oldest hot events into exact archive owners."""
    staged = getattr(planner, "_writes", {})
    if isinstance(history, dict) and isinstance(staged, dict) and staged.get(HISTORY_INDEX_PATH) is history:
        # The planner already isolated this owner on first write. Reusing that
        # transaction-local image avoids repeatedly cloning a growing history head
        # during one batched causal command.
        doc = history
    else:
        doc = copy.deepcopy(dict(history))
    events = doc.setdefault("events", [])
    if not isinstance(events, list):
        raise ValueError("semantic history events are invalid")
    archives = doc.setdefault("archives", [])
    if not isinstance(archives, list):
        raise ValueError("semantic history archive routing is invalid")
    next_seq = max(1, int(doc.get("next_archive_seq", 1)))
    archived_count = doc.get("archived_event_count")
    if not isinstance(archived_count, int) or isinstance(archived_count, bool) or archived_count < 0:
        archived_count = sum(max(0, int(row.get("event_count", 0))) for row in archives if isinstance(row, Mapping))

    while len(events) > _HISTORY_HEAD_LIMIT:
        chunk = list(events[:_HISTORY_SEGMENT_SIZE])
        del events[:_HISTORY_SEGMENT_SIZE]
        segment_ref = f"semantic_history_segment_{next_seq:06d}"
        path = f"{_HISTORY_ARCHIVE_DIR}/segment_{next_seq:06d}.json"
        segment = {
            "schema": "sword-history-segment",
            "owner_id": segment_ref,
            "authority": True,
            "segment_number": next_seq,
            "event_count": len(chunk),
            "first_event_id": chunk[0].get("event_id") if chunk and isinstance(chunk[0], Mapping) else None,
            "last_event_id": chunk[-1].get("event_id") if chunk and isinstance(chunk[-1], Mapping) else None,
            "events": chunk,
        }
        planner.put(path, segment)
        if hasattr(planner, "_register_owner"):
            planner._register_owner(segment_ref, path)
        archives.append({
            "segment_ref": segment_ref,
            "path": path,
            "event_count": len(chunk),
            "first_event_id": segment["first_event_id"],
            "last_event_id": segment["last_event_id"],
        })
        archived_count += len(chunk)
        next_seq += 1

    doc["archived_event_count"] = archived_count
    doc["next_archive_seq"] = next_seq
    doc["head_limit"] = _HISTORY_HEAD_LIMIT
    doc["archive_segment_size"] = _HISTORY_SEGMENT_SIZE
    planner.put(HISTORY_INDEX_PATH, doc)


__all__ = [
    "HISTORY_INDEX_PATH",
    "history_total_count",
    "recent_history_events",
    "iter_history_events",
    "write_history_index",
]
