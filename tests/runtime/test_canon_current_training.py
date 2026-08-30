from __future__ import annotations

from sword_runtime.service_runtime import CommandRoutedProductionPlanner
from sword_runtime.training_rates import resolved_activity_regimen, verified_activity_hours_per_cycle

import pytest


def test_major_canon_specialized_training_contracts_are_current_only_and_deterministic(campaign):
    planner = CommandRoutedProductionPlanner(campaign)
    planner._reset()
    profiles = planner.read("game/data/mil/recruitment-cohort-profiles.json")
    expected = {
        "char_shin": ("professional_officer", "program.commander_combined_arms", 205.714286),
        "char_karyoten": ("professional_officer", "program.strategist", 205.714286),
        "char_mou_ki": ("household_professional", "program.strategic_apprentice", 205.714286),
        "char_kyoukai": ("professional_officer", "program.commander_combined_arms", 205.714286),
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

    hyou = planner.read(planner.owner_path("char_hyou"))
    assert hyou["life_status"] == "dead"
    assert hyou["health_status"] == "dead"
    assert hyou["activity_contract"]["autonomous_enabled"] is False
    assert hyou["autonomous_activity_state"]["enabled"] is False
    assert "next_due" not in hyou["autonomous_activity_state"]


def test_current_capability_state_has_no_repair_receipts(campaign):
    planner = CommandRoutedProductionPlanner(campaign)
    planner._reset()
    meta = planner.read("state/meta.json")
    history = planner.read("state/history/events/index.json")
    assert "last_universal_training_repair" not in meta
    assert "last_training_fairness_canon_repair" not in meta
    assert all(row.get("kind") != "explicit_repair" for row in history.get("events", []))
    assert all(not str(row.get("event_id", "")).startswith("repair_") for row in history.get("events", []))
