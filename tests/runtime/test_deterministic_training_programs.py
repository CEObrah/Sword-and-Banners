from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from sword_runtime.command_contracts import COMMAND_PAYLOAD_KEYS
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.training_programs import (
    REGISTRY_PATH,
    _shared_regional_training_mounts,
    formation_drill_access,
    module_allocations,
    resolve_program_ref,
    settle_exact_program,
)

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = json.loads((ROOT / REGISTRY_PATH).read_text(encoding="utf-8"))
TRAINING = json.loads((ROOT / "game/data/mechanics/training.json").read_text(encoding="utf-8"))
SESSION = json.loads((ROOT / "game/data/mechanics/training-session.json").read_text(encoding="utf-8"))
AT = CampaignTime.parse("245-BCE-01-01T00:00:00+08:00")


class _TrainingMountRuntime:
    def __init__(self) -> None:
        self.rows = {
            "mount_pool": {"regional_reserve": {"loc_a": {"horse": 100}}},
            "state/index/location-formation-index.json": {"locations": {"loc_a": ["formation_own", "formation_remote"]}},
            "formation_remote": {
                "formation_ref": "formation_remote",
                "owner_force_ref": "force_test",
                "location_ref": "loc_b",
            },
        }

    def _mount_pool_path_for_formation(self, formation):
        return "mount_pool"

    def owner_path(self, ref):
        return ref

    def read(self, path):
        return self.rows[path]


def _person(*, billet: str = "formation_commander", role: str = "House Guard Commander") -> dict:
    skills = set()
    attrs = set()
    for drill in REGISTRY["drills"].values():
        skills.update(str(x) for x in drill.get("skills", []))
        attrs.update(str(x) for x in drill.get("attributes", []))
    return {
        "schema": "sab_character",
        "owner_id": "char_training_determinism",
        "birth_date": "270-BCE-01-01",
        "health_status": "healthy",
        "fatigue": 0,
        "role": role,
        "command_assignment": {"billet": billet},
        "skills": {name: 60 for name in sorted(skills)},
        "attributes": {name: 60 for name in sorted(attrs)},
        "aptitude": {
            "physical_learning": 150,
            "tactical_learning": 150,
            "academic_learning": 150,
            "social_learning": 150,
        },
        "development_state": {},
    }


def test_registry_is_finite_closed_and_every_rotation_is_exact() -> None:
    programs = REGISTRY["programs"]
    drills = REGISTRY["drills"]
    assert programs and drills
    for pref, program in programs.items():
        rotation = program["rotation"]
        assert sum(int(row["weight_bp"]) for row in rotation) == 10000, pref
        for row in rotation:
            assert row["drill_ref"] in drills, (pref, row["drill_ref"])
    for dref, drill in drills.items():
        assert isinstance(drill.get("skills"), list), dref
        assert isinstance(drill.get("attributes"), list), dref
        assert drill.get("practice_mode"), dref
        assert drill.get("intensity"), dref
        # A preset drill is a real setup, not only a prose label.
        assert "equipment_requirements" in drill, dref
        assert "facility_tag" in drill, dref
        assert "instructor_role" in drill, dref


def test_stale_formation_location_index_cannot_dilute_local_training_mount_share(monkeypatch) -> None:
    import sword_runtime.training_programs as training_programs

    runtime = _TrainingMountRuntime()
    own = {
        "formation_ref": "formation_own",
        "owner_force_ref": "force_test",
        "location_ref": "loc_a",
    }
    monkeypatch.setattr(training_programs, "_formation_mounted_training_need", lambda _registry, _formation: (100, 0))

    # The remote same-force formation is present only in a stale authority:false
    # routing bucket.  It must not consume half of loc_a's real reserve horses.
    assert _shared_regional_training_mounts(runtime, {}, own, own_unmet=100) == 100.0


