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


def test_progression_repair_is_explicit_and_preserves_review_count(campaign):
    planner = CommandRoutedProductionPlanner(campaign)
    planner._reset()
    expected = {
        "char_duan_jin": 1344,
        "char_mou_ki": 504,
        "char_mu_zhen": 1344,
        "char_ou_ken": 56,
        "char_qiu_ren": 1344,
        "char_sei_kai": 56,
        "char_shen_rui": 1344,
        "char_shou_bun_kun": 56,
        "char_shou_hei_kun": 56,
        "char_wei_jian": 1344,
        "char_zhao_fen": 1344,
    }
    for ref, hours in expected.items():
        person = planner.read(planner.owner_path(ref))
        row = person["development_state"]["progression_repair_history"][-1]
        assert row["reconciled_verified_hours"] == hours
        assert row["historical_instructor_claim"] is False
        assert row["historical_location_claim"] is False
        assert person["development_state"]["completed_reviews"] == person["autonomous_activity_state"]["completed_cycles"]
    meta = planner.read("state/meta.json")["last_progression_integrity_repair"]
    assert meta["repaired_exact_people"] == 11
    assert meta["repaired_exact_hours"] == 8792


def test_exact_verified_training_clock_counts_physically_blocked_program_time(campaign):
    planner = CommandRoutedProductionPlanner(campaign)
    planner._reset()
    path = planner.owner_path("char_ou_ken")
    before = deepcopy(planner.read(path))
    activity = before["autonomous_activity_state"]
    due = activity["next_due"]
    verified_before = int(before["development_state"]["verified_deliberate_training_hours"])
    settled_before = int(before["development_state"]["settled_training_hours"])

    planner._settle_activity_host({"routed_person_refs": ["char_ou_ken"]}, due)
    after = planner.read(path)
    verified_after = int(after["development_state"]["verified_deliberate_training_hours"])
    settled_after = int(after["development_state"]["settled_training_hours"])
    assert verified_after - verified_before == 205
    assert 0 < settled_after - settled_before <= 205
    assert after["autonomous_activity_state"]["fractional_training_hour_credit"] == pytest.approx(0.714286, abs=1e-6)

    second_due = after["autonomous_activity_state"]["next_due"]
    planner._settle_activity_host({"routed_person_refs": ["char_ou_ken"]}, second_due)
    second = planner.read(path)
    verified_second = int(second["development_state"]["verified_deliberate_training_hours"])
    assert verified_second - verified_after == 206
    assert second["autonomous_activity_state"]["fractional_training_hour_credit"] == pytest.approx(0.428572, abs=1e-6)
