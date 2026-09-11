from pathlib import Path

from sword_runtime.api.command_discovery import _compact_campaign_command, compact_play_context
from sword_runtime.api.gm_scene_context import build_gm_scene_context
from sword_runtime.campaign_command_cycle import _player_safe_upward_report_window


def _campaign_command():
    return {
        "cycle_ref": "campaign_command_cycle.test",
        "status": "campaign_command_active",
        "venue_ref": "loc_sanyou",
        "coordination_authority_ref": "inst_qin_military_bureau",
        "superior_command_ref": "char_mou_gou",
        "supreme_commander_ref": "char_mou_gou",
        "upward_reports": [
            {
                "report_ref": "campaign_command_report.old",
                "phase": "dawn",
                "delivery_status": "delivered",
                "delivered_at": "244-BCE-12-21T05:00:00+08:00",
            },
            {
                "report_ref": "campaign_command_report.request",
                "phase": "material_intelligence",
                "prepared_at": "244-BCE-12-21T12:00:01+08:00",
                "delivery_status": "in_transit",
                "delivery_due_at": "244-BCE-12-22T11:00:01+08:00",
                "follow_on_request_refs": ["interaction_attempt.request"],
                "source_location_ref": "loc_sanyou",
                "target_location_ref": "loc_qin_regional_01",
                "communication_travel_seconds": 82800,
            },
        ],
        # Exact cycle internals may know that superior headquarters has already
        # acted. Player-safe compact context must not reveal an undelivered reply.
        "campaign_command_decisions": [
            {
                "decision_ref": "campaign_command_decision.hidden",
                "order_ref": "operational_order.hidden_follow_on",
                "delivery_status": "in_transit",
                "delivery_due_at": "244-BCE-12-22T11:15:01+08:00",
            }
        ],
    }


def _context(command=None):
    return {
        "campaign": {
            "world_time": "244-BCE-12-21T12:00:01+08:00",
            "player_id": "char_tang_wei",
        },
        "player": {
            "person_id": "char_tang_wei",
            "location": "loc_sanyou",
        },
        "scene": {
            "scene_cast": {"present_people": []},
            "narrative": {},
        },
        "controlled_operations": [
            {
                "operation_ref": "operation.test",
                "campaign_phase": "operational_area_arrival",
                "order_status": "awaiting_follow_on_direction",
                "campaign_command": command or _campaign_command(),
            }
        ],
        "recent_interaction_attempts": [],
        "recent_scene_history": [],
        "interaction_handles": [],
        "unresolved_decisions": [],
        "active_player_processes": [],
        "literary_continuity": [],
        "known_information": [],
        "permitted_person_ids": [],
        "permitted_object_refs": [],
    }


def test_compact_campaign_command_keeps_outbound_remote_handoff_hot_without_leaking_reply():
    compact, _ = _compact_campaign_command(
        _campaign_command(),
        {
            "order_ref": "operational_order.base",
            "status": "phase_complete_awaiting_follow_on_direction",
            "actionability_status": "completed",
        },
    )

    assert compact["pending_upward_report_count"] == 1
    assert compact["pending_upward_reports"][0]["report_ref"] == "campaign_command_report.request"
    assert compact["pending_upward_reports"][0]["delivery_status"] == "in_transit"
    assert compact["remote_command_handoff"]["outbound_report_in_flight"] is True
    assert compact["remote_command_handoff"]["response_requested"] is True
    assert "Do not claim remote command persistence is unavailable" in compact["remote_command_handoff"]["rule"]
    assert "do not resend the same request" in compact["remote_command_handoff"]["rule"]
    assert "pending_superior_decisions" not in compact
    assert "campaign_command_decision_count" not in compact
    assert "operational_order.hidden_follow_on" not in repr(compact)


def test_gm_scene_context_derives_remote_handoff_from_full_uncompacted_campaign_projection():
    # compact_play_context builds gm_scene_context before it compacts controlled
    # operations. This regression protects that exact integration boundary.
    compact = compact_play_context(_context())

    handoffs = compact["gm_scene_context"]["hard_constraints"]["remote_command_handoffs"]
    assert len(handoffs) == 1
    handoff = handoffs[0]
    assert handoff["operation_ref"] == "operation.test"
    assert handoff["cycle_ref"] == "campaign_command_cycle.test"
    assert handoff["outbound_report_in_flight"] is True
    assert handoff["response_requested"] is True
    assert handoff["pending_upward_reports"][0]["report_ref"] == "campaign_command_report.request"
    assert handoff["pending_upward_reports"][0]["delivery_status"] == "in_transit"
    assert "operational_order.hidden_follow_on" not in repr(handoff)


