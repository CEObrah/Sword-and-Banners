from __future__ import annotations

from copy import deepcopy
import json

from sword_runtime.development import settle_combat_experience
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.training_programs import (
    combat_skill_weights,
    combat_skill_weights_for_participant,
)


def test_registered_combat_weights_never_train_teaching_skill(campaign):
    registry = json.loads((campaign / "game/data/mil/deterministic-training-programs.json").read_text())
    weights = combat_skill_weights(registry, "program.commander_combined_arms")
    assert "Training" not in weights
    assert "Sword" in weights
    assert "Formation Command" in weights


def test_noncommand_participant_cannot_gain_command_domains(campaign):
    registry = json.loads((campaign / "game/data/mil/deterministic-training-programs.json").read_text())
    weights = combat_skill_weights_for_participant(
        registry, "program.commander_combined_arms", "embedded"
    )
    for skill in ("Formation Command", "Leadership", "Tactics", "Strategy", "Logistics"):
        assert skill not in weights
    assert "Sword" in weights
    assert "Mass Combat" in weights
    assert abs(sum(weights.values()) - 1.0) < 1e-9


def test_actual_internal_commander_keeps_command_learning(campaign):
    registry = json.loads((campaign / "game/data/mil/deterministic-training-programs.json").read_text())
    weights = combat_skill_weights_for_participant(
        registry, "program.commander_combined_arms", "internal_100_commander"
    )
    assert "Formation Command" in weights
    assert "Tactics" in weights
    assert "Sword" in weights
    assert abs(sum(weights.values()) - 1.0) < 1e-9


def test_combat_experience_is_deterministic_and_skill_only(campaign):
    training = json.loads((campaign / "game/data/mechanics/training.json").read_text())
    registry = json.loads((campaign / "game/data/mil/deterministic-training-programs.json").read_text())
    weights = combat_skill_weights_for_participant(
        registry, "program.line_infantry", "embedded"
    )
    base = {
        "owner_id": "char_test_fighter",
        "birth_date": "270-BCE-01-01",
        "health_status": "healthy",
        "attributes": {"Strength": 80, "Agility": 80},
        "skills": {name: 70 for name in weights},
        "aptitude": {
            "physical_learning": 120,
            "tactical_learning": 120,
            "technical_learning": 120,
            "academic_learning": 120,
            "social_learning": 120,
        },
    }
    a = deepcopy(base)
    b = deepcopy(base)
    at = CampaignTime.parse("244-BCE-07-30T12:00:00+08:00")
    ra = settle_combat_experience(a, weights, 12.0, at, training)
    rb = settle_combat_experience(b, weights, 12.0, at, training)
    assert ra == rb
    assert a == b
    assert a["attributes"] == base["attributes"]
    assert a["development_state"]["combat_experience_hours_milli"] == 12000
