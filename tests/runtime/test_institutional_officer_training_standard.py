from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from sword_runtime.api.warfare_operations import WarfareCampaignOperations
from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.service_runtime import ProductionSwordRuntime
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.warfare_depth import build_formation_command_structure
from sword_runtime.warfare_depth_integrity import resolve_scoped_formation_profile


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _rules() -> dict:
    return json.loads((_root() / "game/data/mechanics/warfare-organization.json").read_text())


def _policy() -> dict:
    return json.loads((_root() / "game/data/mechanics/officer-representation.json").read_text())


def _operations(campaign: Path, suffix: str) -> WarfareCampaignOperations:
    runtime = ProductionSwordRuntime(campaign, runtime_root=campaign.parent / suffix)
    return WarfareCampaignOperations(runtime)


def _structure_with_scoped_profile(formation: dict) -> dict:
    rules = _rules()
    profile = resolve_scoped_formation_profile(formation, rules)
    adjusted = deepcopy(rules)
    profiles = adjusted.setdefault("formation_profiles", {})
    if profile:
        profiles[formation["formation_ref"]] = deepcopy(dict(profile))
    return build_formation_command_structure(formation, adjusted)


def _cohort_total(row: dict) -> int:
    return (
        sum(int(v) for v in row.get("reserve_by_location", {}).values())
        + sum(int(v) for v in row.get("allocated_by_formation", {}).values())
        + sum(int(v) for v in row.get("allocated_external_by_formation", {}).values())
    )


def test_house_tang_is_institution_wide_and_qin_is_wei_assignment_scoped() -> None:
    policy = _policy()
    scopes = policy["institutional_scopes"]
    assert set(scopes) == {"house_tang", "wei_assigned_qin"}
    assert scopes["house_tang"]["application"] == "institution_wide"
    assert scopes["wei_assigned_qin"]["application"] == "only_while_lawfully_assigned_under_tang_wei_command"
    assert policy["automatic_full_character"]["minimum_persistent_commanded_personnel"] == 500
    assert "full exact named character" in policy["automatic_full_character"]["rule"]


def test_unprofiled_house_and_wei_assigned_qin_inherit_standard_while_unassigned_qin_does_not() -> None:
    house = {
        "formation_ref": "formation_test_house_tang_unprofiled",
        "owner_force_ref": "force_house_tang",
        "personnel": 2400,
        "command_authority": "char_some_house_commander",
    }
    qin_unassigned = {
        "formation_ref": "formation_test_qin_unassigned",
        "owner_force_ref": "force_state_qin",
        "personnel": 2400,
        "command_authority": "char_qin_other_commander",
    }
    qin_wei = {
        "formation_ref": "formation_test_qin_wei_assigned",
        "owner_force_ref": "force_state_qin",
        "personnel": 2400,
        "command_authority": "char_tang_wei",
    }

    for formation in (house, qin_wei):
        profile = resolve_scoped_formation_profile(formation, _rules())
        assert profile
        assert profile["external_unit_command"]["commander_representation"] == "full_character"
        assert profile["external_unit_command"]["commander_billets"] == 1
        structure = _structure_with_scoped_profile(formation)
        assert structure["unit_command"]["representation"] == "full_character_unit_command"

    assert resolve_scoped_formation_profile(qin_unassigned, _rules()) == {}
    generic_qin = build_formation_command_structure(qin_unassigned, _rules())
    assert generic_qin["unit_command"]["representation"] == "aggregate"
    assert all(row["representation"] == "aggregate" for row in generic_qin["internal_hierarchy"])


def test_current_house_and_wei_assigned_qin_units_have_one_full_character_top_commander() -> None:
    rules = _rules()
    for rel in (
        "state/formations/house-tang-infantry-01.json",
        "state/formations/black-banner-01a.json",
    ):
        formation = json.loads((_root() / rel).read_text())
        profile = resolve_scoped_formation_profile(formation, rules)
        unit = profile["external_unit_command"]
        assert unit["commander_billets"] == 1
        assert unit["commander_representation"] == "full_character"
        assert formation["commander_ref"].startswith("char_")
        structure = _structure_with_scoped_profile(formation)
        assert structure["unit_command"]["named_commander_ref"] == formation["commander_ref"]
        assert structure["unit_command"]["effective_billets_staffed"] == 1