def test_player_safe_report_window_never_hides_old_response_bearing_courier_behind_routine_traffic():
    rows = [
        {
            "report_ref": "campaign_command_report.request",
            "phase": "material_intelligence",
            "delivery_status": "in_transit",
            "follow_on_request_refs": ["interaction_attempt.request"],
        }
    ]
    rows.extend(
        {
            "report_ref": f"campaign_command_report.delivered.{i}",
            "phase": "dawn" if i % 2 == 0 else "evening",
            "delivery_status": "delivered",
        }
        for i in range(12)
    )
    rows.extend(
        {
            "report_ref": f"campaign_command_report.routine_pending.{i}",
            "phase": "dawn" if i % 2 == 0 else "evening",
            "delivery_status": "in_transit",
        }
        for i in range(10)
    )

    projected, pending_count = _player_safe_upward_report_window(rows)
    refs = {row["report_ref"] for row in projected}
    assert pending_count == 11
    assert "campaign_command_report.request" in refs
    assert "campaign_command_report.routine_pending.9" in refs
    assert len(projected) <= 10

    compact, _ = _compact_campaign_command(
        {
            "cycle_ref": "campaign_command_cycle.test",
            "superior_command_ref": "char_mou_gou",
            "upward_reports": projected,
            "pending_upward_report_count": pending_count,
        },
        {"order_ref": "operational_order.base"},
    )
    assert compact["pending_upward_report_count"] == 11
    assert any(
        row.get("report_ref") == "campaign_command_report.request"
        for row in compact["pending_upward_reports"]
    )


def test_waiting_skill_treats_staff_proposal_work_as_reversible_while_remote_reply_is_pending():
    root = Path(__file__).resolve().parents[2]
    waiting = (
        root
        / "plugins/sword-and-banners/skill/sword-and-banners-game-master/references/waiting-and-handoffs.md"
    ).read_text(encoding="utf-8")

    assert "physically absent commander" in waiting
    assert "outbound remote lifecycle is already durable" in waiting
    assert "Never** say that the report could only be drafted" in waiting
    assert "have the staff prepare" in waiting
    assert "reversible staff work, not a binding strategic commitment" in waiting
    assert "without forcing Tang Wei to choose every intermediate branch" in waiting
    assert "carry that standing wait forward" in waiting


def test_interaction_contract_exposes_durable_remote_campaign_channel(campaign):
    from sword_runtime.api.campaign_planning_operations import CampaignPlanningAwareOperations
    from sword_runtime.engine import SwordRuntime

    operations = CampaignPlanningAwareOperations(SwordRuntime(campaign))
    contract = operations.get_command_contract("interaction_action")
    guidance = contract["input_guidance"]
    rule = guidance["campaign_command_remote_rule"]

    assert guidance["expects_response"]["rule"].startswith("set true")
    assert "campaign_command_cycle" in rule
    assert "current controlled operation as process_ref" in rule
    assert "routes physically" in rule
    assert "direct face-to-face access" in rule


def test_second_compaction_layer_keeps_older_response_request_hot_behind_newer_pending_traffic():
    command = {
        "cycle_ref": "campaign_command_cycle.stress",
        "superior_command_ref": "char_mou_gou",
        "upward_reports": [
            {
                "report_ref": "campaign_command_report.request.old",
                "phase": "material_intelligence",
                "delivery_status": "in_transit",
                "follow_on_request_refs": ["interaction_attempt.request.old"],
            },
            {
                "report_ref": "campaign_command_report.material.1",
                "phase": "material_intelligence",
                "delivery_status": "in_transit",
            },
            {
                "report_ref": "campaign_command_report.material.2",
                "phase": "material_intelligence",
                "delivery_status": "in_transit",
            },
            {
                "report_ref": "campaign_command_report.routine.1",
                "phase": "dawn",
                "delivery_status": "in_transit",
            },
            {
                "report_ref": "campaign_command_report.routine.2",
                "phase": "evening",
                "delivery_status": "in_transit",
            },
        ],
    }

    compact_command, _ = _compact_campaign_command(command, {"order_ref": "operational_order.base"})
    compact_refs = {row["report_ref"] for row in compact_command["pending_upward_reports"]}
    assert "campaign_command_report.request.old" in compact_refs
    assert compact_command["remote_command_handoff"]["response_requested"] is True

    compact_context = compact_play_context(_context(command))
    handoff = compact_context["gm_scene_context"]["hard_constraints"]["remote_command_handoffs"][0]
    gm_refs = {row["report_ref"] for row in handoff["pending_upward_reports"]}
    assert "campaign_command_report.request.old" in gm_refs
    assert handoff["response_requested"] is True


