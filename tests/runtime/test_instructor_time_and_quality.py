from __future__ import annotations

import copy
import json
from pathlib import Path

from sword_runtime.training_instructors import (
    best_instructor_for_drill,
    distributed_instructor_capacity,
    instructor_contexts_for_program,
)
from sword_runtime.training_programs import settle_cohort_program, settle_exact_program
from sword_runtime.training_time import reserve_person_training_time
from sword_runtime.sim.calendar import CampaignTime


class MemoryRuntime:
    def __init__(self, people: dict[str, dict], objects: dict[str, dict] | None = None):
        self.people = copy.deepcopy(people)
        self.objects = copy.deepcopy(objects or {})

    def owner_path(self, ref: str) -> str:
        if ref not in self.people and ref not in self.objects:
            raise ValueError(ref)
        return ref

    def read(self, path: str):
        if path in self.people:
            return self.people[path]
        return self.objects[path]

    def put(self, path: str, value):
        if path in self.objects:
            self.objects[path] = copy.deepcopy(value)
        else:
            self.people[path] = copy.deepcopy(value)


def _rules() -> dict:
    return json.loads(Path("game/data/mechanics/training.json").read_text(encoding="utf-8"))


def _session_rules() -> dict:
    return json.loads(Path("game/data/mechanics/training-session.json").read_text(encoding="utf-8"))


def _registry() -> dict:
    return {
        "drills": {
            "drill.sword": {
                "skills": ["Sword"],
                "attributes": ["Coordination"],
                "practice_mode": "coached",
                "intensity": "standard",
                "equipment_requirements": [],
                "facility_tag": "training_ground",
                "instructor_role": "role_instructor",
            }
        },
        "programs": {
            "program.sword": {
                "cycle_days": 7,
                "rotation": [{"drill_ref": "drill.sword", "weight_bp": 10000}],
            }
        },
        "instructor_pools": {"role_instructor": ["char_good", "char_wrong"]},
        "instructor_location_groups": [],
    }


def _exact(name: str, *, sword: int, leadership: int, polearms: int = 0, location: str = "loc_dojo") -> dict:
    return {
        "schema": "sab_character",
        "owner_id": name,
        "current_location": location,
        "health": "healthy",
        "skills": {"Sword": sword, "Polearms": polearms, "Leadership": leadership},
        "attributes": {"Coordination": 80, "Intelligence": 80, "Presence": 80},
        "aptitude": {"technical_learning": 100, "physical_learning": 100},
        "birth": "280-BCE-01-01",
        "development_state": {},
    }


def test_relevant_domain_mastery_beats_unrelated_high_skill() -> None:
    registry = _registry()
    runtime = MemoryRuntime({
        "char_good": _exact("char_good", sword=180, leadership=120, polearms=0),
        "char_wrong": _exact("char_wrong", sword=20, leadership=120, polearms=240),
    })
    row = best_instructor_for_drill(
        runtime, registry=registry, training_rules=_rules(), drill_ref="drill.sword",
        trainee_skills={"Sword": 60, "Leadership": 20}, trainee_location="loc_dojo",
    )
    assert row["instructor_ref"] == "char_good"
    assert row["domain_score"] == 180


def test_absent_instructor_falls_back_to_real_self_practice() -> None:
    registry = _registry()
    runtime = MemoryRuntime({
        "char_good": _exact("char_good", sword=180, leadership=120, location="loc_elsewhere"),
        "char_wrong": _exact("char_wrong", sword=20, leadership=120, location="loc_elsewhere"),
    })
    contexts = instructor_contexts_for_program(
        runtime, registry=registry, training_rules=_rules(), program_ref="program.sword",
        trainee_skills={"Sword": 60, "Leadership": 20}, student_count=1,
        location_ref="loc_dojo", trainee_ref="char_trainee",
    )
    row = contexts["drill.sword"]
    assert row["instructor_ref"] is None
    assert row["source"] == "self_practice_no_exact_instructor"
    assert row["quality_factor"] == 1.0


def _unit_formation(*, strength: int, active_1000: int, active_500: int, active_100: int, both_top: bool = True) -> dict:
    return {
        "personnel": strength,
        "authorized_strength": strength,
        "formation_class": "unit",
        "commander_ref": "char_unit_commander",
        "deputy_ref": "char_unit_deputy" if both_top else None,
        "officer_cadre": {
            "rank_inventory": {
                "1000_commander": active_1000,
                "500_commander": active_500,
                "100_commander": active_100,
            },
            "materialized_refs_by_rank": {
                "1000_commander": [],
                "500_commander": [],
                "100_commander": [],
            },
        },
    }


