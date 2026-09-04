from __future__ import annotations

import copy
from pathlib import Path

import pytest

from sword_runtime.production_planner import ProductionCampaignPlanner


def planner_for(root: Path) -> ProductionCampaignPlanner:
    planner = ProductionCampaignPlanner(root)
    planner.PLAYER_ACTOR = str(planner.read("state/meta.json")["player_id"])
    return planner


def _offer(planner: ProductionCampaignPlanner, source_ref: str, custodian_ref: str, count: int, location_ref: str) -> int:
    sp, source0 = planner._load_formation(source_ref)
    source = copy.deepcopy(source0)
    source["location_ref"] = location_ref
    source["surrender_state"] = {
        "status": "offered",
        "offered_to_formation_ref": custodian_ref,
        "offered_personnel": count,
        "offered_at": str(planner._world_time()),
    }
    planner.put(sp, source)
    return int(source0.get("personnel", 0))


def test_capacity_is_shared_across_groups_using_same_custodian(campaign: Path) -> None:
    p = planner_for(campaign)
    cust_ref = "formation_qin_kankoku_central_gate"
    cp, cust0 = p._load_formation(cust_ref)
    cust = copy.deepcopy(cust0)
    cust["location_ref"] = "loc_kankoku_pass"
    cust["personnel"] = 100  # 200 emergency prisoners under registered guard rules.
    p.put(cp, cust)

    first_source = "formation_zhao_retsubi_gate_command"
    _offer(p, first_source, cust_ref, 120, "loc_kankoku_pass")
    first = p._custody_new_group(
        source_formation_ref=first_source,
        custodian_formation_ref=cust_ref,
        count=120,
        at=str(p._world_time()),
    )
    assert first["personnel"] == 120

    second_source = "formation_zhao_border_line"
    before = _offer(p, second_source, cust_ref, 100, "loc_kankoku_pass")
    capacity = p._custody_holding_capacity(cust_ref, "loc_kankoku_pass")
    assert capacity["occupied_by_same_custodian_people"] == 120
    assert capacity["emergency_capacity_people"] == 80
    with pytest.raises(ValueError, match="custody capacity exceeded"):
        p._custody_new_group(
            source_formation_ref=second_source,
            custodian_formation_ref=cust_ref,
            count=100,
            at=str(p._world_time()),
        )
    # Capacity rejection occurs before detaching conserved source bodies.
    assert int(p._load_formation(second_source)[1]["personnel"]) == before


def test_child_location_uses_enclosing_fortification_holding_space(campaign: Path) -> None:
    p = planner_for(campaign)
    cap = p._custody_holding_capacity("formation_qin_kankoku_central_gate", "loc_kanyou_officer_bureau")
    # Kanyou's officer bureau is inside the Kanyou fortified site; detention
    # capacity therefore comes from that enclosing physical fortification rather
    # than treating the office as an infinite/independent jail.
    assert cap["holding_site_ref"] == "loc_kanyou"
    assert cap["physical_fixed_capacity"] is not None
    assert cap["basis"] == "registered_fortification_geometry_and_guard_manpower"
