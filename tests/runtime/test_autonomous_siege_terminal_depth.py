from __future__ import annotations

import copy

import sword_runtime.strategic_war_operations as swo
from sword_runtime.siege_physics import initial_physical_state


class FakePlanner:
    def __init__(self, *, siege, fort, formations=None, reserve_draw=None, civilians=0):
        self.data = {
            "state/sieges/index.json": {"sieges": {siege["siege_ref"]: "state/sieges/test.json"}},
            "state/sieges/test.json": copy.deepcopy(siege),
            "state/fortifications/test.json": copy.deepcopy(fort),
        }
        self.formations = copy.deepcopy(formations or {})
        self.reserve_draw = copy.deepcopy(reserve_draw or {"consumed": {}, "shortfall": {}})
        self.civilians = int(civilians)

    def read(self, path):
        return copy.deepcopy(self.data[path])

    def put(self, path, value):
        self.data[path] = copy.deepcopy(value)

    def owner_path(self, ref):
        if ref == "fort_test":
            return "state/fortifications/test.json"
        raise ValueError(ref)

    def _load_formation(self, ref):
        if ref not in self.formations:
            raise ValueError(ref)
        return f"state/formations/{ref}.json", copy.deepcopy(self.formations[ref])

    def _siege_defender_reserve_draw(self, fort, *, days, defenders, at):
        return copy.deepcopy(self.reserve_draw)

    def _demographic_site(self, site_ref):
        return "population_test", "state/population/test.json", {}, {"civilian_population": self.civilians}, site_ref


def _profile(*, nested=False):
    layers = [
        {
            "enclosure_ref": "outer_wall",
            "kind": "outer_wall",
            "nesting_depth": 0,
            "fortification": {
                "active": True,
                "constructed_outer_perimeter_km": 4.0,
                "wall_height_m": 8.0,
                "wall_base_thickness_m": 5.0,
                "wall_crown_thickness_m": 3.0,
                "moat_width_m": 0.0,
                "moat_depth_m": 0.0,
                "gate_count": 1,
                "tower_count": 20,
            },
        }
    ]
    if nested:
        layers.append(
            {
                "enclosure_ref": "inner_citadel",
                "kind": "inner_citadel",
                "nesting_depth": 1,
                "fortification": {
                    "active": True,
                    "constructed_outer_perimeter_km": 1.5,
                    "wall_height_m": 9.0,
                    "wall_base_thickness_m": 5.0,
                    "wall_crown_thickness_m": 3.0,
                    "moat_width_m": 0.0,
                    "moat_depth_m": 0.0,
                    "gate_count": 1,
                    "tower_count": 8,
                },
            }
        )
    return {
        "profile_id": "test_profile",
        "current_enclosure_layers": layers,
        "siege_physics": {"moat_required_crossing_for_wheeled_engines": False},
    }


def _owners(*, defenders, relief=0, nested=False):
    profile = _profile(nested=nested)
    physical = initial_physical_state(profile, 100)
    fort = {
        "schema": "sword-fortification",
        "owner_id": "fort_test",
        "fortification_ref": "fort_test",
        "site_ref": "loc_test_fort",
        "location_ref": "loc_test_fort",
        "profile": profile,
        "integrity": 100,
        "physical_state": physical,
    }
    siege = {
        "schema": "sword-siege",
        "owner_id": "siege_test",
        "siege_ref": "siege_test",
        "fortification_ref": "fort_test",
        "attacker_formation_refs": ["formation_attacker"],
        "defender_formation_refs": list(defenders),
        "status": "active",
        "days": 0,
        "deprivation_days": 0,
        "relief_prospect": relief,
        "engineering_works": [],
        "registered_approach_route_refs": [],
        "blockade": {},
    }
    return siege, fort


def _disable_engineering(monkeypatch, *, admissible=False):
    monkeypatch.setattr(swo, "_ensure_material_shipment", lambda *args, **kwargs: None)
    monkeypatch.setattr(swo, "_complete_engineering_work", lambda *args, **kwargs: None)
    monkeypatch.setattr(swo, "ram_access", lambda *args, **kwargs: {"admissible": admissible})


