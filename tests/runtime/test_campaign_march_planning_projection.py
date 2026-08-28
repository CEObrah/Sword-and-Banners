from __future__ import annotations

from sword_runtime.campaign_briefing import build_campaign_dossier, safe_campaign_context
from sword_runtime.campaign_march_planning import project_route_path


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


def test_safe_campaign_context_preserves_bounded_march_planning_projection():
    march_planning = {
        "kind": "staff_route_capacity_baseline",
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


def test_current_campaign_dossier_surfaces_real_route_capacity_baseline(campaign):
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
    safe = safe_campaign_context(dossier)
    assert safe["march_planning"]["kind"] == "staff_route_capacity_baseline"
