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
    assert "Formation Fighting" in weights
    assert "Mass Combat" not in weights
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


def test_actual_commander_combat_builds_command_skill_edu(campaign):
    training = json.loads((campaign / "game/data/mechanics/training.json").read_text())
    registry = json.loads((campaign / "game/data/mil/deterministic-training-programs.json").read_text())
    weights = combat_skill_weights_for_participant(
        registry, "program.commander_combined_arms", "commander"
    )
    person = {
        "owner_id": "char_test_commander_experience",
        "birth_date": "270-BCE-01-01",
        "health_status": "healthy",
        "attributes": {"Strength": 80, "Agility": 80},
        "skills": {name: 60 for name in weights},
        "aptitude": {
            "physical_learning": 120,
            "tactical_learning": 120,
            "technical_learning": 120,
            "academic_learning": 120,
            "social_learning": 120,
        },
    }
    settle_combat_experience(
        person, weights, 20.0,
        CampaignTime.parse("244-BCE-07-30T12:00:00+08:00"), training,
    )
    banks = person["development_state"]["skill_edu_banks"]
    assert banks["Formation Command"] > 0
    assert banks["Leadership"] > 0
    assert banks["Tactics"] > 0
    assert banks["Strategy"] > 0
    assert banks["Logistics"] > 0


def test_green_troops_learn_faster_and_uncommitted_reserve_gets_no_battle_credit(campaign):
    from sword_runtime.cohort_personnel import record_formation_combat_experience

    training = json.loads((campaign / "game/data/mechanics/training.json").read_text())
    registry = json.loads((campaign / "game/data/mil/deterministic-training-programs.json").read_text())
    role_weights = combat_skill_weights(registry, "program.line_infantry")

    def cohort(cid: str, score: float, *, allocated: bool) -> dict:
        return {
            "cohort_id": cid,
            "role": "line_infantry",
            "count": 500,
            "skill_means": {skill: score for skill in role_weights},
            "attribute_means": {},
            "skill_edu_banks": {},
            "attribute_edu_banks": {},
            "aptitude_means": {
                "physical_learning": 100,
                "tactical_learning": 100,
                "technical_learning": 100,
                "academic_learning": 100,
                "social_learning": 100,
            },
            "reserve_by_location": {} if allocated else {"loc_test": 500},
            "allocated_by_formation": {"formation_test": 500} if allocated else {},
        }

    green = cohort("cohort_green", 40, allocated=True)
    veteran = cohort("cohort_veteran", 120, allocated=True)
    reserve = cohort("cohort_reserve", 40, allocated=False)

    def expose(target: dict) -> float:
        force = {
            "headcount": 1000,
            "cohort_ledger": {"cohorts": {target["cohort_id"]: target, "cohort_reserve": deepcopy(reserve)}},
            "available_by_role": {"line_infantry": 500},
            "available_by_location": {"loc_test": {"line_infantry": 500}},
            "allocated_to_formations": {"formation_test": {"personnel": 500}},
        }
        formation = {
            "formation_ref": "formation_test",
            "personnel": 500,
            "composition": {"line_infantry": 500},
            "cohort_composition": [{"cohort_id": target["cohort_id"], "count": 500}],
        }
        record_formation_combat_experience(
            force, formation,
            battle_hours=100.0,
            contact_fraction=1.0,
            role_profiles={},
            training_rules=training,
            evidence_ref=f"battle:{target['cohort_id']}",
            skill_weights_by_role={"line_infantry": role_weights},
        )
        assert force["cohort_ledger"]["cohorts"]["cohort_reserve"].get("verified_combat_exposure_hours_per_person", 0) == 0
        assert force["cohort_ledger"]["cohorts"]["cohort_reserve"].get("skill_edu_banks", {}) == {}
        return sum(float(v) for v in target.get("skill_edu_banks", {}).values())

    green_edu = expose(green)
    veteran_edu = expose(veteran)
    assert green_edu > veteran_edu > 0
