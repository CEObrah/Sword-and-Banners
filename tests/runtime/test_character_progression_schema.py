from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError


ROOT = Path(__file__).resolve().parents[2]


def _schema(name: str):
    return json.loads((ROOT / "game" / "schemas" / name).read_text(encoding="utf-8"))


def _development_state():
    return {
        "skill_edu_banks": {"Sword": 1.25},
        "settled_training_hours": 10,
        "training_credit": 0.0,
        "completed_reviews": 1,
    }


def _sab_character():
    return {
        "schema": "sab_character",
        "owner_id": "char.fixture.progression",
        "name": "Progression Fixture",
        "birth_date": "260-BCE-01-01",
        "body": {
            "adult_height_cm": 175,
            "growth_end_age": 20,
            "current_weight_kg": 70,
            "frame": "average",
        },
        "appearance": 50,
        "development_state": _development_state(),
        "training_history": [
            {
                "started_at": "245-BCE-01-01T00:00:00+08:00",
                "completed_at": "245-BCE-01-01T01:00:00+08:00",
                "focus": "Sword",
                "hours": 1,
                "development": {},
            }
        ],
    }


def _materialized_person():
    return {
        "schema": "sword-materialized-person",
        "owner_id": "char.fixture.materialized",
        "owner_type": "character",
        "id": "char.fixture.materialized",
        "name": "Materialized Progression Fixture",
        "birth_date": "260-BCE-01-01",
        "status": "alive",
        "state": "qin",
        "life_status": "active",
        "health_status": "healthy",
        "current_location": "loc_fixture",
        "attributes": {},
        "skills": {},
        "aptitude": {},
        "development_state": _development_state(),
    }


def test_sab_character_accepts_registered_progression_fields() -> None:
    Draft202012Validator(_schema("sab-character.schema.json")).validate(_sab_character())


def test_sab_character_rejects_invalid_progression_bank_type() -> None:
    value = _sab_character()
    value["development_state"]["skill_edu_banks"]["Sword"] = "not-a-number"
    with pytest.raises(ValidationError):
        Draft202012Validator(_schema("sab-character.schema.json")).validate(value)


def test_materialized_person_accepts_registered_progression_fields() -> None:
    Draft202012Validator(_schema("sword-materialized-person.schema.json")).validate(
        _materialized_person()
    )


def test_materialized_person_rejects_invalid_progression_structure() -> None:
    value = _materialized_person()
    value["development_state"]["completed_reviews"] = -1
    with pytest.raises(ValidationError):
        Draft202012Validator(_schema("sword-materialized-person.schema.json")).validate(value)
