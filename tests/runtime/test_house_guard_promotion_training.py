from __future__ import annotations

import copy
import json
from pathlib import Path

from sword_runtime.cohort_personnel import validate_cohort_ledger
from sword_runtime.production_planner import ProductionCampaignPlanner

ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def test_house_tang_has_only_two_active_troop_species() -> None:
    force = _read("state/forces/house-tang.json")
    assert force["authorized_by_role"] == {"house_infantry": 164060, "house_cavalry": 12000}
    assert set(force.get("available_by_role", {})) <= {"house_infantry", "house_cavalry"}
    validate_cohort_ledger(force)


def test_house_training_registry_contains_only_current_house_programs() -> None:
    registry = _read("game/data/mil/deterministic-training-programs.json")
    current = {"program.house_infantry", "program.house_cavalry", "program.house_infantry_outer_wall"}
    assert current <= set(registry["programs"])
    retired = {
        "program.house_guard", "program.guardian_cavalry", "program.tang_champion",
        "program.sword_officer", "program.sword_trainee", "program.sword_junior",
        "program.sword_general", "program.sword_senior",
    }
    assert not (retired & set(registry["programs"]))
    assert not (retired & set(registry.get("program_aliases", {})))


def test_house_role_and_training_refs_resolve_to_current_programs() -> None:
    registry = _read("game/data/mil/deterministic-training-programs.json")
    assert registry["role_programs"]["house_infantry"] == "program.house_infantry"
    assert registry["role_programs"]["house_cavalry"] == "program.house_cavalry"
    refs = registry["training_ref_programs"]
    assert refs["train.house_tang.house_infantry"] == "program.house_infantry"
    assert refs["train.house_tang.house_cavalry"] == "program.house_cavalry"
    assert refs["train.house_tang.house_infantry_outer_wall"] == "program.house_infantry_outer_wall"


def test_all_live_house_formations_use_only_infantry_or_cavalry() -> None:
    owners = _read("state/index/owner-index.json")["owners"]
    live = 0
    for ref, rel in owners.items():
        if not ref.startswith("formation_") or not str(rel).startswith("state/formations/"):
            continue
        formation = _read(rel)
        if formation.get("owner_force_ref") != "force_house_tang":
            continue
        live += 1
        assert set(formation.get("composition", {})) <= {"house_infantry", "house_cavalry"}
    assert live > 40


def test_monthly_house_training_preserves_species_and_headcount(campaign) -> None:
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    before = copy.deepcopy(planner.read("state/forces/house-tang.json"))
    runtime = planner.read("state/runtime.json")
    host = next(h for h in runtime["hosts"].values() if isinstance(h, dict) and h.get("kind") == "house_tang_training")
    at = str(host["next_due"])
    planner._autonomy_house_tang_training(host, 1, at)
    after = planner.read("state/forces/house-tang.json")
    assert after["headcount"] == before["headcount"] == 176060
    assert after["authorized_by_role"] == before["authorized_by_role"]
    before_roles = {cid: row.get("role") for cid, row in before["cohort_ledger"]["cohorts"].items()}
    after_roles = {cid: row.get("role") for cid, row in after["cohort_ledger"]["cohorts"].items()}
    assert all(after_roles.get(cid) == role for cid, role in before_roles.items())
    assert set(after_roles.values()) <= {"house_infantry", "house_cavalry"}
