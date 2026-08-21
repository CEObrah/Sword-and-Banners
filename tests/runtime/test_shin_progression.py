from __future__ import annotations

from copy import deepcopy
import json

from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.training_programs import (
    drill_record,
    program_record,
    resolve_program_ref,
    settle_exact_program,
)


def _allowed_skills(registry, program_ref):
    return {
        str(skill)
        for row in program_record(registry, program_ref)["rotation"]
        for skill in drill_record(registry, str(row["drill_ref"])).get("skills", [])
    }


def test_shin_routes_to_explicit_martial_aspirant_program(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    shin = planner.read("state/char/shin.json")
    program_ref, training_ref, role = planner._activity_training_context(
        shin, shin["activity_contract"]
    )
    assert program_ref == "program.martial_aspirant"
    assert training_ref == ""
    assert role == ""


def test_shin_monthly_activity_uses_only_martial_aspirant_domains(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    before = deepcopy(planner.read("state/char/shin.json"))
    due = before["autonomous_activity_state"]["next_due"]
    planner._settle_activity_host({"routed_person_refs": ["char_shin"]}, due)
    after = planner.read("state/char/shin.json")
    last = after["autonomous_activity_state"]["last_training"]
    assert last["program_ref"] == "program.martial_aspirant"
    registry = planner.read("game/data/mil/deterministic-training-programs.json")
    allowed = _allowed_skills(registry, "program.martial_aspirant")
    developed = {
        str(skill)
        for skill, value in after["skills"].items()
        if value != before["skills"].get(skill)
    }
    assert developed <= allowed
    assert not ({"Diplomacy", "Law", "Trade", "Navigation", "Training"} & developed)
    assert after["development_state"]["settled_training_hours"] > before["development_state"]["settled_training_hours"]


def test_shin_one_six_twelve_month_program_replay_is_deterministic(campaign):
    root = campaign
    registry = json.loads((root / "game/data/mil/deterministic-training-programs.json").read_text())
    training = json.loads((root / "game/data/mechanics/training.json").read_text())
    session = json.loads((root / "game/data/mechanics/training-session.json").read_text())
    base = json.loads((root / "state/char/shin.json").read_text())
    program_ref = resolve_program_ref(
        registry,
        person=base,
        explicit_program_ref=base["activity_contract"]["training_program_ref"],
    )
    allowed = _allowed_skills(registry, program_ref)

    def run(months):
        person = deepcopy(base)
        start = CampaignTime.parse("244-BCE-08-01T06:22:48+08:00")
        for index in range(months):
            settle_exact_program(
                person,
                registry=registry,
                program_ref=program_ref,
                hours=56,
                at=start.add_seconds(index * 30 * 86400),
                training_rules=training,
                session_rules=session,
                facility_grade="adequate",
                equipment_grade="adequate",
                recovery_grade="adequate",
                feedback_grade="ordinary",
                cursor_key="shin_replay_cursor",
            )
        return person

    snapshots = {}
    for months in (1, 6, 12):
        a = run(months)
        b = run(months)
        assert a == b
        changed = {k for k, v in a["skills"].items() if v != base["skills"].get(k)}
        assert changed <= allowed
        snapshots[months] = a
    assert snapshots[12]["development_state"]["settled_training_hours"] > snapshots[6]["development_state"]["settled_training_hours"]
    assert snapshots[6]["development_state"]["settled_training_hours"] > snapshots[1]["development_state"]["settled_training_hours"]


def test_shin_current_progression_state_is_compact_and_preserved(campaign):
    shin = json.loads((campaign / "state/char/shin.json").read_text())
    ds = shin["development_state"]
    assert ds["settled_training_hours"] > 0
    assert ds["verified_deliberate_training_hours"] == ds["settled_training_hours"]
    assert "Diplomacy" in ds["skill_edu_banks"]
    assert "universal_training_migration_history" not in ds
    assert "progression_repair_history" not in ds
    assert shin["activity_contract"]["training_program_ref"] == "program.martial_aspirant"
