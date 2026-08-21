from __future__ import annotations
import pytest

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


def test_house_tang_and_sword_manor_are_institution_wide_but_qin_is_wei_assignment_scoped():
    policy = _policy()
    scopes = policy["institutional_scopes"]
    assert scopes["house_tang"]["application"] == "institution_wide"
    assert scopes["sword_manor"]["application"] == "institution_wide"
    assert scopes["wei_assigned_qin"]["application"] == "only_while_lawfully_assigned_under_tang_wei_command"
    assert set(policy["automatic_full_character"]["roles"]) == {
        "army_commander",
        "army_deputy",
        "persistent_unit_commander",
        "persistent_unit_deputy",
    }


def test_unprofiled_house_and_sword_formations_inherit_standard_while_unassigned_qin_does_not():
    house = {
        "formation_ref": "formation_test_house_tang_unprofiled",
        "owner_force_ref": "force_house_tang",
        "personnel": 2400,
        "command_authority": "char_some_house_commander",
    }
    sword = {
        "formation_ref": "formation_test_sword_manor_unprofiled",
        "owner_force_ref": "force_sword_manor",
        "personnel": 1500,
        "command_authority": "char_some_sword_commander",
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

    for formation in (house, sword, qin_wei):
        profile = resolve_scoped_formation_profile(formation, _rules())
        assert profile
        assert profile["external_unit_command"]["commander_representation"] == "full_character"
        assert profile["external_unit_command"]["deputy_representation"] == "full_character"
        assert all(
            row["representation"] == ("person_lite" if row["scale"] in {1000, 500} else "aggregate")
            for row in profile["internal_hierarchy"]
        )
        structure = _structure_with_scoped_profile(formation)
        assert structure["unit_command"]["representation"] == "full_character_unit_command"
        by_scale = {row["scale"]: row["representation"] for row in structure["internal_hierarchy"]}
        if formation["personnel"] > 1000:
            assert by_scale[1000] == "person_lite"
        if formation["personnel"] > 500:
            assert by_scale[500] == "person_lite"
        assert by_scale[100] == "aggregate"

    assert resolve_scoped_formation_profile(qin_unassigned, _rules()) == {}
    generic_qin = build_formation_command_structure(qin_unassigned, _rules())
    assert generic_qin["unit_command"]["representation"] == "aggregate"
    assert all(row["representation"] == "aggregate" for row in generic_qin["internal_hierarchy"])


def test_scoped_command_hierarchy_uses_full_unit_deputies_and_person_lite_1000_500():
    rules = _rules()
    qin = rules["formation_profiles"]["formation_qin_wei_unit_01"]
    qin_unit = qin["external_unit_command"]
    assert qin_unit["commander_representation"] == "full_character"
    assert qin_unit["deputy_representation"] == "full_character"
    assert [(row["scale"], row["representation"]) for row in qin["internal_hierarchy"]] == [
        (1000, "person_lite"),
        (500, "person_lite"),
        (100, "aggregate"),
    ]

    guard = rules["formation_profiles"]["formation_tang_wei_house_guard"]
    assert guard["external_unit_command"]["commander_representation"] == "full_character"
    assert guard["external_unit_command"]["deputy_representation"] == "full_character"
    assert [(row["scale"], row["representation"]) for row in guard["internal_hierarchy"]] == [
        (1000, "person_lite"),
        (500, "person_lite"),
        (100, "aggregate"),
    ]


def test_controlled_person_lite_officer_has_player_visible_real_stats(campaign: Path):
    operations = _operations(campaign, "runtime-person-lite-officer-standard")
    context = operations.play_context()
    inspected = operations.inspect_game_object("formation_tang_wei_house_guard")
    officers = inspected["object"].get("person_lite_officers", [])
    internal = [row for row in officers if row.get("role") in {"internal_1000_commander", "internal_500_commander"}]
    assert internal
    officer_ref = internal[0]["person_ref"]
    assert officer_ref in context["permitted_person_ids"]

    sheet = operations.person_sheet(officer_ref)
    person = sheet["person"]
    assert sheet["visibility"] == "player_visible_command_service_sheet"
    assert person["representation"] == "person_lite"
    assert person["current_formation_id"] == "formation_tang_wei_house_guard"
    assert person["attributes"]
    assert person["skills"]
    assert person["aptitude"]
    assert "Formation Command" in person["skills"]
    assert "Strength" in person["attributes"]


def test_standing_formation_training_delegates_registered_program_development_to_person_lite_officers(campaign: Path):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    formation_ref = "formation_tang_wei_house_guard"
    path, raw = planner._load_formation(formation_ref)
    formation = deepcopy(raw)
    before_personnel = int(formation["personnel"])
    current = CampaignTime.parse(str(planner.read("state/runtime.json")["world_time"]))
    # This regression exercises actual delegated training, so put the whole
    # formation at a current built training site. A deployed formation without a
    # registered field/permanent training area correctly receives zero facility hours.
    formation["location_ref"] = "loc_sword_manor"
    formation["standing_training_time_credit_hours"] = 8.0
    formation["standing_training_credit_window_start"] = str(current.add_hours(-24))
    formation.pop("standing_training_recovery_through", None)
    planner.put(path, formation)

    index_before = planner.read("state/cmd/command-personnel.json")
    probe_ref = formation["embedded_person_refs"][0]
    probe_before = planner.read(index_before["record_index"][probe_ref])
    probe_hours_before = float(probe_before.get("development_state", {}).get("verified_training_hours", 0.0))

    result = planner._consume_formation_standing_credit(
        formation_ref,
        current,
        "test-institutional-adaptive-officer-training",
    )
    _path, after = planner._load_formation(formation_ref)

    assert result["consumed_hours"] == 8
    assert int(after["personnel"]) == before_personnel
    assert "delegated_training_last_officer_results" not in after, "formation hot state must not retain a write-only per-officer training receipt"

    index = planner.read("state/cmd/command-personnel.json")
    officer_ref = probe_ref
    record_path = index["record_index"][officer_ref]
    officer = planner.read(record_path)
    assert officer["schema"] == "person-lite"
    assert officer["command_assignment"]["external_to_fighting_strength"] is False
    assert officer["stats"]["attributes"]
    assert officer["stats"]["skills"]
    assert officer["development_state"]["verified_training_hours"] >= probe_hours_before + 8.0
    assert officer["development_state"].get("last_training_program_ref")
    assert "training_history" not in officer["development_state"]


def test_sword_manor_monthly_owner_persists_and_trains_all_internal_officers(campaign: Path):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    force = deepcopy(planner.read("state/forces/sword-manor.json"))
    before_headcount = int(force["headcount"])
    refs = sorted(
        ref
        for ref in force["materialized_people"]
        if ref.startswith("officer.sword_manor.") and (".1000." in ref or ".500." in ref)
    )
    assert len(refs) == 89

    probe_ref = refs[0]
    index_before = planner.read("state/cmd/command-personnel.json")
    probe_before = planner.read(index_before["record_index"][probe_ref])
    inherited_hours = float(probe_before.get("development_state", {}).get("verified_training_hours", 0.0))

    planner._fc_train(
        force,
        "house_tang_max_sustainable",
        1.0,
        "test-sword-manor-institutional-smart-training",
    )

    assert int(force["headcount"]) == before_headcount
    index = planner.read("state/cmd/command-personnel.json")
    routed_paths = [index["record_index"].get(ref) for ref in refs]
    assert all(isinstance(path, str) and path for path in routed_paths)

    record = planner.read(index["record_index"][probe_ref])
    assert record["schema"] == "person-lite"
    assert record["command_assignment"]["external_to_fighting_strength"] is False
    assert record["stats"]["attributes"]
    assert record["stats"]["skills"]
    assert float(record["development_state"]["verified_training_hours"]) - inherited_hours == pytest.approx(205.714, abs=1e-3)
    assert record["development_state"]["verified_role_exposure_hours"] > 0.0
    assert record["development_state"]["last_training"]
    assert "training_history" not in record["development_state"]


def test_generic_state_army_representation_remains_aggregate():
    rules = _rules()
    assert rules["officer_representation_policy"]["default_representation"] == "aggregate"
    assert rules["formation_command_structure"]["unit_command"]["default_representation"] == "aggregate"
    assert rules["formation_command_structure"]["generic_representation"] == "aggregate"
