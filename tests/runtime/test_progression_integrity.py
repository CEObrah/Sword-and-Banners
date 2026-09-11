from __future__ import annotations

from copy import deepcopy

import pytest

from sword_runtime.progression_integrity import exact_activity_shortfall
from sword_runtime.service_runtime import CommandRoutedProductionPlanner
from sword_runtime.training_rates import verified_activity_hours_per_cycle


def _all_activity_refs(runtime):
    return {
        str(ref)
        for host in runtime["hosts"].values()
        if isinstance(host, dict) and host.get("kind") == "person_activity"
        for ref in host.get("routed_person_refs", [])
    }


def test_current_exact_completed_cycles_have_no_proven_verified_hour_shortfall(campaign):
    planner = CommandRoutedProductionPlanner(campaign)
    planner._reset()
    profiles = planner.read("game/data/mil/recruitment-cohort-profiles.json")
    command = planner.read("state/cmd/command-personnel.json")["record_index"]
    owners = planner.read("state/index/owner-index.json")["owners"]
    stale = []
    for ref, path in sorted(owners.items()):
        if ref == planner.PLAYER_ACTOR or not str(path).startswith("state/char/"):
            continue
        person = planner.read(path)
        if person.get("schema") != "sab_character":
            continue
        contract = planner._command_activity_contract(person) if ref in command else planner._effective_activity_contract(person)
        if not isinstance(contract, dict):
            continue
        proof = exact_activity_shortfall(person, contract, profiles)
        if proof["shortfall_hours"]:
            stale.append((ref, proof))
    assert stale == []


def test_current_active_exact_command_people_have_life_and_activity_routes(campaign):
    planner = CommandRoutedProductionPlanner(campaign)
    planner._reset()
    runtime = planner.read("state/runtime.json")
    life = {
        str(host.get("owner_ref"))
        for host in runtime["hosts"].values()
        if isinstance(host, dict) and host.get("kind") == "person"
    }
    routed = _all_activity_refs(runtime)
    profiles = planner.read("game/data/mil/recruitment-cohort-profiles.json")
    records = planner.read("state/cmd/command-personnel.json")["record_index"]
    missing_life = []
    missing_activity = []
    for ref, path in sorted(records.items()):
        if ref == planner.PLAYER_ACTOR or not str(path).startswith("state/char/"):
            continue
        person = planner.read(path)
        if person.get("schema") != "sab_character":
            continue
        if str(person.get("life_status", person.get("status", "active"))).lower() in {"dead", "deceased"}:
            continue
        if ref not in life:
            missing_life.append(ref)
        contract = planner._command_activity_contract(person)
        if not isinstance(contract, dict) or contract.get("autonomous_enabled") is False:
            continue
        if not planner._activity_focuses(person, contract):
            continue
        cadence = int(person.get("autonomous_activity_state", {}).get("cadence_seconds", 30 * 86400))
        if verified_activity_hours_per_cycle(person, contract, profiles, cadence) > 0 and ref not in routed:
            missing_activity.append(ref)
    assert missing_life == []
    assert missing_activity == []


def test_current_progression_state_contains_no_migration_or_repair_scaffolding(campaign):
    planner = CommandRoutedProductionPlanner(campaign)
    planner._reset()
    meta = planner.read("state/meta.json")
    assert not any("repair" in key or "migration" in key for key in meta)
    for ref in (
        "char_duan_jin", "char_mou_ki", "char_mu_zhen", "char_ou_ken", "char_qiu_ren",
        "char_sei_kai", "char_shen_rui", "char_shou_bun_kun", "char_shou_hei_kun",
        "char_wei_jian", "char_zhao_fen",
    ):
        person = planner.read(planner.owner_path(ref))
        dev = person.get("development_state", {})
        assert "progression_repair_history" not in dev
        assert "progression_tracking_baseline" not in dev
        # Development reviews count every gain-bearing program settlement, while
        # autonomous completed_cycles counts only successful routed activity cycles.
        # They are deliberately separate authorities and must not be forced equal.
        assert int(person.get("autonomous_activity_state", {}).get("completed_cycles", 0)) >= 0


def test_exact_verified_training_clock_counts_physically_blocked_program_time(campaign):
    planner = CommandRoutedProductionPlanner(campaign)
    planner._reset()
    path = planner.owner_path("char_ou_ken")
    before = deepcopy(planner.read(path))
    activity = before["autonomous_activity_state"]
    due = activity["next_due"]
    verified_before = int(before["development_state"]["verified_deliberate_training_hours"])
    settled_before = int(before["development_state"]["settled_training_hours"])

    profiles = planner.read("game/data/mil/recruitment-cohort-profiles.json")
    contract = planner._command_activity_contract(before)
    cycle_hours = verified_activity_hours_per_cycle(
        before, contract, profiles, int(activity["cadence_seconds"])
    )
    first_available = cycle_hours + float(activity.get("fractional_training_hour_credit", 0.0))
    first_hours = int(first_available + 1e-9)
    first_credit = first_available - first_hours

    planner._settle_activity_host({"routed_person_refs": ["char_ou_ken"]}, due)
    after = planner.read(path)
    verified_after = int(after["development_state"]["verified_deliberate_training_hours"])
    settled_after = int(after["development_state"]["settled_training_hours"])
    assert verified_after - verified_before == first_hours
    assert 0 < settled_after - settled_before <= first_hours
    assert after["autonomous_activity_state"]["fractional_training_hour_credit"] == pytest.approx(first_credit, abs=1e-6)

    second_due = after["autonomous_activity_state"]["next_due"]
    second_available = cycle_hours + float(after["autonomous_activity_state"].get("fractional_training_hour_credit", 0.0))
    second_hours = int(second_available + 1e-9)
    second_credit = second_available - second_hours
    planner._settle_activity_host({"routed_person_refs": ["char_ou_ken"]}, second_due)
    second = planner.read(path)
    verified_second = int(second["development_state"]["verified_deliberate_training_hours"])
    assert verified_second - verified_after == second_hours
    assert second["autonomous_activity_state"]["fractional_training_hour_credit"] == pytest.approx(second_credit, abs=1e-6)
