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
        "breakthrough_event_refs": ["event.breakthrough.fixture"],
        "breakthrough_dossiers": {
            "Sword": {
                "last_breakthrough_at": "245-BCE-01-01T00:00:00+08:00",
                "last_starting_value": 200,
                "last_ending_value": 201,
                "last_evidence_refs": ["event.breakthrough.fixture"],
                "last_context_signatures": ["battle:battle.fixture"],
                "last_consolidation_units": 12.5,
                "resolved_breakthroughs": 1,
            }
        },
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


def test_sab_character_rejects_duplicate_breakthrough_evidence() -> None:
    value = _sab_character()
    value["development_state"]["breakthrough_event_refs"] = ["event.same", "event.same"]
    with pytest.raises(ValidationError):
        Draft202012Validator(_schema("sab-character.schema.json")).validate(value)


def test_materialized_person_accepts_registered_progression_fields() -> None:
    Draft202012Validator(_schema("sword-materialized-person.schema.json")).validate(
        _materialized_person()
    )


def test_materialized_person_rejects_negative_settled_training_hours() -> None:
    value = _materialized_person()
    value["development_state"]["settled_training_hours"] = -1
    with pytest.raises(ValidationError):
        Draft202012Validator(_schema("sword-materialized-person.schema.json")).validate(value)
