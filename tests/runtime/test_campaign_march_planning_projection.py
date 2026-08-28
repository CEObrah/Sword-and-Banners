from __future__ import annotations

from sword_runtime.campaign_briefing import build_campaign_dossier, safe_campaign_context
from sword_runtime.campaign_march_planning import _campaign_command_hierarchy, project_route_path


def _read(path: str):
    if path == "game/data/world/routes.json":
        return {
            "routes": [
                {
                    "ref": "route_test",
                    "a": "loc_a",
                    "b": "loc_b",
                    "hours": 6,
                    "modes": ["formation", "convoy"],
                    "road_quality": "maintained",
                    "terrain": "plain",
                    "scope": "strategic",
                    "physical_geometry": {
                        "length_km": 18.0,
                        "surface": "maintained_earth",
                        "usable_road_width_m": 5.5,
                        "formation_files_abreast_baseline": 4,
                        "daily_troop_throughput": 32000,
                        "daily_wagon_throughput": 1400,
                        "maximum_sustained_grade_percent": 12.0,
                    },
                }
            ],
            "local_routes": [],
        }
    if path == "game/data/world/locations.json":
        return {"locations": [{"ref": "loc_a", "name": "A"}, {"ref": "loc_b", "name": "B"}]}
    raise KeyError(path)


def test_route_projection_exposes_physical_capacity_without_inventing_orders():
    projected = project_route_path(
        _read,
        {
            "path": ["loc_a", "loc_b"],
            "route_refs": ["route_test"],
            "edge_modes": ["formation"],
            "edge_hours": [6],
            "duration_hours": 6,
        },
        strength=40000,
    )
    segment = projected["segments"][0]
    assert segment["from_name"] == "A"
    assert segment["to_name"] == "B"
    assert segment["physical_geometry"]["usable_road_width_m"] == 5.5
    assert segment["physical_geometry"]["daily_troop_throughput"] == 32000
    assert segment["physical_geometry"]["daily_wagon_throughput"] == 1400
    assert segment["troop_clearance_days_floor"] == 2
    assert "assigned_route" not in projected
    assert "departure_time" not in projected
    assert "required_wagons" not in projected


def test_campaign_hierarchy_nests_intact_armies_under_supreme_command():
    hierarchy = _campaign_command_hierarchy(
        [
            {
                "command_ref": "cmd_main",
                "commander_ref": "char_main",
                "commander_name": "Main",
                "objective_ref": "loc_anchor",
                "objective_name": "Anchor",
                "personnel": 40000,
            },
            {
                "command_ref": "cmd_detached",
                "commander_ref": "char_detached",
                "commander_name": "Detached",
                "objective_ref": "loc_secondary",
                "objective_name": "Secondary",
                "personnel": 20000,
            },
        ],
        [
            {
                "command_ref": "cmd_reserve",
                "commander_ref": "char_reserve",
                "commander_name": "Reserve",
                "personnel": 10000,
            }
        ],
        strategic_anchor="loc_anchor",
    )

    assert hierarchy["kind"] == "supreme_campaign_field_army"
    assert hierarchy["root_role"] == "supreme_campaign_command"
    assert hierarchy["subordinate_command_refs"] == ["cmd_main", "cmd_detached", "cmd_reserve"]
    assert hierarchy["main_body_command_refs"] == ["cmd_main"]
    assert [row["command_ref"] for row in hierarchy["operational_detachments"]] == ["cmd_detached"]
    assert hierarchy["operational_detachments"][0]["objective_ref"] == "loc_secondary"
    assert hierarchy["strategic_reserve_command_refs"] == ["cmd_reserve"]
    assert hierarchy["state_owned_strength"] == 70000
    assert "remain under the campaign supreme command" in hierarchy["subordination_rule"]
    assert "does not make it an independent campaign" in hierarchy["separation_rule"]


def test_safe_campaign_context_preserves_bounded_march_planning_projection():
    march_planning = {
        "kind": "staff_route_capacity_baseline",
        "campaign_scheme": {
            "kind": "pre_entry_campaign_staff_scheme",
            "objective_count": 1,
            "objectives": [{"objective_ref": "loc_b", "objective_name": "B"}],
        },
        "command_routes": [{"operation_ref": "operation_test", "duration_hours": 6}],
        "shared_bottlenecks": [],
        "authority_rule": "planning projection only",
    }
    safe = safe_campaign_context(
        {
            "arc_ref": "arc_test",
            "target_state_ref": "state_test",
            "objective": "test",
            "own": {"strength": 1000, "assigned_strength": 1000, "auxiliary_strength": 0, "location_refs": ["loc_a"]},
            "friendly_total_strength": 1000,
            "other_friendly_participants": [],
            "campaign_commander_ref": None,
            "campaign_commander_name": None,
            "coordination_authority_ref": None,
            "operational_area": {"strategic_target_ref": "loc_b"},
            "enemy_intelligence": {},
            "march_planning": march_planning,
        }
    )
    assert safe["march_planning"] == march_planning


