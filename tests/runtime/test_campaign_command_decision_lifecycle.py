import copy

import sword_runtime.campaign_command_decision as decision


class _FakePlanner:
    PLAYER_ACTOR = "char_tang_wei"

    def __init__(self, data):
        self.data = copy.deepcopy(data)
        self.puts = []

    def read(self, path):
        if path not in self.data:
            raise FileNotFoundError(path)
        return copy.deepcopy(self.data[path])

    def read_optional(self, path):
        value = self.data.get(path)
        return copy.deepcopy(value) if value is not None else None

    def put(self, path, value):
        self.data[path] = copy.deepcopy(value)
        self.puts.append(path)


def _cycle():
    return {
        "kind": "campaign_command_cycle",
        "cycle_ref": "campaign_command_cycle.test",
        "operation_ref": "operation.test",
        "status": "campaign_command_active",
        "venue_ref": "loc_sanyou",
        "war_council": {"status": "held"},
        "supreme_commander_ref": "char_mou_gou",
        "superior_command_ref": "char_mou_gou",
        "coordination_authority_ref": "inst_qin_military_bureau",
        "upward_reports": [],
        "reported_command_information_refs": [],
        "reported_follow_on_request_refs": [],
        "campaign_command_decision_refs": [],
    }


def _operation():
    return {
        "owner_id": "operation.test",
        "status": "active",
        "location_ref": "loc_sanyou",
        "operational_area_ref": "loc_sanyou",
        "strategic_target_ref": "loc_sanyou",
        "institutional_owner_ref": "state_qin",
        "campaign_phase": "operational_area_arrival",
        "order_status": "awaiting_follow_on_direction",
        "last_operational_order_ref": "operational_order.base",
        "operational_orders": [{
            "order_ref": "operational_order.base",
            "issued_at": "244-BCE-09-17T22:22:48+08:00",
            "issuer_ref": "state_qin",
            "superior_commander_ref": "char_mou_gou",
            "status": "phase_complete_awaiting_follow_on_direction",
            "actionability_status": "completed",
            "objective": "Reach Sanyou and report on arrival.",
            "mission_packet": {
                "strategic_target_ref": "loc_sanyou",
                "strategic_target_name": "Sanyou",
                "destination_ref": "loc_sanyou",
                "destination_name": "Sanyou",
            },
            "applies_to_formation_refs": ["formation_qin_a", "formation_qin_b"],
            "excluded_non_state_formation_refs": ["formation_house_tang_a"],
        }],
    }


def _base_data(*, with_intelligence=True, attempts=None):
    data = {
        "state/runtime.json": {"world_time": "244-BCE-09-29T18:00:00+08:00"},
        "state/player.json": {"location": "loc_sanyou"},
        "state/cmd/command-groups/cmdgrp.tang_wei.field_army.json": {
            "active_context_ref": "operation.test",
        },
        "state/information/index.json": {
            "claims": {},
            "by_holder": {"char_tang_wei": []},
        },
        "state/index/interaction-attempts.json": {"attempts": list(attempts or [])},
        "cycle.json": _cycle(),
        "operation.json": _operation(),
        "game/data/mechanics/campaign-command.json": {
            "campaign_command_cycle": {"superior_request_response_delay_minutes": 15}
        },
    }
    if with_intelligence:
        info_ref = "information.military_reconnaissance.test"
        info_path = "state/information/claims/test.json"
        data["state/information/index.json"] = {
            "claims": {info_ref: info_path},
            "by_holder": {"char_tang_wei": [info_ref]},
        }
        data[info_path] = {
            "information_ref": info_ref,
            "classification": "command_intelligence",
            "subject_ref": "military_reconnaissance:loc_wei_regional_02",
            "claim": "Eight enemy formations were observed in the assigned corridor.",
            "confidence_milli": 746,
            "provenance": "military_reconnaissance",
            "holder_states": {
                "char_tang_wei": {
                    "learned_at": "244-BCE-09-29T17:30:00+08:00",
                    "source_ref": "char_ren_qiao",
                }
            },
        }
    return data


def _patch_exact_owners(monkeypatch, planner):
    monkeypatch.setattr(
        decision,
        "_read_cycle",
        lambda _planner, operation_ref: (
            "cycle.json", copy.deepcopy(planner.data["cycle.json"])
        ) if operation_ref == "operation.test" else None,
    )
    monkeypatch.setattr(
        decision,
        "_load_operation",
        lambda _planner, operation_ref: (
            "operation.json", copy.deepcopy(planner.data["operation.json"])
        ) if operation_ref == "operation.test" else (_ for _ in ()).throw(KeyError(operation_ref)),
    )


