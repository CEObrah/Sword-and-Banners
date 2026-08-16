from __future__ import annotations

import json
from pathlib import Path

from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.training_session import settle_training_session, standing_recovery_result

ROOT = Path(__file__).resolve().parents[2]
TRAINING = json.loads((ROOT / "game" / "data" / "mechanics" / "training.json").read_text(encoding="utf-8"))
SESSION = json.loads((ROOT / "game" / "data" / "mechanics" / "training-session.json").read_text(encoding="utf-8"))
AT = CampaignTime.parse("245-BCE-01-01T00:00:00+08:00")


def _person() -> dict:
    return {
        "schema": "sab_character",
        "owner_id": "char_training_test",
        "birth_date": "270-BCE-01-01",
        "health_status": "healthy",
        "fatigue": 0,
        "skills": {"Sword": 60, "Strategy": 60},
        "attributes": {
            "Strength": 60,
            "Agility": 60,
            "Endurance": 60,
            "Toughness": 60,
            "Coordination": 60,
            "Awareness": 60,
            "Composure": 60,
            "Intelligence": 60,
            "Presence": 60,
        },
        "aptitude": {
            "physical_learning": 150,
            "tactical_learning": 150,
            "academic_learning": 150,
            "social_learning": 150,
        },
        "development_state": {},
    }


def test_exact_person_training_banks_related_attribute_stimulus_only() -> None:
    person = _person()
    before = dict(person["attributes"])

    result = settle_training_session(person, "Sword", 12, AT, TRAINING, SESSION)

    assert result["attribute_development"]
    banks = person["development_state"]["attribute_edu_banks"]
    assert banks["Strength"] > 0
    assert banks["Agility"] > 0
    assert banks["Coordination"] > 0
    assert banks["Awareness"] > 0
    assert "Intelligence" not in banks
    assert person["attributes"]["Intelligence"] == before["Intelligence"]


def test_exact_person_attribute_bank_eventually_converts_to_real_stat_points() -> None:
    person = _person()
    person["development_state"]["attribute_edu_banks"] = {"Strength": 1000.0}
    before = person["attributes"]["Strength"]

    result = settle_training_session(person, "Sword", 12, AT, TRAINING, SESSION)

    strength = next(row for row in result["attribute_development"] if row["attribute"] == "Strength")
    assert strength["attribute_points_gained"] > 0
    assert person["attributes"]["Strength"] > before


def test_command_training_can_develop_mental_and_command_attributes() -> None:
    person = _person()
    result = settle_training_session(person, "Strategy", 12, AT, TRAINING, SESSION)
    names = {row["attribute"] for row in result["attribute_development"]}
    assert names == {"Intelligence", "Awareness", "Composure"}
    assert all(person["development_state"]["attribute_edu_banks"][name] > 0 for name in names)


def test_sustainable_standing_training_recovers_instead_of_accumulating_fatigue() -> None:
    start = AT
    end = AT.add_hours(11 * 24)
    result = standing_recovery_result(
        fatigue=62,
        started_at=start,
        completed_at=end,
        completed_deliberate_hours=88,
        normal_deliberate_hours_per_7d=56,
        session_rules=SESSION,
    )
    assert result["normal_deliberate_capacity_hours"] == 88.0
    assert result["excess_deliberate_hours"] == 0.0
    assert result["recovery_points"] == 88
    assert result["fatigue_after"] == 0


def test_only_training_above_normal_ceiling_adds_residual_overload() -> None:
    result = standing_recovery_result(
        fatigue=0,
        started_at=AT,
        completed_at=AT.add_hours(7 * 24),
        completed_deliberate_hours=70,
        normal_deliberate_hours_per_7d=56,
        session_rules=SESSION,
    )
    assert result["excess_deliberate_hours"] == 14.0
    assert result["overload_fatigue_points"] == 7
    assert result["fatigue_after"] == 7
