from __future__ import annotations

from sword_runtime.engine import RepositoryCommandPlanner
from sword_runtime.history_store import (
    history_total_count,
    iter_history_events,
    recent_history_events,
    write_history_index,
)


def test_semantic_history_spills_to_exact_archive_segments(campaign) -> None:
    planner = RepositoryCommandPlanner(campaign)
    planner._reset()
    history = planner.read("state/history/events/index.json")
    history = dict(history)
    history["events"] = [
        {"event_id": f"evt_{i:04d}", "kind": "test", "at": f"245-BCE-01-01T00:{i % 60:02d}:00+08:00"}
        for i in range(600)
    ]
    write_history_index(planner, history)

    head = planner.read("state/history/events/index.json")
    assert len(head["events"]) == 344
    assert head["archived_event_count"] == 256
    assert len(head["archives"]) == 1
    route = head["archives"][0]
    segment = planner.read(route["path"])
    assert segment["event_count"] == 256
    assert segment["events"][0]["event_id"] == "evt_0000"
    assert segment["events"][-1]["event_id"] == "evt_0255"
    assert planner.read("state/index/owner-index.json")["owners"][route["segment_ref"]] == route["path"]
    assert history_total_count(planner) == 600
    assert [row["event_id"] for row in recent_history_events(planner, 3)] == ["evt_0597", "evt_0598", "evt_0599"]
    assert len(list(iter_history_events(planner))) == 600


def test_semantic_history_merges_stale_same_transaction_append(campaign) -> None:
    planner = RepositoryCommandPlanner(campaign)
    planner._reset()

    older = dict(planner.read("state/history/events/index.json"))
    older["events"] = list(older.get("events", []))
    stale = {**older, "events": list(older["events"])}

    first = {**older, "events": list(older["events"])}
    first["events"].append({
        "event_id": "evt_same_tx_first",
        "kind": "test",
        "at": "245-BCE-01-01T00:00:00+08:00",
    })
    write_history_index(planner, first)

    # A second domain still holds its older read image and appends independently.
    # Writing it must not erase the event already staged by the first domain.
    stale["events"].append({
        "event_id": "evt_same_tx_second",
        "kind": "test",
        "at": "245-BCE-01-01T00:01:00+08:00",
    })
    write_history_index(planner, stale)

    ids = [row["event_id"] for row in iter_history_events(planner)]
    assert ids.count("evt_same_tx_first") == 1
    assert ids.count("evt_same_tx_second") == 1
    assert ids.index("evt_same_tx_first") < ids.index("evt_same_tx_second")
