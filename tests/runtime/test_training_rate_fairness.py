from __future__ import annotations

from copy import deepcopy

import pytest

from sword_runtime.service_runtime import CommandRoutedProductionPlanner
from sword_runtime.training_rates import resolve_activity_regimen_ref, resolved_activity_regimen, verified_activity_hours_per_cycle


def _resolve(planner, ref: str):
    person = deepcopy(planner.read(planner.owner_path(ref)))
    contract = planner._effective_activity_contract(person)
    profiles = planner.read("game/data/mil/recruitment-cohort-profiles.json")
    regimen_ref, regimen = resolved_activity_regimen(person, contract, profiles)
    cadence = int(person.get("autonomous_activity_state", {}).get("cadence_seconds", 30 * 86400))
    hours = verified_activity_hours_per_cycle(person, contract, profiles, cadence)
    return regimen_ref, regimen, hours


def test_training_standard_is_role_driven_not_allegiance(campaign):
    planner = CommandRoutedProductionPlanner(campaign)
    planner._reset()
    qin_ref, _qin, qin_hours = _resolve(planner, "char_ouki")
    zhao_ref, _zhao, zhao_hours = _resolve(planner, "char_riboku")
    chu_ref, _chu, chu_hours = _resolve(planner, "char_karin")
    assert (qin_ref, zhao_ref, chu_ref) == ("elite_command", "elite_command", "elite_command")
    assert qin_hours == pytest.approx(205.714286)
    assert zhao_hours == pytest.approx(qin_hours)
    assert chu_hours == pytest.approx(qin_hours)


def test_young_commanders_and_elite_martial_operatives_are_not_capped_at_56(campaign):
    planner = CommandRoutedProductionPlanner(campaign)
    planner._reset()
    assert _resolve(planner, "char_mou_ten")[0] == "professional_officer"
    assert _resolve(planner, "char_ou_hon")[0] == "professional_officer"
    assert _resolve(planner, "char_kyoukai")[0] == "professional_officer"
    for ref in ("char_mou_ten", "char_ou_hon", "char_kyoukai"):
        assert _resolve(planner, ref)[2] == pytest.approx(205.714286)


def test_selective_academy_and_current_young_commander_standards_resolve_from_saved_path(campaign):
    planner = CommandRoutedProductionPlanner(campaign)
    planner._reset()
    assert _resolve(planner, "char_mou_ki")[0] == "household_professional"
    assert _resolve(planner, "char_shin")[0] == "professional_officer"
    for ref in ("char_mou_ki", "char_shin"):
        assert _resolve(planner, ref)[2] == pytest.approx(205.714286)

    # Hyou is already dead by the current campaign baseline. A dead historical
    # character must not remain an active training-rate fixture.
    hyou = planner.read(planner.owner_path("char_hyou"))
    assert hyou["life_status"] == "dead"
    assert hyou["activity_contract"]["autonomous_enabled"] is False
    assert hyou["autonomous_activity_state"]["enabled"] is False
    assert "next_due" not in hyou["autonomous_activity_state"]


def test_house_tang_formation_commander_uses_role_regimen_on_same_clock(campaign):
    planner = CommandRoutedProductionPlanner(campaign)
    planner._reset()
    regimen_ref, _regimen, hours = _resolve(planner, "char_duan_jin")
    # Duan Jin has an explicit non-generic professional-officer activity contract.
    # House affiliation improves institutional quality without overriding that role regimen.
    assert regimen_ref == "professional_officer"
    assert hours == pytest.approx(205.714286)


def test_karyoten_now_uses_professional_officer_clock_as_hi_shin_strategist(campaign):
    planner = CommandRoutedProductionPlanner(campaign)
    planner._reset()
    regimen_ref, _regimen, hours = _resolve(planner, "char_karyoten")
    assert regimen_ref == "professional_officer"
    assert hours == pytest.approx(205.714286)


def test_resolved_regimen_quality_matches_resolved_hours(campaign):
    planner = CommandRoutedProductionPlanner(campaign)
    planner._reset()
    regimen_ref, regimen, hours = _resolve(planner, "char_ouki")
    assert regimen_ref == "elite_command"
    assert hours == pytest.approx(205.714286)
    assert "facility_grade" not in regimen
    assert regimen["feedback_grade"] == "expert"


def test_regular_professional_regimen_is_not_the_reserve_maintenance_ceiling(campaign):
    planner = CommandRoutedProductionPlanner(campaign)
    planner._reset()
    profiles = planner.read("game/data/mil/recruitment-cohort-profiles.json")
    regular = profiles["training_regimens"]["regular_army"]
    reserve = profiles["training_regimens"]["reserve_maintenance"]
    assert regular["deliberate_hours_per_30d"] == pytest.approx(205.714286)
    assert regular["role_exposure_hours_per_30d"] == 96.0
    assert reserve["deliberate_hours_per_30d"] == 56.0
    assert reserve["role_exposure_hours_per_30d"] == 48.0
    assert regular["deliberate_hours_per_30d"] > reserve["deliberate_hours_per_30d"]
    for ref in ("household_professional", "house_tang_max_sustainable", "professional_officer", "elite_command", "elite_martial", "elite_professional", "martial_aspirant", "strategic_apprentice", "statecraft_intensive", "strategist_academy", "intensive_martial_aspirant"):
        row = profiles["training_regimens"][ref]
        assert row["deliberate_hours_per_30d"] == pytest.approx(205.714286)
        assert row["deliberate_hours_per_7d"] == pytest.approx(48.0)
        assert row["role_exposure_hours_per_30d"] == pytest.approx(96.0)
    assert regular["role_exposure_hours_per_30d"] > reserve["role_exposure_hours_per_30d"]


def test_training_regimen_resolution_does_not_read_affiliation_as_a_multiplier(campaign):
    planner = CommandRoutedProductionPlanner(campaign)
    planner._reset()
    profiles = planner.read("game/data/mil/recruitment-cohort-profiles.json")
    contract = {"mode": "standing_role_training", "training_regimen_ref": "regular_army"}
    refs = []
    for affiliation in ("Qin", "Zhao", "Chu", "Wei", "Han", "Yan", "Qi", "House Tang"):
        person = {"schema": "sab_character", "affiliation": affiliation, "role_archetype": "great_general"}
        refs.append(resolve_activity_regimen_ref(person, contract, profiles))
    assert refs == ["elite_command"] * len(refs)