def test_every_training_record_declares_deterministic_gain_authority() -> None:
    for path in sorted((ROOT / "game/data/mil/training-records").glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("schema") == "training-profile-record":
            profile = doc["profile"]
        elif doc.get("schema") == "training-record":
            profile = doc.get("profile", {})
        else:
            continue
        assert profile.get("deterministic_program_policy"), path.name
        assert "deterministic-training-programs.json" in str(profile.get("gain_authority", "")), path.name


def test_role_branch_and_command_billet_resolve_without_reading_current_stats() -> None:
    infantry = _person(role="House Infantry Commander")
    cavalry = _person(role="House Cavalry Commander")
    crossbow = _person(role="Crossbow Commander")

    # A current formation-command billet selects a commander curriculum without
    # resurrecting the retired House Guard / Guardian Cavalry troop taxonomy.
    assert resolve_program_ref(REGISTRY, role="house_infantry", training_ref="train.house_tang.house_infantry", person=infantry) == "program.commander_combined_arms"
    assert resolve_program_ref(REGISTRY, role="house_cavalry", training_ref="train.house_tang.house_cavalry", person=cavalry) == "program.commander_combined_arms"
    assert resolve_program_ref(REGISTRY, role="missile_crossbow", person=crossbow) == "program.commander_crossbow"

    # Changing all current values must not change the selected future program.
    for person, role in ((infantry, "house_infantry"), (cavalry, "house_cavalry"), (crossbow, "missile_crossbow")):
        baseline = resolve_program_ref(REGISTRY, role=role, person=person)
        person["skills"] = {k: 999 - i for i, k in enumerate(person["skills"])}
        person["attributes"] = {k: 1 + i for i, k in enumerate(person["attributes"])}
        assert resolve_program_ref(REGISTRY, role=role, person=person) == baseline

def test_exact_training_is_replay_deterministic_and_uses_registered_drill_attributes() -> None:
    a = _person()
    b = copy.deepcopy(a)
    program = "program.commander_guard"
    kwargs = dict(
        registry=REGISTRY,
        program_ref=program,
        hours=24,
        at=AT,
        training_rules=TRAINING,
        session_rules=SESSION,
        facility_grade="home_garrison",
        equipment_grade="superior",
        recovery_grade="excellent",
        feedback_grade="expert",
    )
    ra = settle_exact_program(a, **kwargs)
    rb = settle_exact_program(b, **kwargs)
    assert ra == rb
    assert a == b
    allocated = {row["drill_ref"] for row in ra["modules"]}
    expected_attrs = {
        str(attr)
        for dref in allocated
        for attr in REGISTRY["drills"][dref].get("attributes", [])
    }
    banks = set(a.get("development_state", {}).get("attribute_edu_banks", {}))
    assert banks
    assert banks <= expected_attrs


def test_free_text_training_domains_cannot_change_program_or_hour_rotation() -> None:
    altered = copy.deepcopy(REGISTRY)
    # Free-text descriptions are not gain authority. Current House Infantry uses
    # the same closed commander program before and after unrelated prose changes.
    person = _person(role="House Infantry Commander")
    before = resolve_program_ref(REGISTRY, role="house_infantry", training_ref="train.house_tang.house_infantry", person=person)
    after = resolve_program_ref(altered, role="house_infantry", training_ref="train.house_tang.house_infantry", person=person)
    assert before == after == "program.commander_combined_arms"
    assert module_allocations(REGISTRY, before, 37, integer_hours=True) == module_allocations(altered, after, 37, integer_hours=True)

def test_unknown_explicit_or_saved_program_fails_closed() -> None:
    with pytest.raises(ValueError, match="unknown explicit deterministic training program"):
        resolve_program_ref(REGISTRY, role="line_infantry", explicit_program_ref="program.not_real")
    person = _person()
    person["activity_contract"] = {"training_program_ref": "program.not_real"}
    with pytest.raises(ValueError, match="unknown saved deterministic training program"):
        resolve_program_ref(REGISTRY, role="line_infantry", person=person)


def test_formation_train_command_has_no_caller_owned_gain_focuses() -> None:
    assert "focuses" not in COMMAND_PAYLOAD_KEYS["formation_train"]
    assert "training_ref" in COMMAND_PAYLOAD_KEYS["formation_training_set"]


def test_physical_formation_kit_bounds_registered_drill_access() -> None:
    cavalry = {
        "composition": {"cavalry": 1000},
        "training_ref": "train.state_qin.elite_cavalry",
        "equipment_units_by_role": {"cavalry": 1000},
        "equipment_condition_by_role": {"cavalry": 100.0},
        "shield_units_by_role": {"cavalry": 1000},
        "shield_condition_by_role": {"cavalry": 100.0},
        "mounts": {"horse": 500},
    }
    access = formation_drill_access(REGISTRY, "program.cavalry", cavalry, role="cavalry")
    assert access["drill.mounted_control"] == pytest.approx(0.5)
    assert access["drill.mounted_lance"] == pytest.approx(0.5)
    assert "drill.mounted_archery" not in access
    assert access["drill.cavalry_formation"] == pytest.approx(0.5)
    assert access["drill.conditioning_march"] == pytest.approx(1.0)

    mounted_archer = {
        "administrative_owner": "state_zhao",
        "owner_force_ref": "force_state_zhao",
        "composition": {"mounted_archer": 1000},
        "training_ref": "train.state_zhao.mounted_archer",
        "equipment_units_by_role": {"mounted_archer": 1000},
        "equipment_condition_by_role": {"mounted_archer": 100.0},
        "mounts": {"horse": 500},
    }
    access = formation_drill_access(REGISTRY, "program.mounted_archer", mounted_archer, role="mounted_archer")
    assert access["drill.mounted_archery"] == pytest.approx(0.5)
    assert access["drill.mounted_control"] == pytest.approx(0.5)

    infantry = {
        "composition": {"line_infantry": 1000},
        "training_ref": "train.state_qin.regular_combined_arms",
        "equipment_units_by_role": {"line_infantry": 1000},
        "shield_units_by_role": {"line_infantry": 500},
        "equipment_condition_by_role": {"line_infantry": 100.0},
        "shield_condition_by_role": {"line_infantry": 100.0},
        "mounts": {},
    }
    access = formation_drill_access(REGISTRY, "program.line_infantry", infantry, role="line_infantry")
    assert access["drill.spear_shield_line"] == pytest.approx(0.5)
    assert access["drill.sword_shield_close"] == pytest.approx(0.5)
    assert access["drill.formation_maneuver"] == pytest.approx(1.0)
    assert access["drill.conditioning_march"] == pytest.approx(1.0)


def test_destroyed_or_missing_equipment_cannot_grant_weapon_drill_access() -> None:
    formation = {
        "composition": {"line_infantry": 1000},
        "training_ref": "train.state_qin.regular_combined_arms",
        "equipment_units_by_role": {"line_infantry": 0},
        "shield_units_by_role": {"line_infantry": 1000},
        "equipment_condition_by_role": {"line_infantry": 100.0},
        "shield_condition_by_role": {"line_infantry": 100.0},
        "mounts": {},
    }
    access = formation_drill_access(REGISTRY, "program.line_infantry", formation, role="line_infantry")
    assert access["drill.spear_shield_line"] == 0.0
    assert access["drill.sword_shield_close"] == 0.0
    assert access["drill.formation_maneuver"] == 1.0
    formation["equipment_units_by_role"]["line_infantry"] = 1000
    formation["equipment_condition_by_role"]["line_infantry"] = 0.0
    access = formation_drill_access(REGISTRY, "program.line_infantry", formation, role="line_infantry")
    assert access["drill.spear_shield_line"] == 0.0
    assert access["drill.sword_shield_close"] == 0.0


def test_current_tang_qin_detachment_and_unified_house_training_coverage() -> None:
    """Every current Tang/assigned-Qin standing formation resolves to a closed program."""
    owner_index = json.loads((ROOT / "state/index/owner-index.json").read_text(encoding="utf-8"))["owners"]
    exact_expected = {
        "char_tang_wei": "program.tang_field_senior_command",
        "char_tang_kai": "program.tang_heir_child",
        "char_tang_zhu": "program.commander_combined_arms",
        "char_tang_ling": "program.tang_field_senior_command",
        "char_lin_zhen": "program.tang_field_senior_command",
        "char_gao_yun": "program.commander_infantry",
        "char_han_qiu": "program.commander_infantry",
        "char_duan_jin": "program.commander_cavalry",
        "char_shen_rui": "program.commander_cavalry",
        "char_wei_jian": "program.commander_combined_arms",
        "char_shin": "program.commander_combined_arms",
    }
    for person_ref, expected in exact_expected.items():
        person = json.loads((ROOT / owner_index[person_ref]).read_text(encoding="utf-8"))
        assert resolve_program_ref(REGISTRY, person=person) == expected, person_ref

    role_expected = {
        "house_infantry": "program.house_infantry",
        "house_cavalry": "program.house_cavalry",
    }
    for role, expected in role_expected.items():
        assert resolve_program_ref(REGISTRY, role=role) == expected, role

    for support_program in ("program.engineer", "program.logistics", "program.signal", "program.medical"):
        assert support_program in REGISTRY.get("programs", REGISTRY)
    for removed_role in (
        "house_guard", "guardian_cavalry", "tang_champion", "trainee", "junior_disciple",
        "general_disciple", "senior_disciple", "bastion_engineer", "bastion_logistics",
        "bastion_signal", "bastion_medical", "sapper", "support_staff",
    ):
        assert removed_role not in REGISTRY.get("role_programs", {})

    qin_refs = {
        "formation_high_guard_qin_a", "formation_high_guard_qin_b",
        *{f"formation_black_banner_{n:02d}{half}" for n in range(1, 5) for half in ("a", "b")},
    }
    found_qin: set[str] = set()
    found_house = 0
    qin_role_programs = {
        "line_infantry": "program.line_infantry",
        "archer": "program.archer",
        "light_cavalry": "program.cavalry",
        "heavy_cavalry": "program.heavy_cavalry",
    }
    for path in sorted((ROOT / "state/formations").glob("*.json")):
        formation = json.loads(path.read_text(encoding="utf-8"))
        ref = str(formation.get("formation_ref", ""))
        owner_force = str(formation.get("owner_force_ref", ""))
        relevant = ref in qin_refs or owner_force == "force_house_tang"
        if not relevant:
            continue
        if ref in qin_refs:
            found_qin.add(ref)
        if owner_force == "force_house_tang":
            found_house += 1
        composition = formation.get("composition", {})
        assert isinstance(composition, dict) and composition, ref
        for role, count in composition.items():
            if int(count or 0) <= 0:
                continue
            program_ref = resolve_program_ref(REGISTRY, role=str(role), training_ref=str(formation.get("training_ref") or "") or None)
            assert program_ref in REGISTRY["programs"], (ref, role, program_ref)
            if owner_force == "force_house_tang":
                assert str(role) in role_expected
                allowed = {role_expected[str(role)]}
                if str(role) == "house_infantry":
                    allowed.add("program.house_infantry_outer_wall")
                assert program_ref in allowed, (ref, role, program_ref)
            if ref in qin_refs:
                assert str(role) in qin_role_programs
                assert program_ref == qin_role_programs[str(role)], (ref, role, program_ref)
    assert found_qin == qin_refs
    assert found_house > 0

    # Retired institution-specific command curricula must not remain on live sheets.
    retired = {"program.bastion_senior_command", "program.sword_officer", "program.house_guard", "program.guardian_cavalry", "program.tang_champion"}
    for path in sorted((ROOT / "state/char").glob("*.json")):
        person = json.loads(path.read_text(encoding="utf-8"))
        contract = person.get("activity_contract") if isinstance(person.get("activity_contract"), dict) else {}
        assert contract.get("training_program_ref") not in retired, path.name

def test_retired_disciple_label_has_no_automatic_promotion_or_live_progression_authority(campaign) -> None:
    from sword_runtime.production_planner import ProductionCampaignPlanner
    from sword_runtime.training_promotion import exact_promotion_facts

    planner = ProductionCampaignPlanner(campaign)
    person = _person(role="Inner Walls Senior Disciple")
    assert exact_promotion_facts(planner, person) == {}
    assert planner.read_optional("game/data/mil/sword-manor-progression.json") is None