def test_mass_capacity_shortfall_reduces_verified_edu() -> None:
    rules = _rules()
    drill = _registry()["drills"]["drill.sword"]
    weak_formation = _unit_formation(strength=1000, active_1000=0, active_500=2, active_100=0)
    full_formation = _unit_formation(strength=1000, active_1000=0, active_500=2, active_100=10)
    no_leaders = distributed_instructor_capacity(
        training_rules=rules, drill=drill, student_count=1000,
        formation=weak_formation, trainee_skills={"Leadership": 0, "Sword": 50},
    )
    trained_cadre = distributed_instructor_capacity(
        training_rules=rules, drill=drill, student_count=1000,
        formation=full_formation, trainee_skills={"Leadership": 100, "Sword": 50},
    )
    assert no_leaders == 0.0
    assert trained_cadre == 1.0

    base = {
        "skill_means": {"Sword": 50}, "attribute_means": {"Coordination": 80},
        "aptitude_means": {"technical_learning": 100, "physical_learning": 100},
        "age_distribution": {"mean": 25}, "skill_edu_banks": {}, "attribute_edu_banks": {},
    }
    weak = copy.deepcopy(base)
    strong = copy.deepcopy(base)
    registry = _registry()
    settle_cohort_program(
        weak, registry=registry, program_ref="program.sword", deliberate_hours=10,
        role_exposure_hours=0, training_rules=rules, facility_grade="adequate",
        equipment_grade="adequate", recovery_grade="adequate", evidence_ref="weak",
        instructor_context_by_drill={"drill.sword": {"quality_factor": 1.0, "capacity_factor": no_leaders}},
    )
    settle_cohort_program(
        strong, registry=registry, program_ref="program.sword", deliberate_hours=10,
        role_exposure_hours=0, training_rules=rules, facility_grade="adequate",
        equipment_grade="adequate", recovery_grade="adequate", evidence_ref="strong",
        instructor_context_by_drill={"drill.sword": {"quality_factor": 1.0, "capacity_factor": trained_cadre}},
    )
    assert weak.get("skill_edu_banks", {}).get("Sword", 0) < strong.get("skill_edu_banks", {}).get("Sword", 0)


def test_aggregate_command_posts_count_as_staffed_hierarchy() -> None:
    rules = _rules()
    drill = _registry()["drills"]["drill.sword"]
    formation = _unit_formation(strength=2000, active_1000=2, active_500=4, active_100=20)
    formation.pop("commander_ref", None)
    formation.pop("deputy_ref", None)
    formation["attached_unit_command_by_role"] = {"command_personnel": 2}
    assert distributed_instructor_capacity(
        training_rules=rules, drill=drill, student_count=2000, formation=formation,
        trainee_skills={"Leadership": 80, "Sword": 50},
    ) == 1.0


def test_unmaterialized_aggregate_cohort_keeps_embedded_drill_cadre() -> None:
    rules = _rules()
    drill = _registry()["drills"]["drill.sword"]
    assert distributed_instructor_capacity(
        training_rules=rules, drill=drill, student_count=5000, formation=None,
        trainee_skills={"Training": 20, "Sword": 50},
    ) == 1.0


def test_hierarchical_capacity_uses_weakest_required_command_echelon() -> None:
    rules = _rules()
    drill = _registry()["drills"]["drill.sword"]
    full = _unit_formation(strength=2000, active_1000=2, active_500=4, active_100=20)
    half_1000 = _unit_formation(strength=2000, active_1000=1, active_500=4, active_100=20)
    half_500 = _unit_formation(strength=2000, active_1000=2, active_500=2, active_100=20)
    half_100 = _unit_formation(strength=2000, active_1000=2, active_500=4, active_100=10)
    one_top = _unit_formation(strength=2000, active_1000=2, active_500=4, active_100=20, both_top=False)
    kwargs = {"training_rules": rules, "drill": drill, "student_count": 2000, "trainee_skills": {"Leadership": 80, "Sword": 50}}
    assert distributed_instructor_capacity(formation=full, **kwargs) == 1.0
    assert distributed_instructor_capacity(formation=half_1000, **kwargs) == 0.5
    assert distributed_instructor_capacity(formation=half_500, **kwargs) == 0.5
    assert distributed_instructor_capacity(formation=half_100, **kwargs) == 0.5
    assert distributed_instructor_capacity(formation=one_top, **kwargs) == 0.85


def test_mass_training_uses_higher_command_chain_without_unit_count_cap() -> None:
    registry = _registry()
    registry["instructor_pools"] = {"role_instructor": []}
    runtime = MemoryRuntime(
        {
            "char_army": _exact("char_army", sword=190, leadership=180),
            "char_army_deputy": _exact("char_army_deputy", sword=160, leadership=150),
        },
        {"cmdgrp.field": {"commander_ref": "char_army", "deputy_ref": "char_army_deputy"}},
    )
    formation = _unit_formation(strength=2000, active_1000=2, active_500=4, active_100=20)
    formation["higher_command_ref"] = "cmdgrp.field"
    row = instructor_contexts_for_program(
        runtime, registry=registry, training_rules=_rules(), program_ref="program.sword",
        trainee_skills={"Sword": 60, "Leadership": 80}, student_count=2000,
        location_ref="loc_dojo", formation=formation, scheduled_hours=48,
        window_start="244-BCE-07-29T08:00:00+08:00", window_end="244-BCE-08-05T08:00:00+08:00",
        evidence_ref="mass-chain", reserve_duty=True,
    )["drill.sword"]
    assert row["instructor_ref"] == "char_army"
    assert row["capacity_factor"] == 1.0
    assert row["instructor_duty"]["model"] == "hierarchical_command_chain"
    assert row["instructor_duty"]["requested_hours"] == 0.0
    assert row["instructor_duty"]["reserved_hours"] == 0.0