def test_saved_relief_knob_is_ignored_and_fourteen_days_of_moderate_shortage_does_not_force_surrender(monkeypatch):
    _disable_engineering(monkeypatch, admissible=False)
    siege, fort = _owners(defenders=["formation_defender"], relief=100)
    planner = FakePlanner(
        siege=siege,
        fort=fort,
        formations={"formation_defender": {"personnel": 1000, "morale": 95}},
        reserve_draw={
            "consumed": {"grain_kg": 50_000, "water_person_days": 14_000},
            "shortfall": {"grain_kg": 50_000, "water_person_days": 0},
        },
        civilians=5000,
    )

    result = swo.advance_autonomous_siege(
        planner,
        siege_ref="siege_test",
        at="243-BCE-01-01T12:00:00+08:00",
        review_days=14,
        attacker_side="state_qin",
    )
    saved = planner.data["state/sieges/test.json"]

    assert saved["deprivation_days"] == 14
    assert result["deprivation_surrender"] is False
    assert saved["status"] == "active"
    assert saved["surrender_pressure"] < 100.0
    assert saved["surrender_evidence"]["relief_prospect"] == 0
    assert "relief_prospect" not in saved
    assert saved["surrender_evidence"]["relief_evidence"]["basis"] == "exact_friendly_formations_plus_route_time"


def test_severe_water_failure_can_drive_evidence_based_surrender(monkeypatch):
    _disable_engineering(monkeypatch, admissible=False)
    siege, fort = _owners(defenders=["formation_defender"], relief=0)
    planner = FakePlanner(
        siege=siege,
        fort=fort,
        formations={"formation_defender": {"personnel": 1000, "morale": 20}},
        reserve_draw={
            "consumed": {"grain_kg": 100_000, "water_person_days": 0},
            "shortfall": {"grain_kg": 0, "water_person_days": 14_000},
        },
        civilians=10_000,
    )

    result = swo.advance_autonomous_siege(
        planner,
        siege_ref="siege_test",
        at="243-BCE-01-01T12:00:00+08:00",
        review_days=14,
        attacker_side="state_qin",
    )
    saved = planner.data["state/sieges/test.json"]

    assert result["deprivation_surrender"] is True
    assert saved["status"] == "captured"
    assert saved["outcome"] == "defender_surrender_under_siege_pressure"
    assert saved["capture_basis"] == "stateful_deprivation_morale_relief_pressure"
    assert saved["terminal_evidence"]["water_shortfall_fraction"] == 1.0
    assert saved["terminal_evidence"]["pressure"] >= 100.0


def test_unopposed_breach_secures_only_one_nested_enclosure_per_review(monkeypatch):
    _disable_engineering(monkeypatch, admissible=True)
    siege, fort = _owners(defenders=[], nested=True)
    physical = fort["physical_state"]
    physical["gates"]["main_gate"]["status"] = "breached"
    physical["gates"]["main_gate"]["breach_width_m"] = 2.0
    fort["physical_state"] = physical
    planner = FakePlanner(siege=siege, fort=fort)

    result = swo.advance_autonomous_siege(
        planner,
        siege_ref="siege_test",
        at="243-BCE-01-01T12:00:00+08:00",
        review_days=1,
        attacker_side="state_qin",
    )
    saved_siege = planner.data["state/sieges/test.json"]
    saved_fort = planner.data["state/fortifications/test.json"]

    assert result["enclosure_transition"]["advanced"] is True
    assert result["enclosure_transition"]["final_layer_secured"] is False
    assert saved_siege["status"] == "active"
    assert saved_siege["active_enclosure_ref"] == "inner_citadel"
    layers = saved_fort["physical_state"]["enclosure_layers"]
    assert layers[0]["secured_by_attacker"] is True
    assert layers[1].get("secured_by_attacker") is not True


