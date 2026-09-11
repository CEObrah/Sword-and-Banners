from __future__ import annotations

import copy

import sword_runtime.campaign_command_decision as decision
import sword_runtime.interaction_routing_health as routing
from sword_runtime.campaign_command_cycle import _cycle_ref


OPERATION_REF = "operation.test.follow_on"
CYCLE_REF = _cycle_ref(OPERATION_REF)


class _FakePlanner:
    PLAYER_ACTOR = "char_tang_wei"

    def __init__(self, attempts=None):
        self.data = {
            "state/runtime.json": {
                "world_time": "244-BCE-12-21T12:00:01+08:00",
                "hosts": {},
                "events": [],
            },
            "state/player.json": {"location": "loc_sanyou"},
            "state/cmd/command-groups/cmdgrp.tang_wei.field_army.json": {
                "active_context_ref": OPERATION_REF,
            },
            "state/index/interaction-attempts.json": {"attempts": list(attempts or [])},
            "cycle.json": {
                "kind": "campaign_command_cycle",
                "cycle_ref": CYCLE_REF,
                "operation_ref": OPERATION_REF,
                "status": "campaign_command_active",
                "venue_ref": "loc_sanyou",
                "participant_commander_refs": ["char_tang_wei", "char_mou_gou"],
                "superior_command_ref": "char_mou_gou",
                "supreme_commander_ref": "char_mou_gou",
                "coordination_authority_ref": "inst_qin_military_bureau",
                "war_council": {"status": "held"},
            },
            "state/char/char_mou_gou.json": {
                "person_id": "char_mou_gou",
                "current_location": "loc_qin_regional_01",
            },
            "game/data/mechanics/campaign-command.json": {
                "campaign_command_cycle": {"superior_request_response_delay_minutes": 15},
            },
        }
        self.owner_paths = {
            CYCLE_REF: "cycle.json",
            "char_mou_gou": "state/char/char_mou_gou.json",
        }

    def read(self, path: str):
        if path not in self.data:
            raise FileNotFoundError(path)
        return copy.deepcopy(self.data[path])

    def read_optional(self, path: str):
        value = self.data.get(path)
        return copy.deepcopy(value) if value is not None else None

    def owner_path(self, ref: str) -> str:
        if ref not in self.owner_paths:
            raise KeyError(ref)
        return self.owner_paths[ref]


def _attempt(*, expects_response: bool, target_ref: str = "inst_qin_military_bureau") -> dict:
    return {
        "event_id": "interaction_attempt.follow_on.admission",
        "actor_id": "char_tang_wei",
        "at": "244-BCE-12-21T12:00:01+08:00",
        "action": "report",
        "expects_response": expects_response,
        "target_ref": target_ref,
        "process_ref": OPERATION_REF,
        "topic": "campaign_command:next_objective",
        "player_statement": (
            "The concentration phase at Sanyou is complete. My field army remains "
            "9,500 strong and ready. State the next objective you require of me."
        ),
        "origin_location_ref": "loc_sanyou",
    }


def _route_stub(_read, origin: str, destination: str, *, round_trip: bool = False):
    assert origin == "loc_sanyou"
    assert destination == "loc_qin_regional_01"
    return {
        "origin_ref": origin,
        "destination_ref": destination,
        "route_refs": ["route.test.command"],
        "path": [origin, destination],
        "one_way_seconds": 82800,
        "travel_seconds": 165600 if round_trip else 82800,
        "round_trip": round_trip,
        "modes": ["horse", "foot"],
    }


def test_response_bearing_field_hq_request_is_admitted_and_scheduler_routable(monkeypatch) -> None:
    attempt = _attempt(expects_response=True)
    planner = _FakePlanner([attempt])
    monkeypatch.setattr(decision, "command_message_route", _route_stub)

    route = decision.campaign_command_follow_on_route(planner, attempt)
    assert route is not None
    assert route["cycle_ref"] == CYCLE_REF
    assert route["operation_ref"] == OPERATION_REF
    assert route["superior_ref"] == "char_mou_gou"
    assert route["request_origin_location_ref"] == "loc_sanyou"
    assert route["target_location_ref"] == "loc_qin_regional_01"
    assert route["courier_route"]["round_trip"] is True

    # ReconnaissanceAwareOperations uses this exact health predicate as the
    # public pre-admission response-route guard.
    assert routing._route_available(planner, attempt) is True

    summary = routing.summarize_interaction_routing(planner)
    assert summary["response_expected_attempts"] == 1
    assert summary["routable_on_next_scheduler_reconcile"] == 1
    assert summary["unrouted_attempts"] == 0

    runtime = copy.deepcopy(planner.data["state/runtime.json"])
    decision._route_follow_on_requests(planner, runtime)
    hosts = [
        host for host in runtime["hosts"].values()
        if host.get("route_domain") == "campaign_command_follow_on_review"
    ]
    assert len(hosts) == 1
    assert hosts[0]["source_interaction_attempt_ref"] == attempt["event_id"]
    assert hosts[0]["campaign_command_cycle_ref"] == CYCLE_REF
    assert hosts[0]["communication_travel_seconds"] == 165600


def test_explicit_no_response_follow_on_report_is_not_resurrected(monkeypatch) -> None:
    attempt = _attempt(expects_response=False)
    planner = _FakePlanner([attempt])
    monkeypatch.setattr(decision, "command_message_route", _route_stub)

    assert decision.campaign_command_follow_on_route(planner, attempt) is None
    summary = routing.summarize_interaction_routing(planner)
    assert summary["response_expected_attempts"] == 0

    runtime = copy.deepcopy(planner.data["state/runtime.json"])
    decision._route_follow_on_requests(planner, runtime)
    assert not any(
        host.get("route_domain") == "campaign_command_follow_on_review"
        for host in runtime["hosts"].values()
    )


def test_follow_on_route_does_not_turn_an_unrelated_or_person_target_into_hq_access(monkeypatch) -> None:
    planner = _FakePlanner()
    monkeypatch.setattr(decision, "command_message_route", _route_stub)

    unrelated = _attempt(expects_response=True, target_ref="inst_unrelated_office")
    assert decision.campaign_command_follow_on_route(planner, unrelated) is None

    direct_person = _attempt(expects_response=True, target_ref="char_mou_gou")
    assert decision.campaign_command_follow_on_route(planner, direct_person) is None