def test_better_instructor_increases_edu_for_same_verified_hours() -> None:
    rules = _rules()
    registry = _registry()
    base = {
        "skill_means": {"Sword": 120}, "attribute_means": {"Coordination": 90},
        "aptitude_means": {"technical_learning": 100, "physical_learning": 100},
        "age_distribution": {"mean": 25}, "skill_edu_banks": {}, "attribute_edu_banks": {},
    }
    ordinary = copy.deepcopy(base)
    excellent = copy.deepcopy(base)
    for cohort, quality, evidence in ((ordinary, 0.9, "ordinary"), (excellent, 1.3, "excellent")):
        settle_cohort_program(
            cohort, registry=registry, program_ref="program.sword", deliberate_hours=8,
            role_exposure_hours=0, training_rules=rules, facility_grade="adequate",
            equipment_grade="adequate", recovery_grade="adequate", evidence_ref=evidence,
            instructor_context_by_drill={"drill.sword": {"quality_factor": quality, "capacity_factor": 1.0}},
        )
    assert excellent["skill_edu_banks"]["Sword"] > ordinary["skill_edu_banks"]["Sword"]


def test_same_instructor_cannot_teach_overlapping_sessions_for_free() -> None:
    registry = _registry()
    runtime = MemoryRuntime({
        "char_good": _exact("char_good", sword=180, leadership=160),
        "char_wrong": _exact("char_wrong", sword=20, leadership=20),
    })
    rules = _rules()
    start = "244-BCE-07-29T08:00:00+08:00"
    end = "244-BCE-07-29T18:00:00+08:00"
    first = instructor_contexts_for_program(
        runtime, registry=registry, training_rules=rules, program_ref="program.sword",
        trainee_skills={"Sword": 60, "Leadership": 20}, student_count=1, location_ref="loc_dojo",
        trainee_ref="char_a", scheduled_hours=10, window_start=start, window_end=end,
        evidence_ref="session-a", reserve_duty=True,
    )["drill.sword"]
    second = instructor_contexts_for_program(
        runtime, registry=registry, training_rules=rules, program_ref="program.sword",
        trainee_skills={"Sword": 60, "Leadership": 20}, student_count=1, location_ref="loc_dojo",
        trainee_ref="char_b", scheduled_hours=10, window_start=start, window_end=end,
        evidence_ref="session-b", reserve_duty=True,
    )["drill.sword"]
    assert first["instructor_duty"]["reserved_hours"] == 10
    assert second["instructor_duty"]["reserved_hours"] == 0
    assert second["instructor_ref"] is None


def test_instructor_can_still_train_personally_with_remaining_time() -> None:
    rules = _rules()
    registry = _registry()
    instructor = _exact("char_good", sword=120, leadership=120)
    start = "244-BCE-07-29T08:00:00+08:00"
    end = "244-BCE-07-29T18:00:00+08:00"
    duty = reserve_person_training_time(
        instructor, requested_hours=4, window_start=start, window_end=end,
        reservation_ref="teaching-four", kind="instructor_duty", training_rules=rules,
    )
    assert duty["reserved_hours"] == 4
    result = settle_exact_program(
        instructor, registry=registry, program_ref="program.sword", hours=8,
        at=CampaignTime.parse(end), training_rules=rules, session_rules=_session_rules(),
        facility_grade="adequate", equipment_grade="adequate", recovery_grade="adequate",
        feedback_grade="ordinary", time_window_start=start, time_window_end=end,
        time_evidence_ref="own-training",
    )
    assert result["requested_hours"] == 8
    assert result["verified_hours"] == 6
    entries = instructor["development_state"]["training_time_ledger"]["active_entries"]
    assert sum(float(row["hours"]) for row in entries) == 10


def test_next_best_available_instructor_replaces_booked_top_teacher() -> None:
    registry = _registry()
    runtime = MemoryRuntime({
        "char_good": _exact("char_good", sword=190, leadership=170),
        "char_wrong": _exact("char_wrong", sword=150, leadership=140),
    })
    rules = _rules()
    start = "244-BCE-07-29T08:00:00+08:00"
    end = "244-BCE-07-29T18:00:00+08:00"
    reserve_person_training_time(
        runtime.people["char_good"], requested_hours=10, window_start=start, window_end=end,
        reservation_ref="already-booked", kind="instructor_duty", training_rules=rules,
    )
    row = instructor_contexts_for_program(
        runtime, registry=registry, training_rules=rules, program_ref="program.sword",
        trainee_skills={"Sword": 60, "Leadership": 20}, student_count=1, location_ref="loc_dojo",
        trainee_ref="char_student", scheduled_hours=10, window_start=start, window_end=end,
        evidence_ref="replacement-session", reserve_duty=True,
    )["drill.sword"]
    assert row["instructor_ref"] == "char_wrong"
    assert row["instructor_duty"]["reserved_hours"] == 10