def test_current_campaign_dossier_surfaces_real_campaign_scheme_and_route_capacity(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner

    planner = RepositoryCommandPlanner(campaign)
    dossier = build_campaign_dossier(planner, "operation_arc_131572c4e8a2892bbc")
    planning = dossier["march_planning"]
    assert planning["kind"] == "staff_route_capacity_baseline"
    assert planning["command_routes"]
    assert planning["strategic_target_ref"] == dossier["operational_area"]["strategic_target_ref"]
    assert any(route["segments"] for route in planning["command_routes"])
    assert any(
        segment["physical_geometry"].get("daily_troop_throughput")
        for route in planning["command_routes"]
        for segment in route["segments"]
    )
    assert "does not assign a route" in planning["authority_rule"]

    scheme = planning["campaign_scheme"]
    assert scheme["kind"] == "pre_entry_campaign_staff_scheme"
    assert scheme["strategic_anchor_ref"] == dossier["operational_area"]["strategic_target_ref"]
    assert scheme["primary_objective_ref"] == scheme["strategic_anchor_ref"]
    assert scheme["objective_count"] == len(scheme["objectives"])
    assert scheme["objective_count"] >= 1
    assert scheme["command_assignments"]
    assert scheme["operational_end_state"]["required_objective_refs"]
    assert "Political war termination" in scheme["operational_end_state"]["war_termination_rule"]
    assert "hidden enemy deployments are not used" in scheme["planning_basis"]
    assert "does not issue an order" in scheme["authority_rule"]

    hierarchy = scheme["command_hierarchy"]
    assert hierarchy["kind"] == "supreme_campaign_field_army"
    assert hierarchy["root_role"] == "supreme_campaign_command"
    planned_command_refs = {
        row["command_ref"]
        for row in scheme["command_assignments"] + scheme["strategic_reserve_commands"]
    }
    assert set(hierarchy["subordinate_command_refs"]) == planned_command_refs
    assert set(hierarchy["main_body_command_refs"]) == {
        row["command_ref"]
        for row in scheme["command_assignments"]
        if row["objective_ref"] == scheme["primary_objective_ref"]
    }
    assert set(hierarchy["strategic_reserve_command_refs"]) == {
        row["command_ref"] for row in scheme["strategic_reserve_commands"]
    }
    assert {row["command_ref"] for row in hierarchy["operational_detachments"]} == {
        row["command_ref"]
        for row in scheme["command_assignments"]
        if row["objective_ref"] != scheme["primary_objective_ref"]
    }
    assert hierarchy["state_owned_strength"] == scheme["state_owned_planned_strength"]
    assert "remain under the campaign supreme command" in hierarchy["subordination_rule"]
    assert "internal command integrity alone does not make it an independent campaign" in hierarchy["separation_rule"]

    # Sanyou is the strategic anchor for a regional campaign, not the whole
    # campaign geography compressed into one city node.
    assert scheme["campaign_scope_kind"] == "regional_campaign"
    assert scheme["campaign_region_ref"] == "loc_wei_regional_02"
    assert scheme["campaign_region_name"] == "Sanyou Region"
    assert scheme["geography_region_name"] == "Wei Western Corridor"
    assert scheme["strategic_anchor_ref"] == "loc_sanyou"
    assert scheme["strategic_anchor_name"] == "Sanyou"
    assert planning["campaign_region_ref"] == scheme["campaign_region_ref"]
    assert planning["campaign_region_name"] == scheme["campaign_region_name"]
    assert scheme["objective_count"] >= 2
    assert any(row["objective_ref"] != "loc_sanyou" for row in scheme["objectives"])
    assert "anchor alone is not equivalent" in scheme["operational_end_state"]["success_condition"]

    expected_private = sum(int(row.get("auxiliary_strength", 0) or 0) for row in dossier["friendly_participants"])
    assert scheme["excluded_non_state_strength"] == expected_private
    planned_refs = {
        ref
        for row in scheme["command_assignments"] + scheme["strategic_reserve_commands"]
        for ref in row["formation_refs"]
    }
    assert not planned_refs.intersection(set(scheme["excluded_non_state_formation_refs"]))

    reserve_command_refs = {row["command_ref"] for row in scheme["strategic_reserve_commands"]}
    routed_command_refs = {row.get("command_ref") for row in planning["command_routes"]}
    assert reserve_command_refs.isdisjoint(routed_command_refs)

    assigned_objectives = {row["objective_ref"] for row in scheme["command_assignments"]}
    if scheme["objective_count"] > 1:
        assert len(assigned_objectives) > 1
        assert any(ref != scheme["primary_objective_ref"] for ref in assigned_objectives)

    safe = safe_campaign_context(dossier)
    assert safe["march_planning"]["campaign_scheme"]["kind"] == "pre_entry_campaign_staff_scheme"
    assert safe["march_planning"]["campaign_scheme"]["command_hierarchy"]["kind"] == "supreme_campaign_field_army"