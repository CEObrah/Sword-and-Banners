from __future__ import annotations

from sword_runtime.great_bow_guard_readiness_event_schema import (
    GreatBowGuardReadinessEventSchemaMixin,
    sanitize_great_bow_guard_readiness_event,
)
from sword_runtime.great_bow_guard_readiness_flow import GreatBowGuardReadinessFlowMixin
from sword_runtime.production_planner import ProductionCampaignPlanner


def test_gbg_event_schema_adapter_precedes_readiness_host_in_mro() -> None:
    mro = ProductionCampaignPlanner.__mro__
    assert mro.index(GreatBowGuardReadinessEventSchemaMixin) < mro.index(GreatBowGuardReadinessFlowMixin)


def test_gbg_event_schema_adapter_strips_only_duplicate_owner_fields(campaign) -> None:
    planner = ProductionCampaignPlanner(campaign)
    event_ref = "event_test_gbg_schema_adapter"
    _path, owner = __import__(
        "sword_runtime.causal_event_store", fromlist=["read_causal_event_owner"]
    ).read_causal_event_owner(planner)
    owner["causal_events"][event_ref] = {
        "event_ref": event_ref,
        "kind": "institutional_response",
        "status": "triggered",
        "due_at": "244-BCE-07-23T01:22:48+08:00",
        "triggered_at": "244-BCE-07-23T01:22:48+08:00",
        "actor_ref": "char_tang_zhu",
        "target_ref": "char_tang_wei",
        "basis_goal": "test",
        "process_kind": "great_bow_guard_field_readiness",
        "process_stage": "ready_with_shortfalls",
        "formation_ref": "formation_tang_wei_great_bow_guard_first",
        "great_bow_guard_stats": {"personnel": 300},
        "issued_loadout_items": {"armor_tang": 300},
        "remaining_shortfalls": {"weapon_spear_long": 300},
        "summary": "test summary",
        "delivery": {
            "target_ref": "char_tang_wei",
            "location_ref": "loc_tang_manor_inner_citadel_family_hall",
            "route": "House Tang field quartermaster and family counsel",
        },
    }
    __import__(
        "sword_runtime.causal_event_store", fromlist=["write_causal_event_owner"]
    ).write_causal_event_owner(planner, owner)

    assert sanitize_great_bow_guard_readiness_event(planner, event_ref) is True
    _path, after_owner = __import__(
        "sword_runtime.causal_event_store", fromlist=["read_causal_event_owner"]
    ).read_causal_event_owner(planner)
    event = after_owner["causal_events"][event_ref]
    assert event["process_kind"] == "great_bow_guard_field_readiness"
    assert event["summary"] == "test summary"
    assert event["delivery"]["target_ref"] == "char_tang_wei"
    assert "formation_ref" not in event
    assert "great_bow_guard_stats" not in event
    assert "issued_loadout_items" not in event
    assert "remaining_shortfalls" not in event