def test_relief_prospect_excludes_nonmobilized_and_forming_units(monkeypatch):
    siege, fort = _owners(defenders=["formation_defender"], relief=0)
    siege["defender_authorities"] = ["state_zhao"]
    formations = {
        "formation_attacker": {"personnel": 10000, "mobilized": True, "status": "mobilized", "location_ref": "loc_attack", "administrative_owner": "state_qin", "command_authority": "state_qin"},
        "formation_defender": {"personnel": 1000, "mobilized": True, "status": "mobilized", "location_ref": "loc_test_fort", "administrative_owner": "state_zhao", "command_authority": "state_zhao"},
        "formation_real_relief": {"personnel": 5000, "mobilized": True, "status": "mobilized", "location_ref": "loc_relief", "administrative_owner": "state_zhao", "command_authority": "state_zhao"},
        "formation_paper_relief": {"personnel": 20000, "mobilized": False, "status": "forming", "location_ref": "loc_relief", "administrative_owner": "state_zhao", "command_authority": "state_zhao"},
    }
    planner = FakePlanner(siege=siege, fort=fort, formations=formations)
    planner.data["state/index/owner-index.json"] = {
        "owners": {ref: f"state/formations/{ref}.json" for ref in formations}
    }
    for ref, formation in formations.items():
        planner.data[f"state/formations/{ref}.json"] = copy.deepcopy(formation)
    monkeypatch.setattr(swo, "shortest_path", lambda *args, **kwargs: {"duration_hours": 48})
    result = swo._derived_relief_prospect(
        planner, siege, "loc_test_fort", at="243-BCE-01-01T12:00:00+08:00"
    )
    assert result["plausible_relief_formation_refs"] == ["formation_real_relief"]
    assert result["plausible_relief_personnel"] == 5000
    assert result["candidate_count"] == 1


def test_relief_prospect_uses_every_reachable_friendly_formation_not_first_four(monkeypatch):
    siege, fort = _owners(defenders=["formation_defender"], relief=0)
    siege["defender_authorities"] = ["state_zhao"]
    formations = {
        "formation_attacker": {"personnel": 10000, "mobilized": True, "status": "mobilized", "location_ref": "loc_attack", "administrative_owner": "state_qin", "command_authority": "state_qin"},
        "formation_defender": {"personnel": 1000, "mobilized": True, "status": "mobilized", "location_ref": "loc_test_fort", "administrative_owner": "state_zhao", "command_authority": "state_zhao"},
    }
    for ordinal in range(1, 6):
        formations[f"formation_relief_{ordinal}"] = {
            "personnel": 1000,
            "mobilized": True,
            "status": "mobilized",
            "location_ref": f"loc_relief_{ordinal}",
            "administrative_owner": "state_zhao",
            "command_authority": "state_zhao",
        }
    planner = FakePlanner(siege=siege, fort=fort, formations=formations)
    planner.data["state/index/owner-index.json"] = {
        "owners": {ref: f"state/formations/{ref}.json" for ref in formations}
    }
    for ref, formation in formations.items():
        planner.data[f"state/formations/{ref}.json"] = copy.deepcopy(formation)

    hours_by_origin = {f"loc_relief_{ordinal}": ordinal * 24 for ordinal in range(1, 6)}
    monkeypatch.setattr(
        swo,
        "shortest_path",
        lambda _read, origin, _site, modes=("formation",): {"duration_hours": hours_by_origin[origin]},
    )

    result = swo._derived_relief_prospect(
        planner, siege, "loc_test_fort", at="243-BCE-01-01T12:00:00+08:00"
    )

    assert result["candidate_count"] == 5
    assert result["plausible_relief_personnel"] == 5000
    assert result["plausible_relief_formation_refs"] == [
        "formation_relief_1",
        "formation_relief_2",
        "formation_relief_3",
        "formation_relief_4",
        "formation_relief_5",
    ]
    assert result["plausible_relief_refs_truncated"] is False
    # The fifth formation must contribute mechanically.  Under the old hidden
    # first-four cap this weighted total was 3375 rather than 4062.
    assert result["weighted_relief_personnel"] == 4062