def test_delivered_report_history_never_becomes_a_fake_pending_remote_handoff():
    command = {
        "cycle_ref": "campaign_command_cycle.delivered",
        "superior_command_ref": "char_mou_gou",
        "upward_reports": [
            {
                "report_ref": "campaign_command_report.done.1",
                "phase": "dawn",
                "delivery_status": "delivered",
                "delivered_at": "244-BCE-12-21T10:00:00+08:00",
            },
            {
                "report_ref": "campaign_command_report.done.2",
                "phase": "evening",
                "delivery_status": "delivered",
                "delivered_at": "244-BCE-12-21T11:00:00+08:00",
            },
        ],
    }

    compact_command, _ = _compact_campaign_command(command, {"order_ref": "operational_order.base"})
    assert "pending_upward_reports" not in compact_command
    assert "remote_command_handoff" not in compact_command
    assert [row["report_ref"] for row in compact_command["recent_delivered_upward_reports"]] == [
        "campaign_command_report.done.1",
        "campaign_command_report.done.2",
    ]

    compact_context = compact_play_context(_context(command))
    assert compact_context["gm_scene_context"]["hard_constraints"]["remote_command_handoffs"] == []


def test_route_unresolved_report_is_visible_but_never_claimed_to_be_in_flight():
    command = {
        "cycle_ref": "campaign_command_cycle.route_unresolved",
        "superior_command_ref": "char_mou_gou",
        "upward_reports": [
            {
                "report_ref": "campaign_command_report.route_unresolved",
                "phase": "material_intelligence",
                "delivery_status": "route_unresolved",
                "follow_on_request_refs": ["interaction_attempt.route_unresolved"],
            }
        ],
    }

    compact_command, _ = _compact_campaign_command(command, {"order_ref": "operational_order.base"})
    handoff = compact_command["remote_command_handoff"]
    assert handoff["outbound_report_in_flight"] is False
    assert handoff["route_unresolved"] is True
    assert handoff["response_requested"] is True
    assert "no physical courier route is currently confirmed" in handoff["rule"]
    assert "wait as though delivery were scheduled" in handoff["rule"]

    compact_context = compact_play_context(_context(command))
    gm_handoff = compact_context["gm_scene_context"]["hard_constraints"]["remote_command_handoffs"][0]
    assert gm_handoff["outbound_report_in_flight"] is False
    assert gm_handoff["route_unresolved"] is True
    assert gm_handoff["response_requested"] is True
    assert gm_handoff["pending_upward_reports"][0]["delivery_status"] == "route_unresolved"


def test_current_campaign_snapshot_exposes_real_response_request_at_mcp_compaction_boundary(campaign, tmp_path):
    from sword_runtime.api.equipment_operations import EquipmentAwareCampaignOperations
    from sword_runtime.service_runtime import ProductionSwordRuntime

    runtime = ProductionSwordRuntime(campaign, runtime_root=tmp_path / "runtime-current-handoff")
    raw_context = EquipmentAwareCampaignOperations(runtime).play_context()
    assert raw_context["campaign"]["revision"] == 45

    compact = compact_play_context(raw_context)
    handoffs = compact["gm_scene_context"]["hard_constraints"]["remote_command_handoffs"]
    response_handoffs = [row for row in handoffs if row.get("response_requested") is True]
    assert len(response_handoffs) == 1
    handoff = response_handoffs[0]
    assert handoff["operation_ref"] == "operation_arc_131572c4e8a2892bbc"
    assert handoff["cycle_ref"] == "campaign_command_cycle.885d1dbce1823cdb2495"
    assert handoff["superior_command_ref"] == "char_mou_gou"
    assert handoff["outbound_report_in_flight"] is True
    assert handoff["route_unresolved"] is False
    assert any(
        row.get("report_ref") == "campaign_command_material_report.422ceb750df6e387d219"
        and row.get("follow_on_request_refs") == ["interaction_attempt_1801588e9249ea1029d1936b"]
        and row.get("delivery_status") == "in_transit"
        for row in handoff["pending_upward_reports"]
    )
