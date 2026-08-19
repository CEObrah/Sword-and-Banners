from __future__ import annotations

from sword_runtime.service_runtime import CommandRoutedProductionPlanner
from sword_runtime.training_rates import resolved_activity_regimen, verified_activity_hours_per_cycle

import pytest


def test_registered_major_canon_current_capability_floors_hold(campaign):
    planner = CommandRoutedProductionPlanner(campaign)
    planner._reset()
    calibration = planner.read("game/data/people/canon-capability-calibration.json")
    calibration_ref = calibration["calibration_ref"]
    assert calibration["rules"]["floor_only"] is True
    assert calibration["rules"]["never_reduce_saved_capability"] is True
    assert calibration["rules"]["never_pregrant_future_office_or_history"] is True
    for person_ref, spec in calibration["characters"].items():
        person = planner.read(planner.owner_path(person_ref))
        for field, floor_key in (
            ("aptitude", "aptitude_floors"),
            ("attributes", "attribute_floors"),
            ("skills", "skill_floors"),
        ):
            for key, floor in spec[floor_key].items():
                assert float(person[field].get(key, 0.0)) >= float(floor), (person_ref, field, key)
        assert person["development_state"]["canon_capability_calibration"]["calibration_ref"] == calibration_ref


def test_major_canon_specialized_training_contracts_are_current_only_and_deterministic(campaign):
    planner = CommandRoutedProductionPlanner(campaign)
    planner._reset()
    profiles = planner.read("game/data/mil/recruitment-cohort-profiles.json")
    expected = {
        "char_shin": ("martial_aspirant", "program.martial_aspirant", 205.714286),
        "char_hyou": ("martial_aspirant", "program.martial_aspirant", 205.714286),
        "char_karyoten": ("strategic_apprentice", "program.strategic_apprentice", 205.714286),
        "char_mou_ki": ("household_professional", "program.strategic_apprentice", 205.714286),
        "char_kyoukai": ("elite_professional", "program.elite_martial_operative", 205.714286),
        "char_yotanwa": ("elite_professional", "program.warrior_ruler", 205.714286),
        "char_ei_sei": ("statecraft_intensive", "program.ruler_governance", 205.714286),
    }
    for person_ref, (regimen_ref, program_ref, expected_hours) in expected.items():
        person = planner.read(planner.owner_path(person_ref))
        contract = person["activity_contract"]
        resolved_ref, _regimen = resolved_activity_regimen(person, contract, profiles)
        cadence = int(person["autonomous_activity_state"]["cadence_seconds"])
        assert resolved_ref == regimen_ref
        assert contract["training_program_ref"] == program_ref
        assert verified_activity_hours_per_cycle(person, contract, profiles, cadence) == pytest.approx(expected_hours)
        assert contract.get("future_canon_guaranteed", False) is False


def test_training_fairness_repair_is_recorded_without_world_time_advance(campaign):
    planner = CommandRoutedProductionPlanner(campaign)
    planner._reset()
    meta = planner.read("state/meta.json")
    repair = meta["last_universal_training_repair"]
    assert repair["migration_ref"] == "universal_active_48h_week_v1"
    assert repair["exact_people_caught_up"] == 55
    assert repair["exact_hours_caught_up"] == 25496
    assert repair["aggregate_cohorts_caught_up"] == 101
    assert repair["person_lite_caught_up"] == 38
    assert repair["canon_people_calibrated"] >= 12
    history = planner.read("state/history/events/index.json")
    event = next(row for row in history["events"] if row["event_id"] == repair["event_ref"])
    assert event["kind"] == "explicit_repair"
    assert event["at"] == planner.read("state/runtime.json")["world_time"]
