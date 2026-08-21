from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from sword_runtime.geography import (
    enclosing_fortification_site,
    nearest_reachable_destination,
    shortest_path,
)
from validate_world_geography import validate

STATES = ("qin", "zhao", "chu", "wei", "han", "yan", "qi")


def j(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def read(path: str):
    return j(path)


def test_systemic_world_geography_validator_passes():
    assert validate(ROOT) == []


def test_strategic_routes_never_enter_non_strategic_interior_locations():
    locs = {row["ref"]: row for row in j("game/data/world/locations.json")["locations"]}
    routes = j("game/data/world/routes.json")
    for edge in routes["routes"]:
        assert edge["scope"] == "strategic"
        assert locs[edge["a"]]["strategic_node"] is True
        assert locs[edge["b"]]["strategic_node"] is True
    assert all(edge["scope"] == "local" for edge in routes["local_routes"])
    interior = {ref for ref, row in locs.items() if not row.get("strategic_node")}
    assert not any(edge["a"] in interior or edge["b"] in interior for edge in routes["routes"])


def test_nearest_reachable_destination_matches_individual_shortest_paths():
    pick = nearest_reachable_destination(
        read,
        "loc_kankoku_pass",
        ("loc_tang_manor_outer_gate", "loc_kanyou"),
        modes=("formation",),
    )
    assert pick["destination"] == "loc_kanyou"
    assert pick["duration_hours"] == shortest_path(
        read, "loc_kankoku_pass", "loc_kanyou", modes=("formation",)
    )["duration_hours"]


def test_tang_manor_is_branch_off_kankoku_to_kanyou_trunk():
    trunk = shortest_path(read, "loc_kankoku_pass", "loc_kanyou", modes=("formation",))
    assert trunk["path"] == ["loc_kankoku_pass", "loc_kanyou"]
    assert not any("tang_manor" in ref for ref in trunk["route_refs"])
    branch = shortest_path(read, "loc_kanyou", "loc_tang_manor_outer_gate", modes=("formation",))
    assert "route_kanyou_tang_manor_gate" in branch["route_refs"]
    assert "loc_tang_manor_outer_gate" == branch["path"][-1]


def test_external_to_internal_tang_movement_uses_access_node_then_local_route():
    plan = shortest_path(read, "loc_kanyou", "loc_tang_manor_garrison_yard", modes=("formation",))
    assert plan["path"][:2] == ["loc_kanyou", "loc_tang_manor_outer_gate"]
    assert "loc_tang_manor" in plan["path"]
    assert plan["path"][-1] == "loc_tang_manor_garrison_yard"
    assert plan["route_refs"][0] == "route_kanyou_tang_manor_gate"
    assert any(ref.startswith("local_tang_") for ref in plan["route_refs"][1:])



def test_tang_manor_family_hall_uses_direct_inner_citadel_approach():
    plan = shortest_path(read, "loc_tang_manor", "loc_tang_manor_inner_citadel_family_hall", modes=("foot",))
    assert plan["path"] == [
        "loc_tang_manor",
        "loc_tang_inner_citadel_gate",
        "loc_tang_inner_citadel",
        "loc_tang_manor_inner_citadel_family_hall",
    ]
    assert plan["route_refs"] == [
        "local_tang_estate_inner_citadel_approach",
        "route_inner_citadel_gate_access",
        "local_tang_estate_family_hall",
    ]
    assert plan["duration_hours"] == 3
    assert "loc_sword_manor" not in plan["path"]

def test_route_closure_forces_real_alternate_and_full_isolation_requires_all_approaches_closed():
    overlay = {
        "state/territory/control.json": copy.deepcopy(j("state/territory/control.json")),
    }
    overlay["state/territory/control.json"]["route_states"]["route_kanyou_tang_manor_gate"]["status"] = "closed"

    def closed_read(path: str):
        return overlay.get(path, j(path))

    alternate = shortest_path(closed_read, "loc_kanyou", "loc_tang_manor_outer_gate", modes=("convoy",))
    assert "route_kanyou_tang_manor_gate" not in alternate["route_refs"]
    assert "route_tang_gate_capital_basin" in alternate["route_refs"]
    overlay["state/territory/control.json"]["route_states"]["route_tang_gate_capital_basin"]["status"] = "closed"
    with pytest.raises(ValueError, match="no usable route"):
        shortest_path(closed_read, "loc_kanyou", "loc_tang_manor_outer_gate", modes=("convoy",))


def test_population_and_private_economy_are_attached_only_to_demographic_owners():
    locs = {row["ref"]: row for row in j("game/data/world/locations.json")["locations"]}
    for state in STATES:
        pop = j(f"state/population/{state}.json")
        sites = pop["local_population"]["sites"]
        econ = j(f"state/economy/private/{state}.json")
        regions = econ["local_regions"]["regions"]
        assert set(regions) == set(sites)
        assert all(locs[ref]["national_population_eligible"] for ref in sites)
        assert all(locs[ref]["national_population_eligible"] for ref in regions)
        # Derived current-close display cache must not reintroduce invalid facility geography.
        assert all(locs[ref]["national_population_eligible"] for ref in econ.get("production_runtime", {}).get("last_regional_close", {}))


def test_state_force_disposition_and_mount_reserves_conserve_exact_owners():
    for state in STATES:
        force = j(f"state/forces/state-{state}.json")
        spatial: dict[str, int] = {}
        for roles in force["available_by_location"].values():
            for role, n in roles.items():
                spatial[role] = spatial.get(role, 0) + int(n)
        assert spatial == force["available_by_role"]

        mounts = j(f"state/mounts/{state}.json")
        reserve: dict[str, int] = {}
        for types in mounts["regional_reserve"].values():
            for typ, n in types.items():
                reserve[typ] = reserve.get(typ, 0) + int(n)
        allocated: dict[str, int] = {}
        for types in mounts["allocated_to_formations"].values():
            for typ, n in types.items():
                allocated[typ] = allocated.get(typ, 0) + int(n)
        assert {typ: reserve.get(typ, 0) + allocated.get(typ, 0) for typ in mounts["types"]} == mounts["types"]


def test_four_bastion_corps_are_permanent_house_tang_force_owners():
    owners = j("state/index/owner-index.json")["owners"]
    expected = {
        "force_bastion_iron_wall": 75000,
        "force_bastion_red_thunder": 16000,
        "force_bastion_white_blade": 10000,
        "force_bastion_stone_spear": 9000,
    }
    corps = [j(owners[ref]) for ref in expected]
    assert sum(int(c["headcount"]) for c in corps) == 110000
    assert all(c["administrative_owner"] == "house_tang" for c in corps)
    assert all(c["institution_ref"] == "institution_four_bastion_corps" for c in corps)
    assert all(c.get("contract_ref") is None for c in corps)


def test_capability_profiles_do_not_materialize_parallel_state_owners():
    cap_dir = ROOT / "state/manpower-capability"
    assert not cap_dir.exists() or not list(cap_dir.glob("*.json"))
    for path in (ROOT / "state/merc").glob("*.json"):
        doc = j(path.relative_to(ROOT).as_posix())
        for pool in doc.get("troop_pools", []) if isinstance(doc.get("troop_pools"), list) else []:
            assert "capability_ref" not in pool
            assert isinstance(pool.get("capability"), dict)
    quanrong = j("game/data/world/minor-polities.json")["polities"]["minor_polity_quanrong"]
    assert quanrong["representation"] == "living exact minor polity"
    owners = j("state/index/owner-index.json")["owners"]
    assert quanrong["exact_population_ref"] in owners
    assert quanrong["exact_force_ref"] in owners


def test_tang_child_facilities_inherit_parent_fortification_without_duplicate_walls():
    assert enclosing_fortification_site(read, "loc_tang_manor_garrison_yard") == "loc_tang_inner_citadel"
    assert enclosing_fortification_site(read, "loc_tang_manor_training_ground") == "loc_sword_manor"
    siege = j("state/inv/tang-manor-siege-inventory.json")
    assert siege["fortification_site_ref"] == "loc_tang_manor"
    profiles = {p["site_ref"]: p for p in j("game/data/world/fortification-profiles.json")["profiles"]}
    assert profiles["loc_tang_manor"]["profile_id"] == siege["fortification_profile_ref"]


def test_kankoku_chokepoint_controls_only_explicit_real_edges():
    routes = {row["ref"]: row for row in j("game/data/world/routes.json")["routes"]}
    profile = next(p for p in j("game/data/world/fortification-profiles.json")["profiles"] if p["site_ref"] == "loc_kankoku_pass")
    assert profile["route_control_refs"]
    for ref in profile["route_control_refs"]:
        assert routes[ref]["control_site_ref"] == "loc_kankoku_pass"


def test_player_safe_map_context_exposes_only_current_static_containment(campaign):
    from sword_runtime.api.operations import CampaignOperations
    from sword_runtime.service_runtime import ProductionSwordRuntime

    runtime = ProductionSwordRuntime(campaign, runtime_root=campaign.parent / "runtime-map-context")
    operations = CampaignOperations(runtime)
    context = operations.play_context()
    player = runtime.store.read_json("state/player.json")
    current = player["location"]
    assert context["map_context"]["location_ref"] == current
    assert context["map_context"]["visibility"] == "current_place_static_geography_only"
    assert current in context["permitted_object_refs"]
    inspected = operations.inspect_game_object(current)
    assert inspected["visibility"] == "player_current_map_static_geography"
    locations = {row["ref"]: row for row in j("game/data/world/locations.json")["locations"]}
    assert inspected["object"]["parent_ref"] == locations[current].get("parent_ref")
    assert "enemy_disposition" in inspected["hidden_current_state_excluded"]
    assert "route_status" in inspected["hidden_current_state_excluded"]
    assert "stockpiles" in inspected["hidden_current_state_excluded"]


def test_hostile_formation_can_reach_tang_access_but_not_teleport_behind_fortification(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner

    planner = ProductionCampaignPlanner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    zhao_path = "state/states/zhao.json"
    zhao = copy.deepcopy(planner.read(zhao_path))
    zhao.setdefault("war_intents", []).append({
        "intent_ref": "test_war_intent_tang_access",
        "status": "authorized",
        "target_ref": "state_qin",
        "location_ref": "loc_tang_manor_outer_gate",
        "kind": "territorial_control",
        "objective": "test hostile access boundary",
    })
    planner.put(zhao_path, zhao)
    formation = {"formation_ref": "formation_test_zhao_access", "administrative_owner": "state_zhao"}

    # A hostile formation may reach the strategic gate to contest the site.
    planner._validate_formation_transit(formation, "loc_tang_manor_outer_gate", at)
    # It may not use the internal road as a teleport behind the still-hostile walls.
    with pytest.raises(PermissionError, match="behind hostile enclosing fortification"):
        planner._validate_formation_transit(formation, "loc_tang_manor_garrison_yard", at)

    territory = copy.deepcopy(planner.read("state/territory/control.json"))
    territory["sites"]["loc_tang_manor"]["controller"] = "state_zhao"
    planner.put("state/territory/control.json", territory)
    # Taking the outer estate does not teleport an enemy through Sword Manor
    # and the Inner Citadel. Each nested fortified layer remains an independent
    # access boundary until its own physical control changes.
    with pytest.raises(PermissionError, match="behind hostile enclosing fortification"):
        planner._validate_formation_transit(formation, "loc_tang_manor_garrison_yard", at)
    territory = copy.deepcopy(planner.read("state/territory/control.json"))
    territory["sites"]["loc_sword_manor"]["controller"] = "state_zhao"
    territory["sites"]["loc_tang_inner_citadel"]["controller"] = "state_zhao"
    planner.put("state/territory/control.json", territory)
    planner._validate_formation_transit(formation, "loc_tang_manor_garrison_yard", at)


def test_current_operations_resolve_to_real_locations_and_formations():
    locations = {row["ref"] for row in j("game/data/world/locations.json")["locations"]}
    formations = {
        (row.get("formation_ref") or row.get("ref") or row.get("owner_id"))
        for row in (json.loads(path.read_text(encoding="utf-8")) for path in (ROOT / "state/formations").glob("*.json"))
    }
    index = j("state/operations/index.json")["operations"]
    for op_ref, rel in index.items():
        op = j(rel)
        assert op["operation_ref"] == op_ref
        assert op["location_ref"] in locations
        assert set(op.get("formation_refs", [])).issubset(formations)
        assert not any(key in op for key in ("headcount", "manpower", "bodies"))


def test_workflow_route_refs_are_explicitly_not_geographic_authority():
    contacts = j("game/data/politics/contact-routes.json")
    assert contacts["geographic_route_authority"] is False
    assert contacts["route_domain"] == "institutional_contact"
    processes = j("state/index/institutional-process-routing.json")
    assert processes["authority"] is False
    assert processes["geographic_route_authority"] is False
    assert processes["route_domain"] == "institutional_process"
    runtime = j("state/runtime.json")
    for host in runtime.get("hosts", {}).values():
        if not isinstance(host, dict) or not isinstance(host.get("route_ref"), str):
            continue
        if host["route_ref"].startswith("contact_"):
            assert host["route_domain"] == "institutional_contact"
        if host["route_ref"].startswith("process_"):
            assert host["route_domain"] == "institutional_process"