def test_controlled_exact_top_commander_has_player_visible_real_stats(campaign: Path) -> None:
    operations = _operations(campaign, "runtime-exact-officer-standard")
    inspected = operations.inspect_game_object("formation_red_lance_a")
    formation = inspected["object"]
    officer_ref = formation["commander_ref"]
    assert officer_ref == "char_duan_jin"

    sheet = operations.person_sheet(officer_ref)
    person = sheet["person"]
    assert sheet["visibility"] == "player_visible_command_service_sheet"
    assert person["representation"] == "full_character"
    assert person["current_formation_id"] == "formation_red_lance_a"
    assert person["command_assignment"]["external_to_fighting_establishment"] is True
    assert person["attributes"]
    assert person["skills"]
    assert person["aptitude"]
    assert "Formation Command" in person["skills"]
    assert "Strength" in person["attributes"]


def test_standing_formation_training_does_not_double_settle_exact_commander(campaign: Path) -> None:
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    formation_ref = "formation_red_lance_a"
    path, raw = planner._load_formation(formation_ref)
    formation = deepcopy(raw)
    before_personnel = int(formation["personnel"])
    commander_ref = str(formation["commander_ref"])
    commander_path = planner.owner_path(commander_ref)
    commander = deepcopy(planner.read(commander_path))
    current = CampaignTime.parse(str(planner.read("state/runtime.json")["world_time"]))

    formation["location_ref"] = "loc_tang_manor_training_ground"
    formation["standing_training_time_credit_hours"] = 8.0
    formation["standing_training_credit_window_start"] = str(current.add_hours(-24))
    formation.pop("standing_training_recovery_through", None)
    planner.put(path, formation)
    commander["current_location"] = "loc_tang_manor_training_ground"
    before_development = deepcopy(commander.get("development_state", {}))
    planner.put(commander_path, commander)

    result = planner._consume_formation_standing_credit(
        formation_ref,
        current,
        "test-institutional-exact-officer-training",
    )
    _path, after = planner._load_formation(formation_ref)
    trained = planner.read(commander_path)

    assert result["consumed_hours"] == 8
    assert int(after["personnel"]) == before_personnel
    assert "delegated_training_last_officer_results" not in after
    assert trained.get("development_state", {}) == before_development
    assert trained.get("activity_contract", {}).get("autonomous_enabled") is True
    assert trained.get("activity_contract", {}).get("training_program_ref")


def test_unified_house_monthly_owner_trains_both_troop_species_without_changing_headcount(campaign: Path) -> None:
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    force = deepcopy(planner.read("state/forces/house-tang.json"))
    before_headcount = int(force["headcount"])
    rows = force["cohort_ledger"]["cohorts"]
    probes = {}
    for role in ("house_infantry", "house_cavalry"):
        cid, row = next((cid, row) for cid, row in rows.items() if row.get("role") == role and _cohort_total(row) > 0)
        probes[role] = (cid, float(row.get("verified_training_hours_per_person", 0.0)))

    planner._fc_train(force, "house_tang_max_sustainable", 1.0, "test-unified-house-institutional-training")

    assert int(force["headcount"]) == before_headcount
    assert set(force["authorized_by_role"]) == {"house_infantry", "house_cavalry"}
    for role, (cid, before_hours) in probes.items():
        assert float(force["cohort_ledger"]["cohorts"][cid].get("verified_training_hours_per_person", 0.0)) > before_hours


def test_generic_state_army_representation_remains_aggregate() -> None:
    rules = _rules()
    assert rules["officer_representation_policy"]["default_representation"] == "aggregate"
    assert rules["formation_command_structure"]["unit_command"]["default_representation"] == "aggregate"
    assert rules["formation_command_structure"]["generic_representation"] == "aggregate"
