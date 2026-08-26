from __future__ import annotations

import json
import json
from pathlib import Path

from sword_runtime.fatigue import (
    RULES_PATH,
    settle_formation_idle_fatigue,
    settle_person_idle_fatigue,
    stamp_formation_activity_fatigue,
    stamp_person_activity_fatigue,
)
from sword_runtime.sim.calendar import CampaignTime

ROOT = Path(__file__).resolve().parents[2]
RULES = json.loads((ROOT / RULES_PATH).read_text(encoding="utf-8"))
T0 = CampaignTime.parse("245-BCE-01-01T00:00:00+08:00")


def test_ready_formation_recovers_ordinary_sleep_and_downtime() -> None:
    formation = {"status": "ready", "fatigue": 60, "fatigue_recovery_through": str(T0)}
    result = settle_formation_idle_fatigue(formation, current=T0.add_hours(8), rules=RULES)
    assert result["recovery_points"] == 12
    assert formation["fatigue"] == 48


def test_garrison_rest_recovers_faster_than_deployed_field_rest() -> None:
    garrison = {"status": "garrisoned", "fatigue": 80, "fatigue_recovery_through": str(T0)}
    deployed = {"status": "deployed", "fatigue": 80, "fatigue_recovery_through": str(T0)}
    settle_formation_idle_fatigue(garrison, current=T0.add_hours(8), rules=RULES)
    settle_formation_idle_fatigue(deployed, current=T0.add_hours(8), rules=RULES)
    assert garrison["fatigue"] == 66
    assert deployed["fatigue"] == 72


def test_marching_does_not_get_free_simultaneous_recovery() -> None:
    formation = {"status": "marching", "fatigue": 40, "fatigue_recovery_through": str(T0)}
    result = settle_formation_idle_fatigue(formation, current=T0.add_hours(16), rules=RULES)
    assert result["recovery_points"] == 0
    assert formation["fatigue"] == 40


def test_activity_completion_boundary_blocks_recovery_until_work_is_finished() -> None:
    formation = {"status": "ready", "fatigue": 20, "fatigue_recovery_through": str(T0)}
    completed = T0.add_hours(12)
    stamp_formation_activity_fatigue(formation, completed_at=completed, fatigue_gain=3, activity_kind="march")
    mid = settle_formation_idle_fatigue(formation, current=T0.add_hours(6), rules=RULES)
    assert mid["activity_in_progress"] is True
    assert formation["fatigue"] == 23
    assert formation["fatigue_recovery_through"] == str(completed)
    later = settle_formation_idle_fatigue(formation, current=completed.add_hours(8), rules=RULES)
    assert later["recovery_points"] == 12
    assert formation["fatigue"] == 11


def test_same_timestamp_cannot_double_recover() -> None:
    formation = {"status": "ready", "fatigue": 60, "fatigue_recovery_through": str(T0)}
    at = T0.add_hours(8)
    first = settle_formation_idle_fatigue(formation, current=at, rules=RULES)
    second = settle_formation_idle_fatigue(formation, current=at, rules=RULES)
    assert first["recovery_points"] == 12
    assert second["recovery_points"] == 0
    assert formation["fatigue"] == 48


def test_exact_officer_recovers_during_idle_time_and_training_restarts_clock() -> None:
    person = {"fatigue": 50, "development_state": {"fatigue_recovery_through": str(T0)}}
    settle_person_idle_fatigue(person, current=T0.add_hours(8), rules=RULES, state="ordinary")
    assert person["fatigue"] == 36
    completed = T0.add_hours(12)
    stamp_person_activity_fatigue(person, completed_at=completed, fatigue_gain=4, activity_kind="training")
    assert person["fatigue"] == 40
    assert person["development_state"]["fatigue_recovery_through"] == str(completed)


def test_endurance_materially_changes_fatigue_accumulation_not_saved_exhaustion_penalty() -> None:
    from sword_runtime.fatigue import battle_person_fatigue_gain, endurance_fatigue_rate_factor, person_fatigue_factors

    low = battle_person_fatigue_gain(
        rules=RULES, battle_hours=3.0, role="embedded", endurance=40,
        available_contact_seconds=120.0, physical_contacts=30, burden_multiplier=1.0,
    )
    kyoukai_like = battle_person_fatigue_gain(
        rules=RULES, battle_hours=3.0, role="embedded", endurance=70,
        available_contact_seconds=120.0, physical_contacts=30, burden_multiplier=1.0,
    )
    high = battle_person_fatigue_gain(
        rules=RULES, battle_hours=3.0, role="embedded", endurance=200,
        available_contact_seconds=120.0, physical_contacts=30, burden_multiplier=1.0,
    )
    assert low >= 30
    assert 20 <= kyoukai_like <= 26
    assert high <= 15
    assert low >= high * 2
    assert endurance_fatigue_rate_factor(40) > endurance_fatigue_rate_factor(200) * 2

    # Once two people are equally exhausted, high Endurance must not magically
    # erase the saved fatigue penalty. Endurance controls how quickly fatigue was
    # accumulated; the persisted exhaustion itself remains mechanically real.
    tired_low = person_fatigue_factors(fatigue=80, endurance=40)
    tired_high = person_fatigue_factors(fatigue=80, endurance=200)
    assert tired_low == tired_high
    assert tired_low["control_factor"] < 0.65
    assert tired_low["tempo_factor"] < 0.50
    assert tired_low["movement_factor"] < 0.55
    assert tired_low["exertion_capacity_factor"] < 0.40


def test_kyoukai_is_elite_combat_low_endurance_current_baseline() -> None:
    person = json.loads((ROOT / "state/char/kyoukai.json").read_text(encoding="utf-8"))
    attributes = person["attributes"]
    skills = person["skills"]
    assert attributes["Endurance"] == 70
    assert skills["Sword"] >= 195
    assert attributes["Agility"] >= 190
    assert attributes["Coordination"] >= 190
    assert attributes["Awareness"] >= 185
    assert person["aptitude"]["physical_learning"] == 150
    assert float(person.get("development_state", {}).get("attribute_edu_banks", {}).get("Endurance", 0) or 0) == 0.0
