from __future__ import annotations

import json

from sword_runtime.api.interaction_surface import (
    INTERACTION_ATTEMPT_PREFIX,
    recent_interaction_attempts,
)
from sword_runtime.contact_request_flow import ContactRequestFlowMixin
from sword_runtime.transaction_invalidations import invalidated_request_ids


BAD_REQUEST = "bad-contact-request"
PROCESS_REF = "event_test_northern_wei_report"


def _summary(request_id: str) -> str:
    attempt = {
        "schema": "sword-interaction-attempt.v1",
        "surface_digest": "a" * 64,
        "request_id": request_id,
        "actor_id": "char_tang_wei",
        "target_ref": "loc_kanyou",
        "action": "seek_contact",
        "process_ref": PROCESS_REF,
        "player_statement": None,
        "formation_refs": ["formation_tang_champions_first"],
        "posture": "Seek the proper Qin military receiving office before presenting substantive business.",
        "world_response_status": "not_established_by_attempt",
    }
    return INTERACTION_ATTEMPT_PREFIX + json.dumps(
        attempt, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


class _Reader:
    def __init__(self):
        self.data = {
            "runtime/contracts/transaction-invalidations.json": {
                "schema": "sword-transaction-invalidations.v1",
                "records": [{
                    "campaign_id": "sword-banner-tang-wei-main",
                    "request_id": BAD_REQUEST,
                    "transaction_id": "sword-bad",
                }],
            },
            "state/history/events/index.json": {
                "events": [
                    {"event_id": "scene_good", "at": "245-BCE-12-07T21:37:48+08:00", "summary": _summary("good-contact-request")},
                    {"event_id": "scene_bad", "at": "245-BCE-12-07T21:37:48+08:00", "summary": _summary(BAD_REQUEST)},
                ],
                "archives": [],
                "archived_event_count": 0,
            },
            "state/event/events-messages-and-movement.json": {
                "schema": "event-registry",
                "owner_id": "events_messages_and_movement",
                "causal_events": {
                    PROCESS_REF: {
                        "event_ref": PROCESS_REF,
                        "kind": "world_arc_report",
                        "status": "triggered",
                        "arc_ref": "arc_ryo_fui_northern_wei_campaign",
                    }
                },
            },
            "game/data/politics/contact-routes.json": {
                "routes": [{
                    "route_ref": "contact_qin_military_bureau_kanyou_northern_wei",
                    "location_ref": "loc_kanyou",
                    "arc_ref": "arc_ryo_fui_northern_wei_campaign",
                    "institution_ref": "inst_qin_military_bureau",
                    "receiving_role": "Qin Military Bureau duty officer",
                    "delay_seconds": 3600,
                    "delivery_route": "Qin Military Bureau receiving office in Kanyou",
                    "audience_summary": "A duty officer is available to hear Tang Wei; no substantive request has yet been made.",
                }],
            },
        }

    def read_json(self, path):
        return self.data[path]


class _ContactPlanner(ContactRequestFlowMixin):
    def __init__(self, data):
        self.data = data

    def read(self, path):
        return self.data[path]


def test_invalidated_request_ids_are_bounded_read_only_provenance() -> None:
    reader = _Reader()
    assert invalidated_request_ids(reader) == {BAD_REQUEST}
    assert invalidated_request_ids(reader, "other-campaign") == set()


def test_recent_interaction_surface_omits_invalidated_attempt() -> None:
    reader = _Reader()
    rows, count = recent_interaction_attempts(reader, "char_tang_wei")
    assert count == 1
    assert [row["request_id"] for row in rows] == ["good-contact-request"]


def test_contact_router_cannot_resurrect_invalidated_attempt() -> None:
    reader = _Reader()
    planner = _ContactPlanner(reader.data)
    runtime = {
        "world_time": "245-BCE-12-07T21:37:48+08:00",
        "hosts": {},
        "events": [],
    }
    planner._sync_contact_request_routes(runtime)
    requests = {
        row.get("request_id")
        for row in runtime["hosts"].values()
        if isinstance(row, dict) and row.get("kind") == "contact_request"
    }
    assert BAD_REQUEST not in requests
    assert "good-contact-request" in requests