def test_material_command_intelligence_creates_one_bounded_follow_on_order(monkeypatch):
    planner = _FakePlanner(_base_data())
    _patch_exact_owners(monkeypatch, planner)

    created = decision.sync_campaign_command_decisions(planner)
    assert len(created) == 1
    operation = planner.data["operation.json"]
    latest = operation["operational_orders"][-1]
    assert latest["order_ref"] == created[0]
    assert latest["order_kind"] == "campaign_command_follow_on_mission"
    assert latest["actionability_status"] == "actionable"
    assert latest["mission_packet"]["mission_phase"] == "contact_development"
    assert latest["mission_packet"]["source_information_refs"] == [
        "information.military_reconnaissance.test"
    ]
    assert latest["applies_to_formation_refs"] == ["formation_qin_a", "formation_qin_b"]
    assert latest["excluded_non_state_formation_refs"] == ["formation_house_tang_a"]
    assert "formation_refs" not in latest["mission_packet"]
    assert operation["campaign_phase"] == "contact_development"
    assert operation["order_status"] == "staff_briefed_awaiting_commander_execution"

    cycle = planner.data["cycle.json"]
    assert cycle["reported_command_information_refs"] == ["information.military_reconnaissance.test"]
    assert cycle["upward_reports"][-1]["phase"] == "material_intelligence"
    assert len(cycle["campaign_command_decisions"]) == 1

    assert decision.sync_campaign_command_decisions(planner) == []
    assert len(planner.data["operation.json"]["operational_orders"]) == 2


def test_bare_follow_on_request_cannot_create_superior_order(monkeypatch):
    attempt = {
        "event_id": "interaction_attempt.follow_on",
        "actor_id": "char_tang_wei",
        "at": "244-BCE-09-29T18:00:00+08:00",
        "action": "request",
        "target_ref": "campaign_command_cycle.test",
        "process_ref": "operation.test",
        "topic": "follow-on campaign order after reconnaissance",
        "player_statement": "I request the follow-on operational order.",
    }
    planner = _FakePlanner(_base_data(with_intelligence=False, attempts=[attempt]))
    _patch_exact_owners(monkeypatch, planner)

    assert decision.sync_campaign_command_decisions(planner) == []
    assert len(planner.data["operation.json"]["operational_orders"]) == 1
    assert planner.data["cycle.json"]["reported_follow_on_request_refs"] == [
        "interaction_attempt.follow_on"
    ]

    planner.data["state/index/interaction-attempts.json"]["attempts"][0]["response_ref"] = (
        decision.campaign_command_request_response_ref("interaction_attempt.follow_on")
    )
    created = decision.sync_campaign_command_decisions(planner)
    assert len(created) == 1
    latest = planner.data["operation.json"]["operational_orders"][-1]
    assert latest["decision_basis"]["follow_on_request_refs"] == ["interaction_attempt.follow_on"]


def test_follow_on_request_gets_delayed_causal_review_route(monkeypatch):
    attempt = {
        "event_id": "interaction_attempt.follow_on",
        "actor_id": "char_tang_wei",
        "at": "244-BCE-09-29T18:00:00+08:00",
        "action": "request",
        "target_ref": "campaign_command_cycle.test",
        "process_ref": "operation.test",
        "topic": "follow-on campaign order after reconnaissance and cavalry recall",
        "player_statement": "I request the follow-on operational order.",
    }
    planner = _FakePlanner(_base_data(with_intelligence=False, attempts=[attempt]))
    _patch_exact_owners(monkeypatch, planner)
    runtime = {
        "world_time": "244-BCE-09-29T18:00:00+08:00",
        "hosts": {},
        "events": [],
    }

    decision._route_follow_on_requests(planner, runtime)
    assert len(runtime["hosts"]) == 1
    host = next(iter(runtime["hosts"].values()))
    assert host["kind"] == "institutional_followup"
    assert host["route_domain"] == "campaign_command_follow_on_review"
    assert host["source_interaction_attempt_ref"] == "interaction_attempt.follow_on"
    assert host["request_dispositions"] == {"follow_on_order": "under_superior_review"}
    assert host["next_due"] == "244-BCE-09-29T18:15:00+08:00"
    assert len(planner.data["operation.json"]["operational_orders"]) == 1
    assert len(runtime["events"]) == 1
