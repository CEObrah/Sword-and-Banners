from __future__ import annotations

import json
from pathlib import Path

import pytest

from sword_runtime.development import (
    CAPABILITY_REFERENCE_VALUE,
    ROUTINE_SKILL_TRAINING_CEILING,
    SKILL_HARD_CAP,
    resolve_exceptional_skill_breakthrough,
    settle_skill_training,
)
from sword_runtime.sim.calendar import CampaignTime

ROOT = Path(__file__).resolve().parents[2]
TRAINING = json.loads((ROOT / "game" / "data" / "mechanics" / "training.json").read_text(encoding="utf-8"))
MODEL = json.loads((ROOT / "game" / "data" / "development" / "model.json").read_text(encoding="utf-8"))
AT = CampaignTime.parse("245-BCE-01-01T00:00:00+08:00")


def _person(score: int, bank: float = 0.0) -> dict:
    return {
        "schema": "sab_character",
        "owner_id": "char_test_master",
        "birth_date": "270-BCE-01-01",
        "skills": {"Sword": score},
        "aptitude": {"physical_learning": 250},
        "health_status": "healthy",
        "development_state": {"skill_edu_banks": {"Sword": bank}},
    }


def test_200_is_reference_not_hard_cap() -> None:
    assert MODEL["capability_scale"]["hard_cap"] is None
    assert MODEL["aptitude_scale"]["max"] is None
    assert MODEL["aptitude_scale"]["uncapped"] is True
    assert CAPABILITY_REFERENCE_VALUE == 200
    assert SKILL_HARD_CAP is None


def test_routine_training_stops_at_ceiling_and_banks_bounded_preparation() -> None:
    person = _person(179, bank=1000.0)
    result = settle_skill_training(person, "Sword", 12, AT, TRAINING)
    assert person["skills"]["Sword"] == ROUTINE_SKILL_TRAINING_CEILING == 180
    assert result["exceptional_progression_required"] is True
    next_cost = 18.0 * ((1.0 + 180 / 50.0) ** 1.75)
    assert person["development_state"]["skill_edu_banks"]["Sword"] < next_cost


def test_saved_skill_above_200_is_valid_and_not_clamped() -> None:
    person = _person(217, bank=0.0)
    result = settle_skill_training(person, "Sword", 12, AT, TRAINING)
    assert person["skills"]["Sword"] == 217
    assert result["skill_score"] == 217
    assert result["skill_hard_cap"] is None


def test_evidence_backed_breakthrough_crosses_200_and_consumes_evidence() -> None:
    person = _person(200, bank=10000.0)
    events = [
        {"event_id": "battle.one", "kind": "personal_combat", "actor_refs": ["char_test_master"], "battle_ref": "battle.one"},
        {"event_id": "battle.two", "kind": "battle_resolved", "actor_refs": ["char_test_master"], "battle_ref": "battle.two"},
        {"event_id": "siege.three", "kind": "siege_assault", "actor_refs": ["char_test_master"], "siege_ref": "siege.three"},
    ]
    result = resolve_exceptional_skill_breakthrough(person, "Sword", events, AT, TRAINING)
    assert result["starting_value"] == 200
    assert result["ending_value"] == 201
    assert person["skills"]["Sword"] == 201
    assert len(person["development_state"]["breakthrough_event_refs"]) == 3

    later = AT.add_seconds(15 * 86400)
    with pytest.raises(ValueError, match="unused exact-person evidence"):
        resolve_exceptional_skill_breakthrough(person, "Sword", events, later, TRAINING)
